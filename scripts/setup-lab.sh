#!/usr/bin/env bash
# =============================================================================
# setup-lab.sh — MOS 4 "Eyes Everywhere"
#
# Brings up 3 fleet nodes + the central collector (sdc-collector). Plants a
# per-host telemetry-id nonce at /etc/sdc/node-id on each node (the agent reports
# it, proving live delivery), points each node at the collector BY NAME via
# /etc/hosts (the relocation capstone rewrites this), and records the gitignored
# .lab/baseline.json the grader reads.
# =============================================================================
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
ROOT_DIR="$(dirname "$SCRIPT_DIR")"
DOCKER_DIR="$ROOT_DIR/.docker"
SSH_DIR="$DOCKER_DIR/ssh-keys"
LAB_DIR="$ROOT_DIR/.lab"

NODES=(sdc-web sdc-db sdc-comms)
COLLECTOR_IP="172.30.0.20"

echo ""
echo "=============================================="
echo "  STARFALL DEFENCE CORPS ACADEMY"
echo "  MOS 4 — Eyes Everywhere"
echo "  Deploying fleet + collector..."
echo "=============================================="
echo ""

if ! python3 -m venv --help &>/dev/null; then
    echo "  ERROR: python3-venv is not installed (apt install python3-venv)."; exit 1
fi
if [ ! -d "$ROOT_DIR/venv" ]; then
    echo "  Setting up Python environment..."
    python3 -m venv "$ROOT_DIR/venv"
    "$ROOT_DIR/venv/bin/pip" install -q -r "$ROOT_DIR/requirements.txt"
    echo "  Python environment ready."; echo ""
fi

if [ ! -f "$SSH_DIR/cadet_key" ]; then
    echo "  Generating SSH credentials..."
    mkdir -p "$SSH_DIR"
    ssh-keygen -t ed25519 -f "$SSH_DIR/cadet_key" -N "" -C "cadet@starfall-academy" -q
    cp "$SSH_DIR/cadet_key.pub" "$SSH_DIR/authorized_keys"
    chmod 600 "$SSH_DIR/cadet_key"; chmod 644 "$SSH_DIR/authorized_keys"
fi
mkdir -p "$ROOT_DIR/workspace/.ssh"
cp "$SSH_DIR/cadet_key" "$ROOT_DIR/workspace/.ssh/cadet_key"
chmod 600 "$ROOT_DIR/workspace/.ssh/cadet_key"

mkdir -p "$LAB_DIR"; chmod 777 "$LAB_DIR" 2>/dev/null || true
rm -f "$LAB_DIR/events.jsonl" "$LAB_DIR/status.json" "$LAB_DIR/baseline.json" 2>/dev/null || true

echo "  Building fleet + collector images..."
docker compose -f "$DOCKER_DIR/docker-compose.yml" up -d --build 2>&1 | sed 's/^/    /'

echo ""
echo "  Waiting for the fleet's SSH..."
for node in sdc-web:2221 sdc-db:2222 sdc-comms:2223; do
    name="${node%%:*}"; port="${node##*:}"
    for i in $(seq 1 40); do
        if ssh -o StrictHostKeyChecking=no -o UserKnownHostsFile=/dev/null -o ConnectTimeout=1 \
            -i "$SSH_DIR/cadet_key" cadet@localhost -p "$port" exit 2>/dev/null; then
            echo "    $name (port $port): ONLINE"; break
        fi
        [ "$i" -eq 40 ] && echo "    $name (port $port): TIMEOUT — 'docker compose logs $name'"
        sleep 1
    done
done

echo ""
echo "  Waiting for the collector (sdc-collector)..."
RANGE="OFFLINE"
for i in $(seq 1 40); do
    if curl -sf -m 2 http://localhost:9000/healthz >/dev/null 2>&1; then RANGE="ONLINE"; break; fi
    sleep 1
done
echo "    Collector: ${RANGE}"
[ "$RANGE" = "ONLINE" ] || { echo "    ERROR: collector never answered — 'docker compose logs sdc-collector'."; exit 1; }

# --- Attestation: plant per-host nonce + point node at the collector by name ---
echo ""
echo "  Arming the range (per-host telemetry-id + collector mapping)..."
ATTEST_TSV="$(mktemp)"; : > "$ATTEST_TSV"
armed_ok=1
for node in "${NODES[@]}"; do
    nonce="$(openssl rand -hex 8 2>/dev/null || head -c 8 /dev/urandom | od -An -tx1 | tr -d ' \n')"
    docker exec "$node" bash -c "mkdir -p /etc/sdc && echo '$nonce' > /etc/sdc/node-id"
    # Resolve the collector by NAME (capstone rewrites this to .21).
    docker exec "$node" bash -c "cp /etc/hosts /tmp/h && grep -v ' sdc-collector\$' /tmp/h > /etc/hosts; echo '$COLLECTOR_IP sdc-collector' >> /etc/hosts"
    docker exec "$node" test -f /etc/sdc/node-id || armed_ok=0
    printf '%s\t%s\n' "$node" "$nonce" >> "$ATTEST_TSV"
    echo "    ${node}: telemetry-id planted, collector mapped ${COLLECTOR_IP}"
done
[ "$armed_ok" -eq 1 ] || { rm -f "$ATTEST_TSV"; echo "  ERROR: range failed to arm — 'make reset'."; exit 1; }

python3 - "$ATTEST_TSV" "$COLLECTOR_IP" "$LAB_DIR/baseline.json" <<'PY'
import json, sys
tsv, cip, out = sys.argv[1], sys.argv[2], sys.argv[3]
nodes = {}
with open(tsv) as f:
    for line in f:
        line = line.rstrip("\n")
        if not line:
            continue
        name, nonce = line.split("\t")
        nodes[name] = {"nonce": nonce}
json.dump({"schema": 1, "nodes": nodes, "collector": {"ip": cip}},
          open(out, "w"), indent=2)
PY
rm -f "$ATTEST_TSV"
echo "    Baseline recorded: .lab/baseline.json"

echo ""
echo "=============================================="
echo "  Fleet ONLINE — and DARK. The collector sees nothing yet."
echo ""
echo "  Deploy your telemetry role so every node's logs, audit"
echo "  events, and agent reports reach the collector."
echo ""
echo "  Your workspace: workspace/    Start: docs/BRIEFING.md"
echo "  Verify:         make test"
echo "=============================================="
echo ""

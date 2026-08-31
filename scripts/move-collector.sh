#!/usr/bin/env bash
# =============================================================================
# move-collector.sh — The Phantom Logstash relocates the SIEM (capstone).
#
# Tells the collector to bring up its new address (.21) and drop the old one
# (.20), then rewrites each node's /etc/hosts so `sdc-collector` now resolves to
# .21. A telemetry config that referenced the collector BY NAME re-resolves on
# the next role run + rsyslog restart and keeps delivering; a config that pinned
# 172.30.0.20 goes blind. The grader drives this in Phase 5.
# =============================================================================
set -euo pipefail
NEW_IP="172.30.0.21"
NODES=(sdc-web sdc-db sdc-comms)

echo "  >> The Phantom Logstash moves the SIEM to ${NEW_IP}..."
curl -sf -m 5 -X POST http://localhost:9000/relocate >/dev/null || {
    echo "  ERROR: collector did not accept /relocate."; exit 1; }

for node in "${NODES[@]}"; do
    docker exec "$node" bash -c "cp /etc/hosts /tmp/h && grep -v ' sdc-collector\$' /tmp/h > /etc/hosts; echo '${NEW_IP} sdc-collector' >> /etc/hosts"
done
sleep 1
echo "  >> SIEM now at ${NEW_IP}; nodes re-pointed. Re-run your role to re-onboard."

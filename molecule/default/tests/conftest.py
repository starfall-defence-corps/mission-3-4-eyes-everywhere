"""
ARIA verification harness — MOS 4: Eyes Everywhere
==================================================

Grades telemetry DELIVERY, not configuration. The harness applies the cadet's
telemetry role once, then for each channel generates a fresh-nonce event on
every node (ground-truth injection via `docker exec`, independent of the cadet's
config) and polls the central collector to confirm the event actually ARRIVED.

Design principles (shared with the 2.5/2.6 range harnesses):
  - Ground truth is the gitignored `.lab/baseline.json` (per-host telemetry-id
    nonce), written at `make setup`.
  - Fresh random nonce per check + server-side receipt ⇒ pre-seeded or replayed
    data cannot satisfy a delivery assertion.
  - All-nodes: a channel passes only if every node delivered. No partial credit.
  - A dead/offline collector reads as SKIP with a re-arm note, never a false pass.
  - The collector is read over its control plane (localhost:9000) via urllib —
    never shell curl, whose output the local dev proxy rewrites.
"""
import json
import os
import secrets
import subprocess
import time
import urllib.request

import pytest

FLEET = ["sdc-web", "sdc-db", "sdc-comms"]
CTRL = "http://localhost:9000"


# -- paths / helpers ---------------------------------------------------------
def _root_dir():
    here = os.path.dirname(os.path.abspath(__file__))
    return os.path.abspath(os.path.join(here, "..", "..", ".."))


def _ws(rel=""):
    return os.path.join(_root_dir(), "workspace", rel)


def _lab_dir():
    return os.path.join(_root_dir(), ".lab")


def _capped(timeout):
    override = os.environ.get("ARIA_MAX_WAIT")
    if override:
        try:
            return min(timeout, int(override))
        except ValueError:
            pass
    return timeout


def read_baseline():
    try:
        with open(os.path.join(_lab_dir(), "baseline.json")) as f:
            return json.load(f)
    except (FileNotFoundError, ValueError, json.JSONDecodeError):
        return None


def new_nonce(prefix):
    return f"{prefix}{secrets.token_hex(6)}"


# -- collector control plane (urllib, never shell curl) ----------------------
def ctrl_get(path, timeout=5):
    try:
        with urllib.request.urlopen(CTRL + path, timeout=timeout) as r:
            return json.load(r)
    except Exception:
        return None


def ctrl_post(path, timeout=8):
    try:
        req = urllib.request.Request(CTRL + path, method="POST", data=b"")
        with urllib.request.urlopen(req, timeout=timeout) as r:
            return json.load(r)
    except Exception:
        return None


def collector_events(nonce):
    r = ctrl_get("/tel/v1/events?nonce=" + nonce)
    return (r or {}).get("events", [])


def wait_for_event(nonce, source, channel, timeout, node_nonce=None):
    """Poll the collector until an event matches (source, channel[, node_nonce])."""
    deadline = time.time() + _capped(timeout)
    while time.time() < deadline:
        for e in collector_events(nonce):
            if e.get("source") == source and e.get("channel") == channel:
                if node_nonce is None or e.get("node_nonce") == node_nonce:
                    return e
        time.sleep(1)
    return None


def deliver_all(channel, inject, timeout, node_nonced=False):
    """Inject a fresh event on every node and confirm arrival. Returns the set of
    nodes that delivered (== FLEET on full success)."""
    baseline = read_baseline() or {"nodes": {}}
    pending = {}
    for node in FLEET:
        nonce = new_nonce(channel[:4])
        inject(node, nonce)
        pending[node] = nonce
    delivered = set()
    deadline = time.time() + _capped(timeout)
    while time.time() < deadline and len(delivered) < len(FLEET):
        for node, nonce in pending.items():
            if node in delivered:
                continue
            nn = baseline["nodes"].get(node, {}).get("nonce") if node_nonced else None
            for e in collector_events(nonce):
                if e.get("source") == node and e.get("channel") == channel:
                    if nn is None or e.get("node_nonce") == nn:
                        delivered.add(node)
                        break
        if len(delivered) < len(FLEET):
            time.sleep(1)
    return delivered


# -- ansible + node probes ---------------------------------------------------
def run_ansible(args, timeout=300):
    env = dict(os.environ)
    env["ANSIBLE_CONFIG"] = _ws("ansible.cfg")
    return subprocess.run(args, capture_output=True, text=True, timeout=timeout,
                          cwd=_ws(), env=env)


def node_run(node, cmd, timeout=25):
    return subprocess.run(["docker", "exec", node, "bash", "-lc", cmd],
                          capture_output=True, text=True, timeout=timeout)


def all_nodes(probe):
    return all(node_run(n, probe).returncode == 0 for n in FLEET)


def _changed_total(recap):
    total = 0
    for line in recap.splitlines():
        for host in FLEET:
            if line.strip().startswith(host) and "changed=" in line:
                try:
                    total += int(line.split("changed=")[1].split()[0])
                except (IndexError, ValueError):
                    pass
    return total


# ===========================================================================
#  Session fixtures
# ===========================================================================
@pytest.fixture(scope="session")
def lab():
    b = read_baseline()
    if b is None:
        pytest.skip("range baseline missing — run 'make setup' first")
    if ctrl_get("/healthz") is None:
        pytest.skip("collector offline on :9000 — run 'make reset'")
    return b


@pytest.fixture(scope="session")
def onboarding(lab):
    """Apply the cadet's telemetry role once; later phases inject + poll."""
    result = {"ran": False, "rc": None, "recap": ""}
    if not os.path.isfile(_ws("site.yml")):
        return result
    run = run_ansible(["ansible-playbook", "site.yml"])
    result.update(ran=True, rc=run.returncode, recap=run.stdout or "",
                  stderr=run.stderr or "")
    time.sleep(_capped(6))   # let the agent timer fire at least once
    return result


@pytest.fixture(scope="class")
def relocated(onboarding, lab):
    """Capstone: relocate the collector, re-point the fleet, re-onboard."""
    if not onboarding.get("ran"):
        pytest.skip("role never applied")
    script = os.path.join(_root_dir(), "scripts", "move-collector.sh")
    subprocess.run(["bash", script], capture_output=True, text=True, timeout=60)
    run_ansible(["ansible-playbook", "site.yml"])   # re-onboard (name re-resolves)
    time.sleep(_capped(6))
    return ctrl_get("/status") or {}


# ===========================================================================
#  ARIA reporter
# ===========================================================================
from aria_reporter import configure  # noqa: E402

configure(
    mission_id="3-4",
    phases={
        "TestSensorsOnline":   ("1", "Sensors Online"),
        "TestSyslogDelivery":  ("2", "Logs Arrive"),
        "TestAuditDelivery":   ("3", "Audit Signal"),
        "TestAgentDelivery":   ("4", "Agent Signal"),
        "TestCapstone":        ("5", "The SIEM Moves"),
    },
    friendly={
        "test_role_applied":            "Telemetry role applied cleanly",
        "test_agent_running":           "fleetquery agent enabled on every node",
        "test_syslog_delivered":        "Node logs arrive at the collector",
        "test_audit_rules_deployed":    "Audit rules deployed fleet-wide",
        "test_audit_delivered":         "Audit-class events arrive at the collector",
        "test_agent_delivered":         "Agent events arrive (with live node identity)",
        "test_full_coverage_idempotent": "All nodes covered; role is idempotent",
        "test_survives_relocation":     "Telemetry survives the SIEM relocating",
    },
)

"""
=== STARFALL DEFENCE CORPS ACADEMY ===
ARIA Automated Verification — MOS 4: Eyes Everywhere
====================================================

Behavioural grading: for each telemetry channel, ARIA generates a fresh-nonce
event on every node and confirms it ACTUALLY ARRIVES at the collector. A config
that looks right but never delivers is blindness with paperwork — it fails.
"""
import pytest

from conftest import (
    FLEET, all_nodes, deliver_all, node_run, run_ansible, _changed_total,
)


# =========================================================================== #
# Phase 1 — Sensors Online
# =========================================================================== #
class TestSensorsOnline:
    def test_role_applied(self, onboarding):
        assert onboarding.get("ran"), (
            "ARIA: workspace/site.yml did not run. Build the telemetry role and "
            "wire it into site.yml, then 'make test'."
        )
        assert onboarding.get("rc") == 0, (
            "ARIA: your telemetry role failed to apply cleanly:\n"
            f"{(onboarding.get('stderr') or '')[-800:]}"
        )

    def test_agent_running(self, onboarding, lab):
        ok = all_nodes(
            "systemctl is-enabled fleetquery.timer >/dev/null 2>&1 && "
            "systemctl is-active fleetquery.timer >/dev/null 2>&1"
        )
        assert ok, (
            "ARIA: the fleetquery agent timer is not enabled+running on every "
            "node. Deploy the provided agent, template its config, and "
            "'enable --now' fleetquery.timer across the fleet."
        )


# =========================================================================== #
# Phase 2 — Logs Arrive (journald -> rsyslog -> collector)
# =========================================================================== #
class TestSyslogDelivery:
    def test_syslog_delivered(self, onboarding, lab):
        def inject(node, nonce):
            node_run(node, f"logger -t sdc_eyes 'mission=3-4 host={node} nonce={nonce}'")
        delivered = deliver_all("syslog", inject, timeout=30)
        assert delivered == set(FLEET), (
            "ARIA: node logs are not reaching the collector. Delivered from "
            f"{sorted(delivered)} of {sorted(FLEET)}. Forward rsyslog to the "
            "collector (by NAME) over TCP AND restart rsyslog so the rule takes "
            "effect — a forward rule that isn't applied delivers nothing."
        )


# =========================================================================== #
# Phase 3 — Audit Signal
# =========================================================================== #
class TestAuditDelivery:
    def test_audit_rules_deployed(self, onboarding, lab):
        ok = all_nodes(
            "test -f /etc/audit/rules.d/sdc.rules && "
            "grep -q sdc_identity /etc/audit/rules.d/sdc.rules"
        )
        assert ok, (
            "ARIA: identity audit rules are not deployed fleet-wide "
            "(/etc/audit/rules.d/sdc.rules with an sdc_identity key)."
        )

    def test_audit_delivered(self, onboarding, lab):
        def inject(node, nonce):
            node_run(node, f"/usr/local/bin/sdc-audit-shim emit privileged_exec {nonce}")
        delivered = deliver_all("audit", inject, timeout=30)
        assert delivered == set(FLEET), (
            "ARIA: audit-class events are not reaching the collector "
            f"({sorted(delivered)} of {sorted(FLEET)}). Deploy the audit shim so "
            "audit events ride the same journald->rsyslog pipe as your logs."
        )


# =========================================================================== #
# Phase 4 — Agent Signal + coverage/idempotence
# =========================================================================== #
class TestAgentDelivery:
    def test_agent_delivered(self, onboarding, lab):
        def inject(node, nonce):
            node_run(node, f"mkdir -p /opt/sdc-telemetry/probes && "
                           f"echo watch > /opt/sdc-telemetry/probes/{nonce}")
        delivered = deliver_all("agent", inject, timeout=50, node_nonced=True)
        assert delivered == set(FLEET), (
            "ARIA: the osquery-style agent is not delivering probe events with a "
            f"valid node identity ({sorted(delivered)} of {sorted(FLEET)}). Ensure "
            "the fleetquery timer is enabled on every node and its config points "
            "at the collector."
        )

    def test_full_coverage_idempotent(self, onboarding, lab):
        run = run_ansible(["ansible-playbook", "site.yml"])
        assert run.returncode == 0, "ARIA: a second role run failed."
        changed = _changed_total(run.stdout or "")
        assert changed == 0, (
            f"ARIA: your role is not idempotent — a second run reported "
            f"changed={changed}. Telemetry rollout must converge and stay put "
            "(use handlers for restarts; don't force changes every run)."
        )


# =========================================================================== #
# Phase 5 — The SIEM Moves (capstone)
# =========================================================================== #
class TestCapstone:
    def test_survives_relocation(self, relocated, lab):
        def inject(node, nonce):
            node_run(node, f"logger -t sdc_eyes 'mission=3-4 host={node} nonce={nonce}'")
        delivered = deliver_all("syslog", inject, timeout=45)
        assert delivered == set(FLEET), (
            "ARIA: after the Phantom Logstash relocated the SIEM, telemetry went "
            f"dark ({sorted(delivered)} of {sorted(FLEET)} recovered). A config that "
            "pins the collector's IP goes blind when it moves. Reference the "
            "collector by NAME so the fleet re-onboards automatically."
        )

---
CLASSIFICATION: LIEUTENANT COMMANDER EYES ONLY
MISSION: 3.4 — EYES EVERYWHERE
THEATRE: Starfall Defence Corps Academy
AUTHORITY: SDC Cyber Command, 2187
---

# OPERATION ORDER — MISSION 3.4: EYES EVERYWHERE

---

## 1. SITUATION

### 1a. Enemy Forces

Designation: **THE PHANTOM LOGSTASH**. Prior encounters with this adversary
ended with the Elastic Stack broken and the fleet running blind — every
hardening effort in place, and nobody able to see whether it was holding.
Post-incident review across the Academy's exercise history reached the same
conclusion every time: blue teams do not usually lose because their defences
failed. They lose because they had no idea they had been beaten. A perfectly
patched, perfectly firewalled fleet that cannot tell you what happened on it
five minutes ago is still blind.

The Phantom Logstash does not attack your fleet directly in this engagement.
It attacks your **visibility of it** — and it does so by exploiting the one
assumption telemetry configurations make carelessly: that the collector will
always be where it was when you wrote the config. Mid-mission, it will
relocate the SIEM. A fleet that referenced the collector by name re-onboards
without you lifting a finger. A fleet that hardcoded the collector's address
goes dark at the exact moment it matters.

### 1b. Friendly Forces

The **Starfall Defence Corps (SDC)** fleet — three nodes, `sdc-web`,
`sdc-db`, and `sdc-comms` — and a central collector, `sdc-collector`, that
receives everything you ship it. The fleet comes up online and **dark**: no
logs, no audit trail, no agent heartbeat reaching the collector until you
deploy telemetry.

### 1c. Attachments / Support

**ARIA** (Automated Review & Intelligence Analyst) remains assigned. ARIA
does not read your task files and score them on appearance — she applies
your role, injects a fresh, nonced event on every node for every channel,
and polls the collector's own control plane to confirm each event **actually
arrived**. Configuration that looks correct but never delivers is treated
exactly like configuration that was never written.

### 1d. Operational Tool

All operations will be conducted using **ANSIBLE** — *Automated Network for
Secure Infrastructure, Baseline Lockdown & Enforcement*. This is a
**purely defensive engagement**: you are deploying observability across
your own fleet, nothing more. You will not touch the collector directly —
you configure the fleet to report to it.

---

## 2. MISSION

Build a single Ansible role, `telemetry`, and roll it out fleet-wide via
`workspace/site.yml`, so that every node's logs, audit-class events, and
agent heartbeats reach `sdc-collector`. The role must deploy three
telemetry streams:

1. **journald → rsyslog → collector.** The core channel. A forward rule
   ships everything (`*.*`) to the collector over TCP — templated in, and
   only live once rsyslog has been restarted to pick it up.
2. **auditd (deploy + userspace shim).** Kernel audit is unreliable inside
   containers, so identity-integrity audit rules are deployed for the
   record (`/etc/audit/rules.d/sdc.rules`, watching `/etc/passwd`,
   `/etc/shadow`, `/etc/sudoers` under key `sdc_identity`), and a userspace
   shim (`/usr/local/bin/sdc-audit-shim`) emits audit-class events through
   `logger`, so they ride the same reliable journald → rsyslog pipe rather
   than depending on kernel audit actually working in a container.
3. **fleetquery agent (PROVIDED, you deploy it).** An osquery-style
   scheduled-query agent ships in `roles/telemetry/files/fleetquery`. You
   copy it into place, template its config, install its systemd
   service/timer pair, and enable the timer. It reads the node's own
   telemetry identity from `/etc/sdc/node-id`, heartbeats to the collector,
   and watches a probe directory for file-integrity events.

**End state**: every node's logs, audit-class events, and agent heartbeats
verifiably reach `sdc-collector` — and keep arriving after the Phantom
Logstash relocates it, because your role referenced the collector **by
name**, never by address.

---

## 3. EXECUTION

### 3a. Commander's Intent

A hardened fleet you cannot see is not a secured fleet — it is a fleet
you're guessing about. The skill under test is not "can you write a
template that forwards logs." It is "did you build telemetry that survives
the one thing telemetry configs always get wrong" — assuming the collector
never moves. It will. Build for that from the first task.

### 3b. Concept of Operations

Five phases, verified behaviourally — ARIA checks that events **arrive**,
not that config files exist. Full procedural detail is in **EXERCISES.md**.

| Phase | Task | Objective |
|-------|------|-----------|
| 1 | Sensors Online | The `telemetry` role applies cleanly; the fleetquery agent timer is enabled and running on every node |
| 2 | Logs Arrive | journald → rsyslog forwarding reaches the collector, fleet-wide |
| 3 | Audit Signal | Audit rules are deployed fleet-wide, and audit-class events (via the shim) reach the collector |
| 4 | Agent Signal | The fleetquery agent delivers probe events with live node identity; a second role run is idempotent |
| 5 | The SIEM Moves (capstone) | The collector relocates; a name-based config re-onboards automatically and keeps delivering |

### 3c. Fleet Assets

All nodes are accessible via SSH. Credentials are uniform across the fleet.

| Designation | Role | SSH Port |
|-------------|------|----------|
| `sdc-web` | Fleet Web Node | 2221 |
| `sdc-db` | Fleet Database Node | 2222 |
| `sdc-comms` | Fleet Comms Node | 2223 |

**SSH User**: `cadet`
**Authentication**: SSH key located at `workspace/.ssh/cadet_key`

The collector, `sdc-collector`, sits on the fleet's Docker network at
`172.30.0.20` — but that address is **not yours to hardcode**. It is range
infrastructure and it moves. ARIA reads its control plane on host port
`9000` to score delivery.

### 3d. Rules of Engagement

- This is a **defensive engagement only**. You are instrumenting your own
  fleet — you never touch the collector's infrastructure directly.
- Do not modify anything under `.docker/` — that is range infrastructure.
  Your work lives entirely in `workspace/roles/telemetry/` and
  `workspace/site.yml`.
- **Reference the collector by name** (`collector_host`, resolving to
  `sdc-collector`), never by IP. The Phantom Logstash relocates the SIEM in
  Phase 5, and a config that pinned the old address will go blind at the
  worst possible moment.
- Coverage must be **complete on every node**. A fleet with two nodes
  reporting and one silent is not observable — there is no partial credit.
- Your role must be **idempotent**. A second application should converge
  with zero changes — telemetry that reconfigures itself on every run is
  telemetry you cannot trust.
- All findings are behavioural. If ARIA cannot observe an event arriving at
  the collector, your work is not complete — regardless of how correct the
  configuration looks on disk.

---

## 4. SUPPORT

| Resource | Function | Command |
|----------|----------|---------|
| **ARIA** | Verifies telemetry delivery; reports pass/fail per phase | `make test` |
| **HINTS.md** | Operational guidance if the mission stalls | — |
| **Fleet Reset** | Rebuilds the fleet and collector from scratch | `make reset` |

`make test` applies your role once, verifies Phases 1-4 by injecting and
polling for events, then relocates the collector and re-applies your role
to verify Phase 5 — all in a single run. Unlike incident-response missions,
applying `telemetry` is not destructive, so `make test` is safe to re-run as
you iterate. Use `make reset` if you want a fully clean fleet and collector
(for example, after debugging with manual changes on a node).

Consulting **HINTS.md** is authorised at Lieutenant Commander rank. Using
available intelligence is not weakness — it is doctrine.

---

## 5. COMMAND AND SIGNAL

**Reporting**: ARIA is your automated reporting chain. Her output is your
after-action record.

**Commander's Final Order**: This mission does not end until every node's
logs, audit-class events, and agent heartbeats verifiably reach the
collector — and keep arriving after it relocates. A fleet that goes dark
the moment the SIEM moves has not been instrumented. It has been decorated.

Proceed to **EXERCISES.md** for phase-by-phase operational instructions.

---

*SDC Cyber Command — 2187 — LIEUTENANT COMMANDER EYES ONLY*

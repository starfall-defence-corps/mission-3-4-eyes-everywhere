# Mission 3.4: Eyes Everywhere — Progress Tracker

**Rank**: Lieutenant Commander
**Module**: MOS 4 · Mission 1 (Specialization)

Check each item off as you complete it. Run `make test` after each phase —
it re-scores all five phases against the live fleet and collector every
time. Applying `telemetry` is not destructive, so `make test` is always
safe to re-run; `make reset` is only needed for a fully clean fleet. If a
phase is blocked, see `docs/HINTS.md`.

---

## Phase 0: Boots on the Ground

- [ ] `make doctor` — machine is mission-ready, including `ansible-core` on your own host
- [ ] `make setup` — fleet + collector online, telemetry **dark**
- [ ] Explored the scaffolding — `roles/telemetry/tasks/{rsyslog,audit,agent}.yml` are stubs, `site.yml` and `handlers/main.yml` are already provided
- [ ] Confirmed a fresh `make test` fails every phase — that's expected, nothing is written yet

---

## Phase 1: Sensors Online

**Deliverable**: `roles/telemetry/tasks/agent.yml` deploys and enables the fleetquery agent fleet-wide.

- [ ] `files/fleetquery` copied to `/usr/local/bin/fleetquery` (mode `0755`)
- [ ] Probe directory (`{{ probe_dir }}`) created
- [ ] `/etc/sdc/fleetquery.conf` templated from `agent_url` and `probe_dir`
- [ ] `fleetquery.service` and `fleetquery.timer` installed under `/etc/systemd/system/`
- [ ] `daemon_reload` run, then `fleetquery.timer` enabled **and** started
- [ ] **ARIA checks**: role applies cleanly; `fleetquery.timer` is enabled and active on every node

---

## Phase 2: Logs Arrive

**Deliverable**: `roles/telemetry/tasks/rsyslog.yml` forwards journald to the collector.

- [ ] Forward rule templated to `/etc/rsyslog.d/99-sdc-forward.conf`
- [ ] Rule ships `*.*` over **TCP** to `{{ collector_host }}:{{ syslog_port }}` — by name, not IP
- [ ] Templating task notifies `restart rsyslog`
- [ ] **ARIA checks**: injects `logger -t sdc_eyes` on every node and confirms it reaches the collector

---

## Phase 3: Audit Signal

**Deliverable**: `roles/telemetry/tasks/audit.yml` deploys audit rules and the userspace shim.

- [ ] `/etc/audit/rules.d/sdc.rules` deployed (mode `0640`), watching `/etc/passwd`, `/etc/shadow`, `/etc/sudoers` under key `sdc_identity`
- [ ] `/usr/local/bin/sdc-audit-shim` deployed (mode `0755`)
- [ ] Shim emits audit-class events via `logger -t sdc_audit`, riding the Phase 2 pipe
- [ ] **ARIA checks**: audit rules present fleet-wide; invoking the shim on every node produces an event that reaches the collector

---

## Phase 4: Agent Signal + Coverage/Idempotence

- [ ] Agent delivers probe events dropped into `{{ probe_dir }}` on every node
- [ ] Delivered events carry each node's **live** telemetry identity (`/etc/sdc/node-id`) — not guessed or hardcoded
- [ ] A second `ansible-playbook site.yml` run reports `changed=0` fleet-wide
- [ ] **ARIA checks**: agent delivery with valid node identity on every node; full re-run is idempotent

---

## Phase 5: The SIEM Moves (Capstone)

- [ ] Every telemetry channel references the collector **by name** (`collector_host` / `agent_url`) — no hardcoded IP anywhere in `roles/telemetry/`
- [ ] `grep -rn "172.30" workspace/roles/telemetry/` returns nothing
- [ ] Telemetry keeps flowing after the collector relocates, with no manual intervention beyond the role's own re-application
- [ ] **ARIA checks**: injects a fresh syslog event on every node after relocation and confirms it reaches the collector at its new location

---

## Before You Submit

- [ ] `make test` — all five phases pass
- [ ] `make submit` — work submitted for ARIA review

**Next stop**: [MOS 5 — Battle Rattle](https://github.com/starfall-defence-corps/mission-3-5-battle-rattle)

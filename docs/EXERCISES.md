---
CLASSIFICATION: LIEUTENANT COMMANDER EYES ONLY
MISSION: 3.4 — EYES EVERYWHERE
DOCUMENT: EXERCISES — Phase-by-Phase Operational Instructions
---

# EXERCISES — MISSION 3.4: EYES EVERYWHERE

Complete each phase in sequence. Run `make test` after each phase. Do not
advance until ARIA confirms compliance.

**Two directories, two purposes:**

- **Ansible commands** (`ansible-playbook`): Run from `workspace/` where `ansible.cfg` lives.
- **Make commands** (`make test`, `make reset`): Run from the **project root** (where the `Makefile` lives).

When a phase says "Run ARIA's Verification", return to the project root first:

```bash
cd ..        # from workspace/ back to project root
make test
cd workspace # return to workspace for the next phase
```

**A note on `make test`**: it applies your `telemetry` role once (via
`workspace/site.yml`), then injects a fresh, nonced event on every node for
each channel and polls the collector's own control plane (`:9000`) to
confirm arrival — never trusting your inventory or your config files as
proof. In the same run, it relocates the collector and re-applies your role
to check Phase 5. Applying `telemetry` is not destructive, so re-running
`make test` as you iterate is always safe — no `make reset` required between
phases.

There is exactly **one role** you build in this mission:
`workspace/roles/telemetry/`, wired into `workspace/site.yml` (already
provided, unmodified). Its `tasks/main.yml` already imports
`rsyslog.yml`, `audit.yml`, and `agent.yml` in order — you fill in each of
those three files.

---

## PHASE 0: Launch the Fleet, Confirm It's Dark

> Before you can light up telemetry, you need a fleet that's actually
> silent. Launch it, then confirm nothing is reaching the collector yet.

### Step 0.1 — Preflight Check

From the **project root directory**, confirm your machine is mission-ready:

```bash
make doctor
```

This mission checks that `ansible-core` is installed **on your own
machine** — the telemetry role runs from your host, not from a lab-managed
Python environment.

### Step 0.2 — Start the Fleet and the Collector

From the **project root directory** (not `workspace/`), run:

```bash
make setup
```

This builds the Docker containers, generates SSH credentials, starts all
three fleet nodes and the central collector, plants a per-host telemetry
identity at `/etc/sdc/node-id` on each node, and points every node at the
collector **by name** (`sdc-collector`) via `/etc/hosts`.

### Step 0.3 — Orient Yourself

Everything you write lives in `workspace/`, targets your own fleet, and is
applied fleet-wide via `site.yml`. Take a look at what's already
scaffolded for you:

```bash
cd workspace
cat site.yml
cat inventory/hosts.yml
cat inventory/group_vars/all.yml
cat roles/telemetry/defaults/main.yml
cat roles/telemetry/tasks/main.yml
cat roles/telemetry/tasks/rsyslog.yml
cat roles/telemetry/tasks/audit.yml
cat roles/telemetry/tasks/agent.yml
cat roles/telemetry/handlers/main.yml
```

`tasks/rsyslog.yml`, `tasks/audit.yml`, and `tasks/agent.yml` are stubs
(a single `debug` task each) with header comments describing exactly what
"done" looks like. `handlers/main.yml` already provides the `restart
rsyslog` handler you'll need — you just have to notify it.
`inventory/group_vars/all.yml` already sets `collector_host: sdc-collector`
and the other tunables (`syslog_port`, `agent_url`, `agent_interval_seconds`,
`probe_dir`) — read them, don't hardcode them.

### Step 0.4 — Confirm the Fleet Is Actually Dark

SSH into a node and confirm there's no forward rule, no audit shim, and no
agent running yet:

```bash
make ssh-web
cat /etc/rsyslog.d/99-sdc-forward.conf   # should not exist
which sdc-audit-shim                     # should not exist
systemctl is-active fleetquery.timer     # should fail — unit not installed
exit
```

### Step 0.5 — If Things Go Wrong

If containers are in a bad state, or you need a clean start at any point:

```bash
make reset
```

This destroys and rebuilds the fleet and collector. Your work in
`workspace/roles/telemetry/` is preserved — only the lab state is reset.

---

## PHASE 1: Sensors Online

> The osquery-style agent is provided — you deploy it, you don't write it.
> Get it running fleet-wide first; it's the easiest channel to verify with
> your own eyes.

### What You Are Building

Fill in `workspace/roles/telemetry/tasks/agent.yml`.

### Step 1.1 — Understand the Objective

The agent binary already ships at `roles/telemetry/files/fleetquery` — a
stdlib-only Python script. You need to:

1. Copy it to `/usr/local/bin/fleetquery` (mode `0755`).
2. Ensure the probe directory (`{{ probe_dir }}`) exists.
3. Template its config to `/etc/sdc/fleetquery.conf`, from `agent_url` and
   `probe_dir` (`ansible.builtin.template`).
4. Install `fleetquery.service` and `fleetquery.timer` under
   `/etc/systemd/system/` (templates already exist in
   `roles/telemetry/templates/` once you add them — see HINTS if you're
   unsure of the shape).
5. `daemon_reload`, then enable **and start** `fleetquery.timer`.

### Step 1.2 — Apply and Verify

```bash
ansible-playbook site.yml
```

```bash
cd ..
make test
cd workspace
```

ARIA checks that `fleetquery.timer` is enabled **and** active on every
node — a timer that's installed but not started, or started but not
enabled, both fail this phase.

---

## PHASE 2: Logs Arrive

> The core channel. journald already captures everything on the node —
> your job is to get rsyslog to ship it to the collector, and to make sure
> the config you templated is actually loaded.

### What You Are Building

Fill in `workspace/roles/telemetry/tasks/rsyslog.yml`.

### Step 2.1 — Understand the Objective

- Template a forward rule into `/etc/rsyslog.d/99-sdc-forward.conf` that
  ships `*.*` to `{{ collector_host }}:{{ syslog_port }}` over **TCP**.
  Reference the collector by the variable — never a literal IP.
- **Notify a handler to restart rsyslog.** A forward rule sitting on disk
  that rsyslog hasn't reloaded delivers nothing. This is the entire point
  of this phase: `handlers/main.yml` already defines `restart rsyslog` —
  your templating task just needs `notify: restart rsyslog`.

### Step 2.2 — Apply and Verify

```bash
ansible-playbook site.yml
```

```bash
cd ..
make test
cd workspace
```

ARIA injects `logger -t sdc_eyes '...'` on every node directly (independent
of your config) and polls the collector for each event. If your forward
rule is templated but the handler never fired (or you forgot `notify:`
entirely), this phase fails even though the file on disk is correct —
ARIA grades delivery, not appearance.

---

## PHASE 3: Audit Signal

> Kernel audit is unreliable inside containers, so this channel has two
> parts: the audit rules themselves (deployed for the record, and checked
> for their presence), and a userspace shim that actually gets events to
> the collector reliably.

### What You Are Building

Fill in `workspace/roles/telemetry/tasks/audit.yml`.

### Step 3.1 — Understand the Objective

- Template identity-integrity audit rules to
  `/etc/audit/rules.d/sdc.rules` (mode `0640`) — watching `/etc/passwd`,
  `/etc/shadow`, and `/etc/sudoers`, tagged with key `sdc_identity`.
- Template the userspace shim to `/usr/local/bin/sdc-audit-shim`
  (mode `0755`). This is the honest part of the design: kernel `auditd`
  frequently can't run inside a container, so instead of pretending it
  does, the shim emits an audit-class event through `logger` — which rides
  the same journald → rsyslog pipe you already wired up in Phase 2, rather
  than depending on a kernel subsystem that may not be there at all.

### Step 3.2 — Apply and Verify

```bash
ansible-playbook site.yml
```

```bash
cd ..
make test
cd workspace
```

ARIA checks two things independently: that `/etc/audit/rules.d/sdc.rules`
exists fleet-wide with the `sdc_identity` key present, and that invoking
`/usr/local/bin/sdc-audit-shim emit privileged_exec <nonce>` on every node
produces an event that actually reaches the collector.

---

## PHASE 4: Agent Signal + Coverage/Idempotence

> The agent from Phase 1 needs to actually deliver — and your whole role
> needs to converge instead of re-configuring the fleet on every run.

### Step 4.1 — Verify Agent Delivery

```bash
cd ..
make test
cd workspace
```

ARIA drops a probe file into `{{ probe_dir }}` on every node and waits for
the fleetquery agent's next scheduled tick to pick it up and report it —
carrying that node's **live** telemetry identity from `/etc/sdc/node-id`,
not a guessed or hardcoded value. If Phase 1's agent config or timer isn't
right, this is where it will show up as a missed delivery rather than a
config error.

### Step 4.2 — Prove Idempotence

ARIA also re-runs `ansible-playbook site.yml` a second time and checks that
it reports `changed=0` across the fleet. Run it yourself first:

```bash
ansible-playbook site.yml
ansible-playbook site.yml   # again — should report changed=0 for every host
```

If the second run shows changes, something in your role is not converging
— a template that re-renders differently each time, or a task that forces
state instead of describing it, is the usual cause. Handlers should fire
only when a templated file's content actually changes, not unconditionally.

---

## PHASE 5: The SIEM Moves (Capstone)

> Everything above this line assumed the collector stays where it is. It
> doesn't. The Phantom Logstash relocates `sdc-collector` mid-mission —
> this phase tests whether your fleet notices.

### Step 5.1 — Understand What Happens

`make test` triggers this automatically as the last step of a full run: it
tells the collector to bring up a new address and drop the old one, then
rewrites each node's `/etc/hosts` so `sdc-collector` now resolves
somewhere new. It then re-applies your role once.

- If your `rsyslog.yml`, `audit.yml`, and `agent.yml` all referenced
  `{{ collector_host }}` / `{{ agent_url }}` (which is itself built from
  the collector's name) — as instructed in every phase above — the
  re-applied role re-renders nothing new (the hostname didn't change), and
  rsyslog/the agent simply re-resolve the name on their next connection.
  Telemetry keeps flowing straight through the move.
- If you ever hardcoded `172.30.0.20` anywhere instead of using
  `collector_host`, the fleet is now pointed at a dead address and goes
  fully dark — no amount of re-running the role fixes that, because the
  role has nothing wrong to detect.

### Step 5.2 — Run ARIA's Final Verification

```bash
cd ..
make test
cd workspace
```

For this phase, ARIA injects a fresh syslog event on every node **after**
the relocation and confirms it still reaches the collector at its new
location. This is the same delivery check as Phase 2 — the only thing that
changed is where the collector actually is.

---

## MISSION COMPLETE — DEBRIEF CHECKLIST

Before closing this mission, confirm the following:

- [ ] `telemetry` role applies cleanly via `workspace/site.yml`
- [ ] `fleetquery.timer` is enabled and active on every node
- [ ] rsyslog forwards `*.*` to `{{ collector_host }}:{{ syslog_port }}` over TCP, and the config change notifies `restart rsyslog`
- [ ] `/etc/audit/rules.d/sdc.rules` is deployed fleet-wide with the `sdc_identity` key
- [ ] `sdc-audit-shim` is deployed and emits events that reach the collector
- [ ] The fleetquery agent delivers probe events carrying each node's live telemetry identity
- [ ] A second `ansible-playbook site.yml` run reports `changed=0` fleet-wide
- [ ] Telemetry survives the collector's relocation because the collector is referenced **by name** everywhere
- [ ] `make test` reports all five phases passing

If any item is incomplete, return to the corresponding phase and complete it
before closing the mission record.

---

*SDC Cyber Command — 2187 — LIEUTENANT COMMANDER EYES ONLY*

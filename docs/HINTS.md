# Mission 3.4: Eyes Everywhere — Hints & Troubleshooting Guide

> 📚 Deeper reference: [FM-1 — Ansible Module Reference](https://github.com/starfall-defence-corps/sdc-academy/blob/main/field-manuals/FM-1-ansible-reference.md)

**Rank**: Lieutenant Commander (Minimal Scaffolding)

This guide escalates in three stages per phase: a **Nudge** (a question to
get you thinking in the right direction), **More** (the specific module and
shape to use), and a **Full Worked Solution** (the exact, verified files).
Try the Nudge first. Consulting HINTS.md at this rank is doctrine, not
weakness — but reaching straight for the full solution every time will cost
you on the missions that don't provide one.

---

## Phase 1 — Sensors Online (fleetquery agent)

### Nudge

You're not writing the agent — it already exists at
`roles/telemetry/files/fleetquery`. What are the four things a role needs to
do to take a binary someone else wrote and turn it into a running,
supervised service? (Hint: place it, configure it, give systemd units for
it, then tell systemd to actually run it.)

### More

- `ansible.builtin.file` (`state: directory`) for `{{ probe_dir }}`.
- `ansible.builtin.copy` (not `template` — it's a binary, not a Jinja file)
  for `files/fleetquery` → `/usr/local/bin/fleetquery`, mode `0755`.
- `ansible.builtin.template` for `/etc/sdc/fleetquery.conf`, filling in
  `agent_url` and `probe_dir` from role defaults / group_vars.
- Two more `template` tasks (or one looped over `fleetquery.service.j2` and
  `fleetquery.timer.j2`) writing to `/etc/systemd/system/`.
- `ansible.builtin.systemd` with `daemon_reload: true`, then a second
  `systemd` task: `name: fleetquery.timer`, `enabled: true`,
  `state: started`.

### Full Worked Solution

You need the two systemd unit templates in
`roles/telemetry/templates/fleetquery.service.j2` and `fleetquery.timer.j2`,
the config template `fleetquery.conf.j2`, and the task file itself.

**`roles/telemetry/templates/fleetquery.conf.j2`**
```ini
[fleetquery]
agent_url = {{ agent_url }}
probe_dir = {{ probe_dir }}
```

**`roles/telemetry/templates/fleetquery.service.j2`**
```ini
[Unit]
Description=SDC fleetquery scheduled-query agent

[Service]
Type=oneshot
ExecStart=/usr/local/bin/fleetquery
```

**`roles/telemetry/templates/fleetquery.timer.j2`**
```ini
[Unit]
Description=Run fleetquery every {{ agent_interval_seconds }}s

[Timer]
OnActiveSec=2s
OnUnitActiveSec={{ agent_interval_seconds }}s
AccuracySec=1s

[Install]
WantedBy=timers.target
```

**`roles/telemetry/tasks/agent.yml`**
```yaml
---
- name: Ensure the probe directory exists
  ansible.builtin.file:
    path: "{{ probe_dir }}"
    state: directory
    mode: "0755"

- name: Deploy the fleetquery agent
  ansible.builtin.copy:
    src: fleetquery
    dest: /usr/local/bin/fleetquery
    mode: "0755"

- name: Template the fleetquery config
  ansible.builtin.template:
    src: fleetquery.conf.j2
    dest: /etc/sdc/fleetquery.conf
    mode: "0644"

- name: Install fleetquery systemd units
  ansible.builtin.template:
    src: "{{ item }}"
    dest: "/etc/systemd/system/{{ item | replace('.j2', '') }}"
    mode: "0644"
  loop:
    - fleetquery.service.j2
    - fleetquery.timer.j2

- name: Reload systemd to pick up the units
  ansible.builtin.systemd:
    daemon_reload: true
  changed_when: false

- name: Enable and start the fleetquery timer
  ansible.builtin.systemd:
    name: fleetquery.timer
    enabled: true
    state: started
```

Why the `daemon_reload` matters: exactly as in Mission 2.6's beacon
teardown, systemd does not notice new (or removed) unit files just because
they changed on disk — you have to tell it to re-read them, every time the
unit files themselves change. Skipping it here means `fleetquery.timer`
either doesn't exist yet from systemd's point of view, or is still running
an old, stale unit definition.

---

## Phase 2 — Logs Arrive (rsyslog forwarding)

### Nudge

You have a working, provided handler (`restart rsyslog`) sitting unused in
`handlers/main.yml`. What single keyword on your templating task connects
"this file changed" to "fire that handler"?

### More

- `ansible.builtin.template` rendering a forward rule to
  `/etc/rsyslog.d/99-sdc-forward.conf`, mode `0644`.
- The rule uses rsyslog's `omfwd` action module, `protocol="tcp"`, target
  `{{ collector_host }}`, port `{{ syslog_port }}` — never a literal IP.
- `notify: restart rsyslog` on that same task. Nothing else in this file
  needs a handler — the forward rule is the only thing that changes
  rsyslog's runtime behaviour.

### Full Worked Solution

**`roles/telemetry/templates/99-sdc-forward.conf.j2`**
```
# Forward all logs to the SOC collector over TCP. Target the collector by NAME
# so it re-resolves if the SIEM relocates. A durable queue survives event bursts.
*.* action(type="omfwd"
           target="{{ collector_host }}" port="{{ syslog_port }}" protocol="tcp"
           action.resumeRetryCount="-1"
           queue.type="linkedList" queue.size="10000" queue.saveOnShutdown="on")
```

**`roles/telemetry/tasks/rsyslog.yml`**
```yaml
---
- name: Forward all logs to the collector
  ansible.builtin.template:
    src: 99-sdc-forward.conf.j2
    dest: /etc/rsyslog.d/99-sdc-forward.conf
    mode: "0644"
  notify: restart rsyslog
```

**Why the notify is the whole phase.** A forward rule that's correctly
templated onto disk but never applied delivers exactly nothing — rsyslog
only reads `/etc/rsyslog.d/` at startup (or reload). This is the same
lesson as Mission 2.6's `daemon_reload`, applied to a different service: a
config file on disk is not the same thing as a running service that has
seen it. ARIA's check here is entirely behavioural (does the event
arrive?), so a missing `notify:` fails silently — your playbook run stays
green, and the phase still fails.

**Verifying by hand:**
```bash
make ssh-web
sudo systemctl status rsyslog       # should show a recent restart, not the boot-time start
cat /etc/rsyslog.d/99-sdc-forward.conf
logger -t sdc_eyes "manual test"
```

---

## Phase 3 — Audit Signal (audit rules + shim)

### Nudge

The task comment says "kernel auditd is unreliable in containers." If you
can't trust the kernel subsystem to actually produce the event, what other
mechanism have you already built in Phase 2 that's proven to reach the
collector — and can you route an audit-shaped event through it instead?

### More

- Deploy `/etc/audit/rules.d/sdc.rules` with `ansible.builtin.template`,
  mode `0640` — this is deployed as ground truth, checked for its
  *presence*, not its enforcement (kernel auditd may not even be running).
- Deploy `/usr/local/bin/sdc-audit-shim` with `ansible.builtin.template`,
  mode `0755` — it's a shell script, but `template` still works for static
  content with no Jinja in it, and keeps this consistent with everything
  else in the role.
- The shim's whole job is to call `logger -t sdc_audit "..."` — riding the
  same journald → rsyslog pipe you wired up in Phase 2, rather than
  depending on the kernel audit subsystem to work at all.

### Full Worked Solution

**`roles/telemetry/templates/sdc-audit.rules.j2`**
```
## SDC identity-integrity audit rules
-w /etc/passwd  -p wa -k sdc_identity
-w /etc/shadow  -p wa -k sdc_identity
-w /etc/sudoers -p wa -k sdc_identity
```

**`roles/telemetry/templates/sdc-audit-shim.j2`**
```sh
#!/bin/sh
# sdc-audit-shim emit <audit_type> <nonce>
# Emits an audit-class event through journald so it rides the fleet's rsyslog
# pipe to the collector (kernel auditd is unreliable in containers).
[ "$1" = "emit" ] || { echo "usage: sdc-audit-shim emit <type> <nonce>" >&2; exit 2; }
logger -t sdc_audit "mission=3-4 audit_type=$2 host=$(hostname) nonce=$3"
```

**`roles/telemetry/tasks/audit.yml`**
```yaml
---
- name: Deploy identity-integrity audit rules
  ansible.builtin.template:
    src: sdc-audit.rules.j2
    dest: /etc/audit/rules.d/sdc.rules
    mode: "0640"

- name: Deploy the userspace audit shim
  ansible.builtin.template:
    src: sdc-audit-shim.j2
    dest: /usr/local/bin/sdc-audit-shim
    mode: "0755"
```

**Why this two-part design is honest, not lazy.** A role that only
deployed the audit *rules* and claimed victory would be lying about
coverage — kernel `auditd` frequently doesn't function inside an
unprivileged or lightly-privileged container, so events that depend on it
alone may simply never fire. Deploying the rules is still worth doing (it's
the artifact a real compliance audit expects to find), but the shim is what
actually guarantees delivery, by piggybacking on a channel you already
proved works in Phase 2.

**Verifying by hand:**
```bash
make ssh-db
sudo /usr/local/bin/sdc-audit-shim emit privileged_exec test123
sudo journalctl -t sdc_audit -n 5
```

---

## Phase 4 — Agent Signal + Coverage/Idempotence

### Nudge

If the agent isn't delivering probe events, is the bug more likely in
`agent.yml` (Phase 1) or somewhere else entirely? And if a second
`ansible-playbook site.yml` run shows `changed` on any host, which of your
three task files is the most likely place a value is being recomputed
differently each run?

### More

- **Agent not delivering**: confirm `fleetquery.timer` is not just
  installed but `is-active` (Phase 1's check was for enabled+active — a
  timer that's enabled but never started, or crashed after one run, looks
  fine at a glance). Also confirm `/etc/sdc/fleetquery.conf` actually
  contains a reachable `agent_url` — a typo there means the agent runs
  successfully and silently fails to deliver.
- **Idempotence broken**: the most common causes are a `shell`/`command`
  task without `changed_when: false` where one's needed, or a `template`
  task whose source renders non-deterministic content (timestamps, random
  values) on every run. None of the three task files above should need
  either — if you added anything beyond what's shown, check it first.

### Full Worked Solution

There's no new file for this phase — it's the combination of Phases 1-3
already shown above, run twice:

```bash
cd workspace
ansible-playbook site.yml
ansible-playbook site.yml
```

The second run's recap line for every host should read `changed=0`. If any
host shows a nonzero `changed` count, re-check each task's mode/content
against what's shown above — the reference tasks are template-only or
systemd-enable-only, both of which are naturally idempotent when the
rendered content doesn't change between runs.

**Verifying agent delivery by hand:**
```bash
make ssh-comms
mkdir -p /opt/sdc-telemetry/probes
echo watch > /opt/sdc-telemetry/probes/manual-test
# wait one agent_interval_seconds tick, then check the collector saw it
# (ARIA does this via the control plane at :9000 — you don't have direct
#  access to it, but you can confirm the agent itself ran cleanly)
sudo systemctl status fleetquery.timer
sudo journalctl -u fleetquery.service -n 20
```

---

## Phase 5 — The SIEM Moves (Read This Before You Guess)

### Nudge

Nothing in this phase requires you to write new tasks. If Phases 2-4 all
consistently used `{{ collector_host }}` / `{{ agent_url }}` instead of a
literal address, what — if anything — should change when the collector's IP
changes underneath you?

### More

The trap here isn't a missing feature, it's a fact you might have
introduced by accident: if at any point you wrote `172.30.0.20` directly
into a template, a task's `dest:`, or anywhere else instead of using the
`collector_host` / `agent_url` variables from `defaults/main.yml` /
`inventory/group_vars/all.yml`, that hardcoded value survives the
relocation untouched — and your fleet goes dark with a green Ansible run,
because there's nothing left for the role to detect as "changed."

Grep your own role for the giveaway before you assume something's broken:

```bash
grep -rn "172.30" workspace/roles/telemetry/
# should print nothing
```

### Full Worked Solution

There is nothing to write here — this phase passes automatically if
Phases 2-4 were built exactly as shown above, because every template and
task already references `{{ collector_host }}` and `{{ agent_url }}`,
never a literal address:

- `99-sdc-forward.conf.j2` → `target="{{ collector_host }}"`
- `fleetquery.conf.j2` → `agent_url = {{ agent_url }}` (itself built from
  `collector_host` in `inventory/group_vars/all.yml`)

When the Phantom Logstash relocates the collector, `/etc/hosts` on every
node is rewritten so `sdc-collector` resolves to the new address. Your
role's next application re-renders those two templates (harmlessly — the
rendered *content* doesn't change, only what the hostname resolves to at
the OS level), and rsyslog/the agent simply reconnect to wherever
`sdc-collector` now points. No task of yours needs to know the collector
moved.

**"My Phase 5 fails even though 2-4 passed."** This means a literal IP
snuck in somewhere despite Phases 2-4 passing on the *original* address.
Re-run the grep above, and double check
`roles/telemetry/defaults/main.yml` wasn't edited to pin a literal value —
it should still read `collector_host: sdc-collector`, not an IP.

---

## General Troubleshooting

**"`ansible-playbook: command not found`."**
This mission runs Ansible from your own machine, not a lab-provided venv —
install `ansible-core` (see README Prerequisites) and confirm `make doctor`
passes.

**"`make test` reports everything skipped."**
The collector isn't answering on `:9000`, or the range baseline is
missing. Give `make setup` a few more seconds, or run `make reset`.

**"My playbook runs clean but `make test` still fails a delivery check."**
A green Ansible run only proves your tasks executed without error — it
says nothing about whether the *service* actually picked up the change
(Phase 2's `notify:` gap is the classic example) or whether the resulting
config is actually correct (a typo in `agent_url`, a firewalled path). Grade
your own work the way ARIA does: trigger the event by hand on the node and
watch for it, rather than trusting that "no errors" means "delivered."

**"make: *** No targets specified" or "make: *** No rule to make target".**
You are in the wrong directory. `make` commands must be run from the
**project root**, where the `Makefile` lives — not from `workspace/`. Run
`cd ..` to go back.

**Never edit anything under `.docker/`.**
That directory is the range itself — the fleet-node images, the collector
image, and the compose file wiring it all together. Your entire mission is
written in `workspace/roles/telemetry/`.

**Quick diagnostic sequence when something is not working:**
1. `docker ps` — are all three fleet containers and `sdc-collector` running?
2. `make ssh-web` / `make ssh-db` / `make ssh-comms` — can you still reach
   each node with your key?
3. On the node, check the specific artifact for the phase you're on:
   `cat /etc/rsyslog.d/99-sdc-forward.conf`,
   `cat /etc/audit/rules.d/sdc.rules`,
   `systemctl status fleetquery.timer`.
4. `grep -rn "172.30" workspace/roles/telemetry/` — confirm nothing is
   hardcoded.
5. If nothing above explains it, `make reset` and re-apply from a
   known-clean fleet and collector.

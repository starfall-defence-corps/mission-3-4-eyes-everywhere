# Starfall Defence Corps Academy

> 🧭 [← Master Simulation](https://github.com/starfall-defence-corps/master-simulation) · **You are here: MOS 4 · Mission 1 — Eyes Everywhere** · [🏠 Academy Hub](https://github.com/starfall-defence-corps/sdc-academy)

> ☁️ **No Docker on your machine?** Create your own copy first (Use this template), then on **your** repo: **Code → Codespaces → Create codespace** — everything is preinstalled. First boot takes ~5 min (one-time); after that it starts fast.

## MOS 4 · Mission 1: Eyes Everywhere — Deploy Telemetry at Scale

> *"The Phantom Logstash didn't break your defences. It broke your view of them."*

**Rank: Lieutenant Commander** — this is the first mission of **Module 3: Specialization** (MOS 4). More MOS-4 missions are in development.

Blue teams don't usually lose exercises because their hardening was weak. They lose because they had no idea they'd been beaten — no logs, no audit trail, no agent reporting home. This mission is not about defending anything. It's about **seeing**. You will build a single Ansible role, `telemetry`, and roll it out across a three-node fleet plus a central collector, `sdc-collector`. ARIA doesn't grade whether your config *looks* right — she grades whether telemetry events **actually arrive** at the collector. And partway through, the Phantom Logstash relocates the SIEM itself, to find out whether your fleet was built to survive that.

This is purely defensive work: you are instrumenting **your own** fleet, nothing more.

## Prerequisites

- All of Module 1 and Module 2 (roles, variables, templates, handlers, firewalling, incident response).
- [Docker Desktop](https://www.docker.com/products/docker-desktop/) (with Docker Compose v2)
- [GNU Make](https://www.gnu.org/software/make/)
- [Ansible](https://docs.ansible.com/ansible/latest/installation_guide/) (`ansible-core`) — **installed on your own machine**. Unlike earlier missions, the telemetry role runs from your host, not from a lab-managed venv.
- Python 3.10+ (for the grading environment) — on Debian/Ubuntu: `sudo apt install python3-venv`
- Git

> **Windows users**: run everything inside [WSL2](https://learn.microsoft.com/en-us/windows/wsl/install), with Docker Desktop on the WSL2 backend.

## Quick Start

```bash
# 1. Use this template on GitHub (green button, top right) to create YOUR OWN
#    copy. Set it Public, then clone it:
git clone https://github.com/YOUR-USERNAME/mission-3-4-eyes-everywhere.git
cd mission-3-4-eyes-everywhere

# 2. Check your machine is mission-ready
make doctor

# 3. Bring the fleet + collector online — telemetry starts dark
make setup

# 4. Build workspace/roles/telemetry, then apply it
cd workspace
ansible-playbook site.yml
cd ..

# 5. Ask ARIA whether telemetry is actually arriving
make test
```

6. **Read your orders**: [Mission Briefing](docs/BRIEFING.md)
7. **Work the deployment**: [Exercises](docs/EXERCISES.md)
8. **Stuck?** [Hints & Troubleshooting](docs/HINTS.md)
9. **Track progress**: [Checklist](CHECKLIST.md)
10. **Ready?** `make submit`

## Lab Architecture

```
 Your Machine
+---------------------------------------------------------------+
|  ansible-core runs HERE — not in a lab venv                    |
|  workspace/           (the only place you write Ansible)       |
|    ansible.cfg                                                 |
|    inventory/hosts.yml         (the fleet, pre-registered)     |
|    inventory/group_vars/all.yml (collector_host, syslog_port…) |
|    site.yml                    (applies roles/telemetry)       |
|    roles/telemetry/            (you build this)                |
|                                                               |
|  Docker Network: 172.30.0.0/24                                 |
|  +------------+  +------------+  +------------+   the fleet     |
|  | sdc-web    |  | sdc-db     |  | sdc-comms  |   (dark until   |
|  | .11  :2221 |  | .12  :2222 |  | .13  :2223 |   you deploy)   |
|  +------------+  +------------+  +------------+                 |
|                          |                                      |
|                          v                                      |
|  +-------------------------------+   central collector          |
|  | sdc-collector  172.30.0.20    |   (control plane on          |
|  | logs · audit events · agent   |   host port 9000 — ARIA       |
|  | heartbeats — all by NAME      |   reads it there)             |
|  +-------------------------------+                             |
+---------------------------------------------------------------+
```

The fleet comes up **online and dark**: three nodes, no telemetry flowing anywhere. Your job is to make every node's logs, audit-class events, and agent heartbeats reach `sdc-collector` — referenced by **name**, never by address, because the Phantom Logstash relocates it mid-mission. ARIA reads the collector's own control plane at `localhost:9000` to score delivery, independent of your inventory.

Only one SDC lab at a time is supported — run `make destroy` in any other mission first.

## Available Commands

```
make help       Show available commands
make doctor     Check your machine is mission-ready (Docker, ports, tools)
make setup      Deploy the fleet + central collector (3 nodes, telemetry dark)
make test       Ask ARIA to verify telemetry actually reaches the collector
make reset      Destroy and rebuild the fleet + collector
make destroy    Tear down everything (containers, keys, venv, range state)
make ssh-web    SSH into sdc-web    (172.30.0.11, port 2221)
make ssh-db     SSH into sdc-db     (172.30.0.12, port 2222)
make ssh-comms  SSH into sdc-comms  (172.30.0.13, port 2223)
make submit     Submit your work for ARIA review (branch, commit, push, PR)
```

## Mission Files

| File | Purpose |
|------|---------|
| [BRIEFING.md](docs/BRIEFING.md) | Mission briefing — **read this first** |
| [EXERCISES.md](docs/EXERCISES.md) | Phase-by-phase operational instructions (5 phases) |
| [HINTS.md](docs/HINTS.md) | Troubleshooting and hints |
| [CHECKLIST.md](CHECKLIST.md) | Progress tracker |

## How ARIA scores this mission

`make test` applies your `workspace/site.yml` (your `telemetry` role) once, then behaviourally verifies each channel: it injects a fresh, freshly-nonced event on every node and polls the collector's control plane to confirm it **actually arrived**. A config that looks right on disk but never delivers is blindness with paperwork — it fails. In the same run, ARIA relocates the collector (the Phantom Logstash's move) and re-applies your role once more, to check whether your fleet re-onboards or goes dark.

- **`make test` is safe to re-run.** Unlike incident-response missions, applying `telemetry` is not destructive — running it again just re-verifies. If you want a clean start (e.g. after debugging with manual changes on a node), `make reset` rebuilds the fleet and collector from scratch.
- **A dead or offline collector reads as skipped**, never a false pass or fail. If you see that, give `make setup` a few more seconds or run `make reset`.

## ARIA Review (Pull Request Workflow)

**ARIA** (Automated Review & Intelligence Analyst) reviews your work two ways:

**Locally** — `make test` for instant pass/fail verification. No API key needed.

**On Pull Request** — push a branch, open a PR to `main`, and ARIA posts a
qualitative review as a PR comment. To enable it, add an `ANTHROPIC_API_KEY` repo
secret (**Settings → Secrets and variables → Actions**). Without a key, PR review is
skipped and `make test` still works locally.

## Troubleshooting

**Containers won't start**: Ensure Docker Desktop is running; check for port conflicts on 2221-2223. Only one SDC lab at a time is supported — run `make destroy` in any other mission first.

**"port is already allocated" on 9000**: `mission-2-6-counterattack` publishes a service on host port 9000 too — run `make destroy` there first.

**`make test` reports everything skipped**: the collector isn't answering on `:9000` or the range baseline is missing — run `make reset`.

**`ansible-playbook` fails with "command not found"**: `ansible-core` isn't on your machine's PATH — this mission runs Ansible from your host, not a lab venv. See Prerequisites.

**Need a clean slate**: `make reset` (rebuilds the fleet + collector) or `make destroy` (full teardown).

**Docker network conflict** ("Pool overlaps..."): another Docker network is using 172.30.0.0/24 — stop it, or edit `.docker/docker-compose.yml`.

# Labyrinth — Active Deception Tarpit

**v2.2.2**

Labyrinth is Meli's built-in SSH and Telnet honeypot. It accepts every incoming login, drops the attacker into a procedurally-generated fake shell, and never lets them reach anything real. Every keystroke is emitted as a standard Cowrie-format event through Meli's ingest pipeline, so trapped sessions appear automatically in the Live Feed, Commands view, Attackers table, and the dashboard amphora.

---

## Architecture

```
Incoming connection (SSH or Telnet)
    │
    ├─ SSH ──────────── paramiko Transport
    │                   LabyrinthServerIface (accept all passwords)
    │                   SSHSession (sync, one OS thread/connection)
    │
    └─ Telnet ────────── asyncio StreamReader/StreamWriter
                        LabyrinthSession (one coroutine/connection)
                        RFC 854 negotiation (WILL ECHO / SUPPRESS-GO-AHEAD)
                              │
                    ┌─────────▼─────────┐
                    │   duck-typed       │
                    │   session surface  │
                    └─────────┬─────────┘
                              │
         ┌────────────────────┼──────────────────────┐
         │                    │                      │
    FakeFS             commands.py             TauntEngine
  per-session         74+ handlers             on_login()
  fake filesystem      ls, cat, wget…          on_command()
  (canary injection)   id, uname, ip…          on_exit()
                              │
                         sink.py
                   Cowrie-format events
                    → process_event()
                    → Live Feed / DB
```

The daemon orchestrator (`LabyrinthDaemon`) manages both listeners:
- **SSH** — `SSHListener` runs paramiko on a bounded thread pool; one OS thread per connection capped by a `BoundedSemaphore`
- **Telnet** — async server in a dedicated background thread; one asyncio coroutine per connection; per-connection read buffer capped at 8 KiB

---

## Configuration

In `~/.config/meli/config.yaml`:

```yaml
labyrinth:
  enabled: true
  host: "0.0.0.0"        # bind address
  telnet_port: 2323
  ssh_enabled: true
  ssh_port: 2222
  max_sessions: 128       # concurrent sessions cap (both protocols)
  taunts:
    intensity: subtle     # off | subtle | full
```

Or configure via Settings → Labyrinth in the GUI.

---

## Fake Shell Environment

Each session receives:
- A **per-session FakeFS** seeded from a random 64-bit value. Two attackers connecting simultaneously see slightly different directory trees, making cross-session comparison harder.
- The same **fake Debian/Ubuntu layout**: `/etc/passwd`, `/proc/cpuinfo` (randomized CPU model), `/root/.bash_history`, `/root/.ssh/`, `/root/.aws/`, `/home/admin/`, `/opt/app/`.
- A **fake hostname** seeded from the session ID (`srv-XXXX` format).

The SSH session presents an OpenSSH-style MOTD. The Telnet session presents an Ubuntu 22.04 login banner. Both are realistic enough to fool automated scanners.

---

## Subsystems

### botdetect

Weighted bot-vs-human scoring. Score 0–100 where 100 is definitely bot.

**Signals:**
- `no_motd_pause` — typed within 500ms of the prompt (human reaction time ~250ms minimum)
- `known_creds` — used a known Mirai/Gafgyt default credential pair
- `bot_commands` — typed commands from a known botnet command list (`wget`, `chmod +x`, `./[binary]`)
- `no_typos` — typed >20 characters with zero backspace corrections
- `oneshot` — connected, ran exactly one command, disconnected (typical loader behavior)
- `speed_burst` — high command rate (>5 commands in 30s with <100ms inter-command latency)
- `credential_spray` — tried >3 different usernames in the same session

Weights are tunable in `botdetect.py`. Default weights are tuned from real Mirai/Gafgyt honeypot captures.

The per-session bot profile is finalized at disconnect and the score is attached to the `cowrie.session.closed` event, which propagates to the DB and the dashboard.

### canary tokens

Bait files are injected at well-known high-value paths:
- `/root/.aws/credentials` — AWS key bait
- `/root/.ssh/id_rsa` — SSH private key bait
- `/etc/shadow` — password hash bait
- Other paths defined in `canary.py`

Any `cat` of a canary path fires a **CRITICAL alert** immediately with session ID, peer IP, protocol, and path context. The alert goes through all configured notification channels.

**Hard constraint:** Do not modify the canary token content in `canary.py`. The bait strings are deliberately formatted to be benign to GitHub's secret scanner. Modifying them may cause false positives in CI or make them less effective as bait.

### tripwire

Regex rules that fire at the command-dispatch layer before the fake command executes:
- Bump the session's bot score
- Raise the event severity to HIGH or CRITICAL
- Post a replay event tagged as `tripwire_hit`

Default rules match: downloaders (`wget http://`, `curl http://`), persistence (`crontab`, `authorized_keys`, `useradd`), lateral movement (`scp`, `rsync`), privilege escalation (`sudo su`, `passwd root`), and crypto miner indicators (`xmrig`, `minerd`).

User-defined tripwire rules can be added via Settings → Labyrinth → Tripwire Rules.

### session replay

Every session is recorded as an append-only JSONL file:
```
~/.local/share/meli/labyrinth/replay/YYYY-MM-DD/SESSION_ID.jsonl
```

Each line is a timestamped event:
```json
{"t": 1.234, "type": "command", "text": "ls -la", "session": "abc123", "ip": "1.2.3.4"}
```

Storage caps:
- 2 MiB per session (oldest lines pruned if exceeded)
- 200 MiB global (oldest sessions pruned every 5 minutes)

The **Labyrinth Replay** view plays these files back at ¼× / 1× / 2× / 8× / instant speed with full transport controls.

### replay export

Export any session in asciinema v2 JSON format for offline review:

```python
from meli.labyrinth.replay_export import export_session
export_session("SESSION_ID", "/tmp/session.cast")
```

Or via the Labyrinth Replay view → "Export…" button.

### polaroid

Posts a one-line attacker summary to configured notification channels at session close, but only for "interesting" sessions: bot score ≥ 60, or any canary trip occurred.

Example post:
```
[Labyrinth] 203.0.113.5 (CN) · SSH · 14 cmds · 127s · bot_score=87 · canary: /root/.aws/credentials
```

### cohort

Clusters sessions by command-sequence fingerprint. Two sessions are in the same cohort if their first N commands match after normalization (stripping arguments, lowercasing).

Cohort data is written to `~/.local/share/meli/labyrinth/cohorts.json`. The Labyrinth Sessions view shows cohort membership per session.

### sticky

Persists per-IP statistics across daemon restarts:
- Visit count
- First seen / last seen
- Cumulative session duration
- Running bot score average

Written to `~/.local/share/meli/labyrinth/sticky.json` at session close.

### blocklist

Export confirmed-malicious IPs in firewall-ready format:

```python
from meli.labyrinth.blocklist import export

# fail2ban format
print(export("fail2ban"))

# iptables DROP rules
print(export("iptables"))

# nftables
print(export("nftables"))

# ufw deny
print(export("ufw"))

# bare CIDR list
print(export("cidr"))
```

Threshold: IPs are included if bot_score ≥ 80 or they tripped a canary token.

### taunt engine

Configurable reveal of the honeypot identity:

| Intensity | on_login (30s in) | on_command | on_exit |
|-----------|-------------------|------------|---------|
| `off` | silent | silent | silent |
| `subtle` | "session activity is being logged" | silent | "This session has been recorded" |
| `full` | Full reveal banner | Inline taunts for hostile commands | Session summary with duration and command count |

### daily digest

The `meli-labyrinth-digest.timer` systemd unit fires at 07:00 daily and generates:
- Markdown report: top-20 noisy IPs, all canary trips, new cohorts, tripwire hit counts
- Optional PDF (if ReportLab is installed)
- Teaser posted to configured notification channels

Manual trigger:
```bash
python -m meli --digest
```

---

## SSH Host Key

The SSH listener uses an RSA-2048 host key stored at:
```
~/.local/share/meli/labyrinth/ssh_host_rsa_key
```

Generated automatically on first start. Persisted so returning attackers don't see a changed-key warning (which would blow the illusion).

---

## Security Notes

- Labyrinth **never** executes any attacker-supplied code on the host system. Every command is dispatched to a Python function in `commands.py` that returns a static or semi-dynamic string.
- The fake filesystem is entirely in-memory. No disk reads or writes occur in response to attacker commands.
- The SSH server accepts only `password` authentication (no pubkey). Keys cannot be used to enumerate information about the host.
- The per-connection read buffer is capped at 8 KiB (Telnet) and 4 KiB (SSH) to prevent buffer-bomb DoS.
- Oversized input is drained and discarded, not accumulated.
- The session semaphore (`max_sessions`) prevents thread exhaustion DoS.
- Attacker connections are isolated from each other and from the Meli GUI process.

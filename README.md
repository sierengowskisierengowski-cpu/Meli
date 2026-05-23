# Meli — Honeypot Command Center

> *Meli* is Greek for "honey" — a fitting name for a command center that watches your traps.

**v2.9.0** — Meli now ships **two complete frontends** against the same Python ingest pipeline:

- 🐝 **Web Command Center** (new in 2.9) — a React + Vite single-page app in `webui/`, served by `meli-web` (FastAPI + uvicorn) at `http://127.0.0.1:17655/`. 17 dashboards: live KPI tiles, severity breakdown, 24-hour attack-intensity chart, top-attacker leaderboard, honey-jar capacity gauge, honeypot fleet status, attackers / events / credentials / commands / payloads / sessions / services / alerts (with one-click acknowledge) / reports / botnets / IP-reputation lookup / setup wizard.
- 🖥️ **GTK4 desktop app** (the original) — full native Linux experience with the Cairo amphora, Labyrinth tarpit controls, and 16 windowed views.

Both frontends read the same SQLite database written by the Meli ingest daemon, so events captured by Cowrie / Dionaea / Conpot / Heralding / Endlessh / Labyrinth show up everywhere automatically.

**One-command launch** (no /opt install required):

```bash
./run.sh
```

This bootstraps a `.venv`, installs Python deps, runs `npm install && npm run build` in `webui/`, then launches `meli-web` on port `17655` and opens your browser. Add `--native` for the borderless Electron window, or `--no-open` for a headless server.

For a full system install (systemd user units, desktop entry, `/opt/meli`), use `./install.sh` instead — Phase 4b builds the React webui and Phase 4c (`--with-electron`) installs the Electron shell.

---

**v2.2.2** — A native **GTK4 + libadwaita** Linux desktop application for real-time honeypot monitoring, threat intelligence, and active deception. Built for security researchers, SOC analysts, homelab operators, and anyone running Cowrie, Heralding, Dionaea, or their own custom honeypot infrastructure.

**Author:** Joseph Sierengowski  
**License:** MIT  
**Platform:** Linux (COSMIC, GNOME, other GTK4 desktops)  
**Repository:** [github.com/sierengowskisierengowski-cpu/Meli](https://github.com/sierengowskisierengowski-cpu/Meli)

---

## What Makes Meli Different

Most honeypot dashboards are web applications layered on top of a database. Meli is not. It is a true native desktop application: the ingest daemon and the GUI are independent processes that communicate only through SQLite and MQTT. Close the window and the daemon keeps running, classifying events, firing alerts, and writing enrichment results. The GUI is a reader, not a requirement.

The second difference is that Meli ships its own deception engine — **Labyrinth** — rather than only consuming logs from third-party honeypots. Labyrinth is a dual-protocol SSH and Telnet tarpit built from scratch, running alongside the existing ingest pipeline. A session trapped in Labyrinth populates the Live Feed, Commands view, Sessions view, and the dashboard amphora automatically, because every keystroke is emitted as a standard Cowrie-formatted event through the same ingest pipeline everything else uses.

The signature visual element is the **amphora**: a Cairo-drawn Greek vase at the center of the dashboard that fills with amber honey as attacks accumulate, pulses warm when new events arrive, and drips when the pot is overflowing. It is decorative but purposeful — a quick glance tells you whether the honeypot is quiet, active, or under siege.

---

## Features

### 16 Dashboard Views

| View | Description |
|------|-------------|
| Dashboard | Live stat cards, severity breakdown, top attackers, recent events, amphora |
| Live Feed | Real-time MQTT event stream with pause, filter, and export |
| Geographic Map | World map with attack density (Leaflet.js via WebKitGTK) + country table |
| Attackers | Sortable IP table with full enrichment profile drawer |
| Credentials | Username/password pairs captured across all honeypots with wordlist export |
| Commands | Post-auth command analysis with intent classification |
| Payloads | Captured malware files with VirusTotal hash lookup |
| Service Stats | Per-honeypot breakdown with health status |
| Timeline | Attack volume bars with configurable periods (1h / 24h / 7d / 30d / 90d) |
| IP Reputation | Single-IP lookup across all enrichment services |
| Botnet Detection | Coordinated attack cluster analysis (shared credentials / commands / hashes) |
| Alert Rules | CRUD rule editor + full alert history with one-click acknowledge |
| Reports | Generate and browse PDF / Markdown / JSON / CSV reports |
| Settings | Full configuration panel for all subsystems |
| Labyrinth Sessions | Live tarpit status, sticky-IP roster, and recent finalized session table |
| Labyrinth Replay | Session playback with variable speed controls (¼× / 1× / 2× / 8× / instant) |

---

### Labyrinth — Active Deception Tarpit

Labyrinth is Meli's built-in SSH and Telnet honeypot. It accepts every incoming login (to harvest credentials), drops the attacker into a procedurally-generated fake shell, and never lets them reach anything real.

**Protocol support:**
- **SSH** — paramiko on a bounded thread pool; realistic MOTD, `last login` banner, PTY negotiation
- **Telnet** — asyncio; one coroutine per connection with RFC 854 negotiation (WILL ECHO / SUPPRESS-GO-AHEAD)
- Both protocols share a single duck-typed session interface so all command handlers work identically across both

**Fake environment:**
- Procedurally-generated filesystem seeded per-session — two attackers comparing notes see slightly different trees
- 74+ fake shell command handlers: `ls`, `cat`, `wget`, `curl`, `chmod`, `busybox`, `ps`, `id`, `uname`, `netstat`, `ip`, `crontab`, `systemctl`, and more
- Plausible Debian/Ubuntu file tree including `/etc/passwd`, `/proc/cpuinfo`, `/root/.bash_history`, `/root/.aws/`, and other high-value bait paths

**Subsystems:**

| Subsystem | Description |
|-----------|-------------|
| **botdetect** | Weighted bot-vs-human scoring (0–100) from timing and command signals; weights tuned from real Mirai/Gafgyt captures; full auditable signal list per session |
| **canary tokens** | Bait files injected into the fake filesystem; any `cat` of a canary path fires a CRITICAL alert immediately with session, IP, and path context |
| **tripwire** | Regex rules that bump the bot score and raise event severity when hostile commands (downloaders, persistence mechanisms, privilege escalation) are observed |
| **session replay** | Every session is written as an append-only JSONL file; the Labyrinth Replay view plays it back at variable speed with full transport controls |
| **replay export** | Export any session as an asciinema-compatible JSON file for offline review or sharing |
| **polaroid** | Automatically posts a one-line attacker summary to configured notification channels for high-value sessions (bot score ≥ threshold or any canary trip) |
| **cohort** | Clusters sessions by command-sequence fingerprint to group botnet variants and identify coordinated campaigns |
| **sticky** | Cross-restart IP tracking — the sticky roster persists visit counts, last-seen timestamps, and cumulative bot scores so returning IPs are recognized immediately |
| **blocklist** | Exports confirmed-malicious IPs in fail2ban, iptables, nftables, ufw, or bare CIDR format for immediate firewall enforcement |
| **taunt engine** | Operator-configurable reveal intensity: `off` (silent tarpit), `subtle` (session-logged notice after 30s), or `full` (explicit tarpit reveal with session summary on exit) |
| **daily digest** | 24-hour Markdown (+ optional PDF) summary: top noisy IPs, all canary trips, new cohorts, tripwire hit counts; posts a teaser to notification channels |

All Labyrinth events feed through Meli's standard ingest pipeline, so the Live Feed, Commands view, Attackers table, and the dashboard amphora all reflect Labyrinth activity without any special handling.

---

### Atrium — Kiosk / Wall-Monitor Mode

Atrium is an opt-in fullscreen visualization designed for a wall-mounted monitor. It is lazily imported at runtime so it adds zero overhead to normal Meli operation — if you never invoke it, it is never loaded.

**Three launch paths:**
1. Sidebar button in the main window
2. F12 keyboard shortcut
3. `meli --kiosk` command-line flag

**Display layout (1920×1080 target, scales to any size):**
- **Radar scope** — animated sweep with blips for active sessions
- **Amphora** — the same Cairo honey-pot widget as the dashboard, rendered at 3× scale
- **Terminal stream** — scrolling live session activity feed (connects, auth attempts, commands, canary trips)
- **24-hour heatmap** — attack intensity in 15-minute bins across the bottom bar
- **Clock bar** — UTC time, live/idle status, session count

The aurora gradient background, soft audio cues on session open/close, and red canary-trip flash overlay are synthesized from stdlib wave/math at first launch (no binary audio assets in the repository). The mouse cursor auto-hides after 3 seconds.

Normal Meli operation — the ingest daemon, all 16 views, alert routing — is completely unaffected whether Atrium is running or not.

---

### Honeypot Parsers (7)

| Parser | Handles |
|--------|---------|
| **Cowrie** | SSH/Telnet — all event IDs: `cowrie.login.failed`, `cowrie.login.success`, `cowrie.command.input`, `cowrie.session.file_download`, and more |
| **Heralding** | Multi-service credential capture (SSH, FTP, RDP, VNC, POP3, IMAP, SMTP) |
| **Dionaea** | Malware capture (SMB, HTTP, MySQL, FTP, SIP, TFTP) |
| **HTTP Honeypot** | Snare/Tanner + custom nginx JSON log format |
| **Glastopf** | Web application honeypot |
| **Mailoney** | SMTP probe honeypot |
| **Generic JSON** | Canonical Meli format + heuristic field-mapping fallback |

---

### Enrichment Services (6)

| Service | Type | Notes |
|---------|------|-------|
| **GeoLite2** (MaxMind) | Offline | City + ASN; no per-query cost; requires free MaxMind account for database download |
| **AbuseIPDB** | API key | Abuse confidence score (0–100%), report count, last-report date |
| **GreyNoise** | API key | Noise / malicious / benign classification for mass-scanner IPs |
| **VirusTotal** | API key | IP reputation + file hash malware scanning |
| **Shodan** | API key | Open ports, service banners, CVE matches |
| **IPInfo** | API key | ASN, organization, VPN/proxy/Tor detection |

All results are cached in SQLite for 24 hours (configurable TTL).

---

### Alert System

**6 notification channels:** Desktop (libnotify), Discord (webhook), Slack (webhook), Telegram (bot), SMTP Email, HTTP Webhook

- Per-rule cooldown, active hours, and severity threshold
- Alert sound per severity level via PipeWire/ALSA (`paplay` / `aplay`)
- Full alert history with one-click acknowledge

---

### Security

- **Master password** — Argon2id KDF (64 MB memory, 3 iterations) for key derivation; bcrypt for verification storage
- **TOTP 2FA** — compatible with Google Authenticator, Authy, and any TOTP app
- **Progressive lockout** — 60 s after 3 failed attempts, 5 min after 6 failed attempts; restart required beyond the hard limit
- **Ctrl+L** — instant lock; configurable auto-lock idle timeout
- **Fernet encryption at rest** — AES-128-CBC for API keys and sensitive configuration fields
- Database and config files created `chmod 600`; config directory `chmod 700`

---

### Reports

- Periods: daily, weekly, monthly, custom date range
- Formats: **PDF** (ReportLab), **Markdown**, **JSON**, **CSV**
- Jinja2 report templates (customizable)
- Scheduled automatic generation

---

### Ingest Methods

- **MQTT** — subscribe to `meli/events/ingest` (Mosquitto broker on port 1883)
- **HTTP POST** — `POST http://127.0.0.1:17654/api/v1/events/ingest` with Bearer token

See [Roadmap](#roadmap) for planned ingest methods not yet implemented.

---

## Architecture

```
┌──────────────────────────────────────────────────────────────────┐
│  External Honeypots (Cowrie / Heralding / Dionaea / …)           │
│  → publish JSON events via MQTT or HTTP POST                     │
└──────────────────────────┬───────────────────────────────────────┘
                           │
┌──────────────────────────▼───────────────────────────────────────┐
│  Labyrinth Tarpit (meli/labyrinth/)                               │
│  SSH (paramiko / thread pool) + Telnet (asyncio)                  │
│  → emits Cowrie-formatted events → same ingest pipeline below     │
└──────────────────────────┬───────────────────────────────────────┘
                           │
              ┌────────────▼────────────┐
              │      meli-ingest         │  systemd user service
              │      daemon.py           │  MQTT consumer + HTTP server
              └────────────┬────────────┘
                           │
         ┌─────────────────▼─────────────────────┐
         │             processor.py               │
         │  parse → classify → store → enrich     │
         └──────────┬────────────────┬────────────┘
                    │                │
         ┌──────────▼──────┐  ┌──────▼──────────┐
         │   SQLite DB      │  │  Alert Engine    │
         │  (SQLAlchemy)    │  │  + 6 Notifiers   │
         └──────────┬──────┘  └──────────────────┘
                    │
         ┌──────────▼──────┐
         │    GTK4 UI       │  Main thread only
         │   (16 views)     │  Reads DB, subscribes MQTT
         │  [opt: Atrium]   │  Fullscreen kiosk on demand
         └─────────────────┘
```

The ingest daemon and GUI are independent processes. The GUI subscribes to `meli/events/processed` for the live feed and reads the database for all other views. Capture and classification continue when the GUI window is closed.

---

## Installation

See [docs/INSTALL.md](docs/INSTALL.md) for full instructions.

**Quick start (Arch Linux):**
```bash
git clone https://github.com/sierengowskisierengowski-cpu/Meli
cd Meli
sudo ./install.sh --phase 1    # system packages: GTK4, PyGObject, Mosquitto
./install.sh                   # Python venv, app files, desktop integration, services
meli                           # launch
```

**Quick start (Ubuntu 24.04+):**
```bash
git clone https://github.com/sierengowskisierengowski-cpu/Meli
cd Meli
sudo ./install.sh --phase 1
./install.sh
meli
```

The installer runs 9 phases: system packages → Python venv → Python dependencies → app files → desktop integration → systemd services → Mosquitto configuration → user data directories → database initialization.

---

## Connecting a Honeypot

### Cowrie via MQTT

In `etc/cowrie.cfg`:
```ini
[output_mqtt]
enabled = true
host = 127.0.0.1
port = 1883
topic = meli/events/ingest
qos = 1
```

### Any honeypot via HTTP POST

```bash
curl -X POST http://127.0.0.1:17654/api/v1/events/ingest \
  -H "Authorization: Bearer YOUR_INGEST_TOKEN" \
  -H "Content-Type: application/json" \
  -d '{
    "network": {"source_ip": "1.2.3.4", "destination_port": 22},
    "honeypot": {"type": "cowrie"},
    "action": {"type": "login_attempt",
                "details": {"username": "root", "password": "toor"}},
    "timestamp": "2024-01-15T12:00:00Z"
  }'
```

Ingest tokens are created automatically for each honeypot source you add in Settings → Honeypot Sources.

See [docs/HONEYPOT-INTEGRATION.md](docs/HONEYPOT-INTEGRATION.md) for parser-specific configuration.

---

## Development

```bash
git clone https://github.com/sierengowskisierengowski-cpu/Meli
cd Meli

# System dependencies (GTK4, PyGObject, Mosquitto)
sudo ./install.sh --phase 1

# Python dev environment
python3 -m venv --system-site-packages .venv
source .venv/bin/activate
pip install -e .

# Launch the GUI
python -m meli

# Launch ingest daemon only (no GUI)
python -m meli --daemon ingest

# Launch Atrium kiosk mode
python -m meli --kiosk

# Run the test suite
python -m pytest tests/ -v
```

### Project Structure

```
Meli/
├── meli/                        # Python package
│   ├── __main__.py              # CLI entry point (meli / meli --daemon / meli --kiosk)
│   ├── app.py                   # Adw.Application subclass
│   ├── auth.py                  # Master password, TOTP, lockout
│   ├── config.py                # YAML config singleton
│   ├── event_bus.py             # In-process publish/subscribe
│   ├── alerts/                  # Alert engine + 6 notifiers
│   │   └── notifiers/           # desktop, discord, email_smtp, slack, telegram, webhook
│   ├── classification/          # Severity rules engine + default_rules.yaml
│   ├── database/                # SQLAlchemy models, migrations, backup
│   ├── enrichment/              # abuseipdb, geolocation, greynoise, ipinfo, shodan, virustotal
│   ├── ingest/                  # MQTT + HTTP daemon + parsers/
│   │   └── parsers/             # cowrie, dionaea, generic_json, glastopf, heralding, http_honeypot, mailoney
│   ├── labyrinth/               # Native SSH+Telnet tarpit
│   │   ├── daemon.py            # LabyrinthDaemon — top-level orchestrator
│   │   ├── ssh_server.py        # paramiko-based SSH listener + SSHSession
│   │   ├── shell.py             # asyncio Telnet LabyrinthSession
│   │   ├── filesystem.py        # Per-session fake filesystem (FakeFS)
│   │   ├── commands.py          # 74 fake shell command handlers
│   │   ├── taunts.py            # Taunt engine (off / subtle / full)
│   │   ├── host_key.py          # RSA host key persistence
│   │   ├── sink.py              # Ingest pipeline bridge
│   │   ├── botdetect.py         # Bot-vs-human scoring
│   │   ├── canary.py            # Bait-file canary tokens
│   │   ├── tripwire.py          # Regex-based severity escalation
│   │   ├── replay.py            # Per-session JSONL replay recorder
│   │   ├── replay_export.py     # Asciinema-format export
│   │   ├── polaroid.py          # Auto-posted attacker summaries
│   │   ├── cohort.py            # Command-sequence fingerprint clustering
│   │   ├── sticky.py            # Cross-restart IP tracking
│   │   ├── blocklist.py         # Firewall-rule export
│   │   └── digest.py            # Daily Markdown + PDF digest service
│   ├── reports/                 # PDF/MD/JSON/CSV generation
│   └── ui/                      # GTK4 application UI
│       ├── app.py               # Window, sidebar, stack navigation
│       ├── atrium.py            # Fullscreen kiosk display (lazily imported)
│       ├── dialogs/             # Change-password and setup wizard dialogs
│       ├── widgets.py           # HoneyPotWidget (Cairo amphora) and shared widgets
│       └── views/               # 16 views (see table above)
├── tests/                       # pytest suite
├── docs/                        # Documentation
├── assets/
│   ├── icons/meli.svg           # Application icon
│   └── sounds/                  # Alert sound files
├── install.sh                   # 9-phase installer (Arch / Ubuntu / Fedora)
├── uninstall.sh                 # Uninstaller (preserves user data)
├── pyproject.toml               # Build configuration
├── requirements.txt             # Python dependencies
├── meli.desktop                 # XDG desktop entry
├── meli-ingest.service          # systemd user service
├── meli-labyrinth-digest.service # systemd oneshot for daily digest
├── meli-labyrinth-digest.timer  # systemd timer (daily at 07:00)
└── PKGBUILD                     # Arch Linux package
```

---

## Known Limitations

- **Settings → Configure 2FA button** — the TOTP configuration dialog is not yet implemented. TOTP can be configured via the first-run setup wizard.
- **Settings → Add Honeypot button** — the inline add-honeypot dialog is not yet implemented. Honeypot sources can be added via the first-run setup wizard.
- **Geographic Map** — the Leaflet.js marker layer is partially implemented; the map renders but does not place per-country attack markers.
- **Log file watch** — inotify-based direct log parsing is not yet implemented. See [Roadmap](#roadmap).

---

## Roadmap

Features planned but not yet implemented:

- Log file watcher (inotify-based, no MQTT/HTTP required)
- Network PCAP analysis mode
- Additional parsers: T-Pot, HoneyTrap, OpenCanary
- CIDR and geofence block lists in the UI
- YubiKey hardware 2FA
- PostgreSQL backend option
- Report scheduling UI and email delivery
- STIX 2.1 / TAXII 2.1 export

---

## License

MIT License — © Joseph Sierengowski

See [LICENSE](LICENSE) for full text.

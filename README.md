# Meli — Honeypot Command Center

> *Meli* is Greek for "honey" — a fitting name for a command center that watches your honeypots.

A native **GTK4 + libadwaita** Linux desktop application for real-time honeypot monitoring and threat intelligence. Built for security researchers, homelab operators, and professionals running Cowrie, Heralding, Dionaea, and other honeypot software.

**Author:** Joseph Sierengowski  
**License:** MIT  
**Platform:** Linux (COSMIC, GNOME, other GTK4 desktops)  

---

## ⚠️ Authorization, Intended Use & Legal Notice

Meli is a **defensive-security and home-lab tool.** It is designed to be run by its operator against their own infrastructure — their own honeypots, their own network, their own devices, their own lab environment. That is the only use it is designed, intended, or supported for.

**Intended for:**
- Monitoring honeypots and decoy services you have deployed on infrastructure you control.
- Capturing, analyzing, and visualizing traffic, devices, and activity on networks you own or administer.
- Threat-intelligence enrichment, alerting, reporting, and visualization for your own security monitoring.

**Not for:**
- Monitoring, capturing, or analyzing traffic on networks you do not own or are not explicitly authorized to monitor.
- Surveilling, tracking, or profiling other people, their devices, or their communications without their knowledge and consent.
- Scanning, probing, exploiting, or accessing any system you do not own or have explicit written authorization to test.
- Any activity that violates applicable local, state, federal, or international law.

**Your responsibility:** You — the operator — are solely responsible for ensuring your use of this software is lawful in your jurisdiction and authorized for the systems and networks you point it at. Laws governing network monitoring, packet capture, and wireless interception vary significantly by location. **When in doubt, don't** — get written authorization first, or limit the tool to infrastructure you unambiguously own.

**No warranty.** This software is provided "as is." The author is not liable for any misuse or for any damages arising from its use. Use entirely at your own risk.

Full notice: [**DISCLAIMER.md**](./DISCLAIMER.md). MIT license applies separately (see `LICENSE`).

---

## Features

### 14 Dashboard Views
| View | Description |
|------|-------------|
| Dashboard | Live stat cards, severity breakdown, top attackers, recent events |
| Live Feed | Real-time MQTT event stream with pause, filter, and export |
| Geographic Map | World map with attack density; Leaflet.js via WebKitGTK |
| Attackers | Sortable IP table with full enrichment profile drawer |
| Credentials | Top username/password pairs with wordlist export |
| Commands | Post-auth command analysis with intent classification |
| Payloads | Captured malware files with VirusTotal hash lookup |
| Service Stats | Per-honeypot breakdown with health status |
| Timeline | Attack volume over time with configurable period bars |
| IP Reputation | Single-IP lookup across all enrichment services |
| Botnet Detection | Coordinated attack cluster analysis (shared creds/commands/hashes) |
| Alert Rules | CRUD rule editor + full alert history with acknowledge |
| Reports | Generate PDF/Markdown/JSON/CSV reports on demand |
| Settings | Full configuration panel for all subsystems |

### Honeypot Parsers
- **Cowrie** — SSH/Telnet (all event IDs: login, command, file_download, etc.)
- **Heralding** — Multi-service credential capture (SSH, FTP, RDP, VNC, POP3, IMAP, SMTP)
- **Dionaea** — Malware capture (SMB, HTTP, MySQL, FTP, SIP, TFTP)
- **HTTP Honeypot** — Snare/Tanner + custom nginx log honeypots
- **Glastopf** — Web application honeypot
- **Mailoney** — SMTP honeypot
- **Generic JSON** — Canonical Meli format + heuristic fallback

### Enrichment Services
- **GeoLite2** (MaxMind) — Offline city + ASN geolocation, no API limit
- **AbuseIPDB** — Abuse confidence score and report history
- **GreyNoise** — Noise/malicious/benign classification
- **VirusTotal** — IP reputation + file hash malware scanning
- **Shodan** — Open ports, banners, CVE matches
- **IPInfo** — ASN, org, VPN/proxy/Tor detection

### Alert System
- 5 notification channels: Desktop, Discord, Slack, Telegram, SMTP Email, HTTP Webhook
- Per-rule cooldown, active hours, severity threshold, conditions
- Alert sound per severity level (ogg/wav via PipeWire/ALSA)
- Full alert history with one-click acknowledge

### Security
- **Master password** (Argon2id KDF + bcrypt hash)
- **TOTP 2FA** (Google Authenticator, Authy, etc.)
- Progressive lockout: 60s after 3 fails, 5min after 6 fails
- **Ctrl+L** lock / configurable auto-lock idle timeout
- Sensitive fields encrypted at rest (Fernet AES-128)

### Reports
- Daily, weekly, monthly, and custom period ranges
- Formats: **PDF** (ReportLab), **Markdown**, **JSON**, **CSV**
- Scheduled automatic generation
- Jinja2 report templates (customizable)

### Ingest Methods
- **MQTT** — Subscribe to `meli/events/ingest` topic (Mosquitto broker)
- **HTTP POST** — `POST http://127.0.0.1:17654/api/v1/events/ingest`
- **Log file watch** (coming in v1.1) — inotify-based direct log parsing

---

## Architecture

```
┌─────────────────────────────────────────────────────┐
│  Honeypots (Cowrie / Heralding / Dionaea / …)        │
│  → publish JSON events via MQTT or HTTP POST         │
└────────────────────────┬────────────────────────────┘
                         │
              ┌──────────▼──────────┐
              │   meli-ingest        │  systemd user service
              │   daemon.py          │  MQTT consumer + HTTP server
              └──────────┬──────────┘
                         │
         ┌───────────────▼───────────────────┐
         │           processor.py             │
         │  parse → classify → store → enrich │
         └───────┬───────────────────┬────────┘
                 │                   │
         ┌───────▼───────┐   ┌──────▼──────┐
         │   SQLite DB    │   │  Alert Engine│
         │  (SQLAlchemy)  │   │  + Notifiers │
         └───────┬───────┘   └─────────────┘
                 │
         ┌───────▼───────┐
         │   GTK4 UI      │  Main thread only
         │  (14 views)    │  Reads DB, subscribes MQTT
         └───────────────┘
```

The ingest daemon and GUI run independently. The GUI subscribes to `meli/events/processed` for the live feed but reads the database for all historical views. This means the GUI is optional — ingest and classification continue even when the window is closed.

---

## Installation

See [INSTALL.md](docs/INSTALL.md) for full instructions.

**Quick start (Arch Linux):**
```bash
git clone https://github.com/sierengowski/meli
cd meli
sudo ./install.sh --phase 1    # system packages (GTK4, PyGObject, Mosquitto)
./install.sh                   # Python venv + app + services
meli                           # launch
```

**Quick start (Ubuntu 24.04+):**
```bash
sudo ./install.sh --phase 1
./install.sh
meli
```

---

## Connecting a Honeypot

### Cowrie via MQTT

In `cowrie.cfg`:
```ini
[output_mqtt]
enabled = true
host = 127.0.0.1
port = 1883
topic = meli/events/ingest
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

Ingest tokens are created automatically for each honeypot you add in Settings → Honeypot Sources.

---

## Development

```bash
git clone https://github.com/sierengowski/meli
cd meli
python -m venv --system-site-packages .venv
source .venv/bin/activate
pip install -e ".[dev]"
python -m meli           # launch GUI
python -m meli --daemon ingest  # launch ingest daemon only
python -m pytest tests/  # run tests
```

### Project structure

```
meli/
├── meli/                    # Python package
│   ├── __main__.py          # CLI entry point
│   ├── app.py               # GTK4 application class
│   ├── auth.py              # Master password + TOTP
│   ├── config.py            # YAML config singleton
│   ├── alerts/              # Alert engine + 6 notifiers
│   ├── classification/      # Severity rules engine
│   ├── database/            # SQLAlchemy models + backup
│   ├── enrichment/          # IP enrichment services
│   ├── ingest/              # MQTT + HTTP + parsers
│   ├── reports/             # PDF/MD/JSON/CSV generation
│   └── ui/                  # GTK4 views (14), dialogs, widgets
├── tests/                   # pytest test suite
├── assets/
│   ├── icons/meli.svg       # Application icon
│   └── sounds/              # Alert sound files (ogg)
├── docs/                    # Documentation
├── install.sh               # Installer (Arch/Ubuntu/Fedora)
├── uninstall.sh             # Uninstaller
├── pyproject.toml           # Build config
├── requirements.txt         # Python dependencies
├── meli.desktop             # .desktop file
├── meli-ingest.service      # systemd user service
└── PKGBUILD                 # Arch Linux package
```

---

## License

MIT License — © Joseph Sierengowski

See [LICENSE](LICENSE) for full text.

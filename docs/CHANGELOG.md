# Changelog

All notable changes to Meli are documented here.

## [2.3.0] — 2026-05-22

### Added — Authorization & Intended Use

- **New mandatory wizard step: Authorization** (`meli/ui/setup_wizard.py`).
  Inserted between **Welcome** and **Password** so the operator must
  explicitly acknowledge `DISCLAIMER.md` before any data is ingested.
  The Next button (relabelled **I Agree →**) stays disabled until the
  checkbox is ticked. Acknowledgments are timestamped, recorded with
  the local user/host, and persisted to `~/.config/meli/eula.json`
  (mode 0600) by the new `meli.eula` module. Re-running the wizard
  pre-ticks the box and shows the prior acceptance timestamp.

- **Persistent authorization notice on the Labyrinth Atrium kiosk**
  (`meli/ui/atrium.py`). The `ClockBar` grew 48→66 px and now
  permanently renders **"⚠ Monitoring authorized infrastructure
  only — see DISCLAIMER.md"** beneath the title in a dim-white 11 px
  face. Designed to be readable from across a room so anyone walking
  past a wall-mounted Pi kiosk sees the operating context.

- **`meli.eula` module** (new, stdlib-only). API: `is_accepted()`,
  `accept(version)`, `get_record()`. Honors `MELI_CONFIG_DIR` for
  packaged/sandboxed installs.

### Changed — Visual polish

- **Honeycomb pattern tiled across the main window**
  (`meli/resources/css/style.css`). The same hex-cell SVG used on the
  splash now repeats over `window.meli-window` at 3.5% opacity so the
  hive motif reads at any zoom level. Zero perceptible perf cost —
  it's a single inline 56×48 data-URI SVG.

- **Wizard window size** bumped 600×500 → 640×560 to give the
  Authorization step's longer copy room to breathe without scrolling.

### Notes

- No DB migration required.
- `meli.auth` (master password + TOTP) is unchanged — `meli.eula` is
  intentionally a separate module: acceptance is a one-time
  legal/operational acknowledgment, not an authentication factor.
- Existing installs: the wizard re-runs only on first launch; for
  already-configured installs you can record acknowledgment manually
  by writing `~/.config/meli/eula.json` or simply re-running the
  wizard from Settings.

---

## [1.0.0] — 2025-05-20

### Initial Release

**Core**
- GTK4 + libadwaita native desktop application
- Master password authentication with Argon2id KDF
- TOTP 2FA (Google Authenticator, Authy compatible)
- Progressive lockout: 60s → 5min → app restart required
- Ctrl+L lock / configurable auto-lock idle timeout
- First-run setup wizard (7 steps)

**Event Ingestion**
- MQTT consumer (paho-mqtt 2.x, `meli/events/ingest` topic)
- HTTP POST ingest server on port 17654
- Per-honeypot ingest tokens (stored encrypted in DB)
- Runs as `meli-ingest.service` systemd user service

**Honeypot Parsers (7)**
- Cowrie SSH/Telnet — all event IDs (login, command, file_download, etc.)
- Heralding — multi-service credential capture
- Dionaea — malware capture (SMB, FTP, MySQL, SIP, TFTP)
- HTTP Honeypot — Snare/Tanner + custom nginx log format
- Glastopf — web application honeypot
- Mailoney — SMTP probe honeypot
- Generic JSON — canonical Meli format + heuristic fallback

**Classification Engine**
- 16 built-in rules (INFO through CRITICAL)
- YAML rule definition with conditions (eq, in, regex, exists, gte, lte)
- User-defined rules via the Alert Rules UI
- Context injection: attacker_event_count for threshold rules

**IP Enrichment (6 services)**
- MaxMind GeoLite2 — offline city + ASN (no API limit)
- AbuseIPDB — abuse confidence score
- GreyNoise — noise/malicious/benign classification
- VirusTotal — IP + file hash reputation
- Shodan — open ports, CVEs, banners
- IPInfo — ASN, org, VPN/proxy/Tor detection
- 24h result caching in SQLite (configurable TTL)

**Alert System**
- 7 notification channels: Desktop, Discord, Slack, Telegram, SMTP Email, HTTP Webhook, Sound
- Per-rule cooldown, active hours, severity threshold
- Alert sound per severity level (PipeWire/ALSA via paplay/aplay)
- Full alert history with acknowledge

**Reports**
- Types: daily, weekly, monthly, custom
- Formats: PDF (ReportLab), Markdown, JSON, CSV
- Jinja2 report templates

**Database**
- SQLite via SQLAlchemy 2.x
- WAL journal mode, foreign keys enabled
- 12 tables: events, attackers, credentials, commands, payloads, honeypots, alert_rules, alerts, api_keys, enrichment_cache, reports, audit_log
- Online backup via SQLite backup API
- VACUUM support

**GTK4 Views (14)**
1. Dashboard — stat cards, severity breakdown, top attackers, recent events, honeypot health
2. Live Feed — real-time MQTT event stream, pause/filter/export
3. Geographic Map — world map with Leaflet.js (WebKitGTK) + country table
4. Attackers — sortable IP table with enrichment profile drawer
5. Credentials — username/password pairs with wordlist export
6. Commands — post-auth command analysis with intent classification
7. Payloads — captured malware with VirusTotal hash lookup
8. Service Stats — per-honeypot breakdown with health status
9. Timeline — attack volume bars with configurable periods (1h/24h/7d/30d/90d)
10. IP Reputation — single-IP lookup across all enrichment services
11. Botnet Detection — coordinated attack cluster analysis
12. Alert Rules — CRUD editor + alert history with acknowledge
13. Reports — generate and browse reports
14. Settings — full configuration panel (categories sidebar)

**Security**
- Fernet encryption (AES-128-CBC) for API keys and sensitive data at rest
- bcrypt for master password hashing
- Database and config files: chmod 600 / 700
- API keys never logged or stored in config file plaintext

**Packaging**
- `install.sh` — Arch/Ubuntu/Fedora support, phased install
- `uninstall.sh` — preserves user data
- `PKGBUILD` — Arch Linux package
- `meli.desktop` + SVG icon
- `meli-ingest.service` — systemd user service

## [Unreleased / Roadmap]

### v1.1
- Log file watcher (inotify-based, no MQTT required)
- Network PCAP analysis mode
- Additional parsers: T-Pot, HoneyTrap, OpenCanary
- CIDR and geofence block lists

### v1.2
- YubiKey hardware 2FA
- PostgreSQL backend option
- Report scheduling UI
- Email delivery on scheduled reports

### v1.3
- Threat feed subscriptions (auto-update IoC lists)
- STIX 2.1 / TAXII 2.1 export
- Correlation rules (link events across honeypots)
- Heat map calendar view

# Changelog

All notable changes to Meli are documented here.

## [2.9.1] — 2026-06-09

### Fixed
- **Attackers:** collision-free attacker IDs — generate a stable UUID from source IP rather than relying on DB insertion order, preventing ID collisions when multiple ingestion sources report the same IP
- **Dashboard:** surface database state on load — KPI tiles and the amphora now reflect the current DB totals immediately on startup rather than waiting for the first live event

---

## [2.9.0] — 2026-06-05

### Added
- **React Web Command Center** — full second frontend in `webui/` (React + Vite + TypeScript + shadcn/ui)
  - 17 dashboard pages: live KPI tiles, severity breakdown, 24h intensity chart, top-attacker leaderboard, honey-jar capacity gauge, honeypot fleet status, attackers, events, credentials, commands, payloads, sessions, services, alerts (with one-click acknowledge), reports, botnets, IP-reputation lookup, setup wizard
  - Served by `meli-web` (FastAPI + uvicorn) at `http://127.0.0.1:17655/`
  - REST API reads the same SQLite DB as the GTK4 app — no separate backend required
- **`run.sh`** — one-command dev launcher: bootstraps `.venv`, builds `webui/`, launches `meli-web` and opens the browser; `--native` flag spawns the Electron shell; `--no-open` for headless servers
- **`meli/webapi/`** — FastAPI application and `meli-web` CLI entry point
- **Electron shell** (`electron/`) — optional borderless desktop window wrapping the web UI; installed by `install.sh --with-electron`

---

## [2.8.2] — 2026-05-31

### Fixed
- **npm build:** corrected `MeliShell` named export mismatch that caused `npm run build` to fail in CI and clean install environments

---

## [2.8.1] — 2026-05-30

### Fixed
- **React UI:** four regressions found in v2.8.0 code review — corrected TypeScript type errors, fixed broken API client base URL resolution, resolved missing Vite env variable references, and patched a React key collision in the event list

---

## [2.8.0] — 2026-05-29

### Added
- Initial React + Vite scaffold for the web command center (pre-release; `npm run build` required before serving)
- `webui/package.json`, `vite.config.ts`, `tsconfig.json`, `components.json` (shadcn/ui)
- Placeholder dashboard pages for all 17 views

---

## [2.7.20] — 2026-05-27

### Changed
- **Dashboard:** KPI sparkline height reduced to 52 px (dense, not hazy) with no vertical expand; jar glow rebuilt as a single bright AMBER halo with a constant 4-second shimmer pulse (replaces 6 stacked semi-transparent passes that were effectively invisible at runtime)

---

## [2.7.0–2.7.19] — 2026-05-15 to 2026-05-27

### Added / Changed
- **Cairo UI overhaul** — all dashboard panels repainted with Cairo directly; bypasses GTK4 CSS engine for chrome (gradients, glows, halos); consistent luminous honey aesthetic across every view
- **CairoPanel widget** (`meli/ui/widgets/cairo_panel.py`) — reusable Cairo-painted panel with amber gradient background, outer glow, gold inner halo, and warm border; wired into `dashboard._panel()` helper
- **HivePrefsGroup** — Cairo hive-panel chrome applied to all settings-style views (Settings, Setup Wizard, Alert Rules, Attackers, Botnets, IP Reputation, Payloads, Reports, Service Stats, Timeline, Live Feed)
- **KPI sparklines** — Cairo-drawn sparklines with honey-drip top stripe and state dot; 44→72 px height iterations; cylindrical honey-jar with honeycomb hex texture; amber numbered rank badges and country chips
- **Dashboard layout** — matches final mockup: giant honey-jar centerpiece (left, 420 px) with corner overlay stats; Severity + Top Attackers stacked right column; intensity chart + credentials + ticker below hero
- **Setup Wizard** moved to sidebar nav list as a pill
- **Sidebar** — M badge + amber pills + status pill; matches mockup; lands on Dashboard not Atrium by default
- **`__gtype_name__`** added to all Cairo widgets so `do_snapshot` fires correctly in GTK4
- Various GTK4 CSS compatibility fixes (removed `!important`, split border shorthand with alpha, USER priority provider)
- Bug fixes: `Event.event_data` crash (use `parsed_data` JSON column), `Credential.honeypot_service` crash (use `source_honeypots` JSON list), `HiveHeader.pack_start/add` GTK4 compat

---

## [2.6.0–2.6.2] — 2026-05-08 to 2026-05-12

### Added
- **Lock screen** — full-screen honeycomb overlay with gooey vertical honey drips; displayed on Ctrl+L or auto-lock timeout
- **Splash screen** — redesigned: fullscreen honey splat → drips → MELI logo; replaced earlier minimal splash
- Multi-resolution PNG icons added for desktop integration

### Fixed
- `install.sh` now correctly pip-installs the package inside the venv (Phase 3)

---

## [2.2.2] — 2026-05-22

### Fixed
- **Atrium:** corrected `_bg` field name in `AtriumScene` shutdown path; the background drawing area was not being stopped cleanly on window close, leaving a dangling timer

---

## [2.2.1] — 2026-05-14

### Fixed
- **Atrium:** kiosk mode launched after unlocking the main window now renders correctly; the scene was starting before the parent application window was fully mapped
- **Atrium:** fixed GLib timer leak — the aurora, radar, and heatmap timers were not removed on scene teardown, accumulating idle callbacks across open/close cycles
- **Labyrinth:** fixed background thread leak in `botdetect` — profile objects were retained in the in-memory registry after `discard()` was called if the session ended with an active timer still pending

---

## [2.2.0] — 2026-04-28

### Added
- **Atrium** — opt-in fullscreen kiosk display (`meli --kiosk`, F12, or sidebar button); lazily imported so it adds zero overhead to normal operation
  - Aurora gradient background (5 fps), radar scope (30 fps), 3× amphora centerpiece, live terminal stream, 24-hour heatmap bar
  - Synthesized WAV audio cues (session open, canary trip, close) — generated stdlib-only on first launch, no binary assets required
  - Canary-trip red full-screen flash overlay
  - CRT scanline overlay
  - Cursor auto-hides after 3 seconds; exits via Esc / F11 / Ctrl+W / corner click
- **Labyrinth Sessions view** — live daemon status panel, sticky-IP roster, and recent finalized session table (2-second auto-refresh)
- **Labyrinth Replay view** — session playback with ¼× / 1× / 2× / 8× / instant speed controls; asciinema-format export

---

## [2.1.0] — 2026-03-15

### Added
- **Labyrinth digest service** — daily 24-hour Markdown + optional PDF summary: top-20 noisy IPs, all canary trips, new cohorts, tripwire hit counts; posts teaser to notification channels; installable as `meli-labyrinth-digest.timer` systemd unit firing at 07:00
- **Labyrinth blocklist export** — `fail2ban`, `iptables`, `nftables`, `ufw`, and bare CIDR formats; "Export blocklist…" button in the Sessions view
- **Labyrinth cohort** — command-sequence fingerprint clustering to group botnet variants and identify coordinated campaigns across sessions
- **Labyrinth replay export** — asciinema-compatible JSON export from any recorded session

### Changed
- Labyrinth session replay files are now stored under `~/.local/share/meli/labyrinth/replay/<YYYY-MM-DD>/` with a 200 MiB global cap and 2 MiB per-session cap; the pruner runs lazily every 5 minutes

---

## [2.0.0] — 2026-02-01

### Added
- **Labyrinth tarpit** — Meli's native SSH + Telnet honeypot built from scratch
  - SSH listener: paramiko on a bounded thread pool; accepts every login; realistic MOTD and `last login` banner
  - Telnet listener: asyncio; RFC 854 negotiation (WILL ECHO / SUPPRESS-GO-AHEAD); Ubuntu 22.04 login banner
  - Shared procedurally-generated fake filesystem seeded per session (`FakeFS`)
  - 74+ fake shell command handlers: `ls`, `cat`, `wget`, `curl`, `chmod`, `busybox`, `ps`, `id`, `uname`, `netstat`, `ip`, `crontab`, `systemctl`, and more (`commands.py`)
  - Duck-typed session interface so all command handlers work identically across SSH and Telnet
  - **botdetect** — weighted bot-vs-human scoring 0–100 from timing + command signals; weights tuned from Mirai/Gafgyt captures; full signal list auditable per session
  - **canary tokens** — bait files injected into the fake filesystem; any read fires a CRITICAL alert immediately
  - **tripwire** — regex rules that bump bot score and raise severity on hostile commands
  - **session replay** — per-session append-only JSONL files with monotonic timestamps
  - **polaroid** — auto-posts one-line attacker summaries to notification channels for high-value sessions
  - **sticky** — cross-restart IP tracking persisted to `sticky.json`
  - **taunt engine** — configurable reveal intensity: `off`, `subtle`, or `full`
  - **sink** — bounded worker pool bridging Labyrinth events into Meli's standard ingest pipeline (Cowrie-format events)
  - All Labyrinth sessions appear in the Live Feed, Commands view, Attackers table, and dashboard amphora automatically
- `meli-labyrinth-digest.service` and `meli-labyrinth-digest.timer` systemd units (installed by `install.sh`)
- RSA host key generated and persisted to `~/.local/share/meli/labyrinth/ssh_host_rsa_key` on first SSH listener start

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
- 6 notification channels: Desktop, Discord, Slack, Telegram, SMTP Email, HTTP Webhook
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
- 14 tables: events, event_sessions, attackers, credentials, commands, payloads, honeypots, alert_rules, alerts, api_keys, enrichment_cache, reports, audit_log, user_settings
- Online backup via SQLite backup API
- VACUUM support

**GTK4 Views (14)**
1. Dashboard — stat cards, severity breakdown, top attackers, recent events, honey amphora
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
- bcrypt for master password verification
- Database and config files: chmod 600 / 700

**Packaging**
- `install.sh` — Arch/Ubuntu/Fedora support, 9-phase install
- `uninstall.sh` — preserves user data
- `PKGBUILD` — Arch Linux package
- `meli.desktop` + SVG icon
- `meli-ingest.service` — systemd user service

---

## [Roadmap]

Features planned but not yet implemented:

- Log file watcher (inotify-based, no MQTT required)
- Network PCAP analysis mode
- Additional parsers: T-Pot, HoneyTrap, OpenCanary
- CIDR and geofence block lists in the UI
- YubiKey hardware 2FA
- PostgreSQL backend option
- Report scheduling UI and email delivery on scheduled reports
- STIX 2.1 / TAXII 2.1 export
- Correlation rules (link events across honeypots)


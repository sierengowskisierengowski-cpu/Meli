# Meli Architecture

**v2.2.2**

## Overview

Meli is split into two independent processes:

1. **`meli-ingest` daemon** — runs as a systemd user service; receives and processes events 24/7
2. **`meli` GUI** — GTK4 desktop application; reads the database and subscribes to the processed MQTT feed

The two processes communicate only through:
- The **SQLite database** (ingest writes, GUI reads)
- **MQTT** (ingest publishes processed events, GUI subscribes for the live feed)

This means the GUI is completely optional — your honeypot data is captured, classified, enriched, and alerted even when you close the window.

## Component Map

```
┌──────────────────────────────────────────────────────────────────┐
│  External Honeypots (Cowrie / Heralding / Dionaea / …)           │
│  → JSON events via MQTT (meli/events/ingest)                     │
│  → or HTTP POST (:17654/api/v1/events/ingest)                    │
└──────────────────────────┬───────────────────────────────────────┘
                          │
┌──────────────────────────▼───────────────────────────────────────┐
│  Labyrinth Tarpit  (meli/labyrinth/)                              │
│  SSH listener (paramiko / thread pool)                            │
│  Telnet listener (asyncio)                                        │
│  → emits Cowrie-format events → same ingest pipeline below        │
└──────────────────────────┬───────────────────────────────────────┘
                          │
┌──────────────────────────▼───────────────────────────────────────┐
│                    INGEST DAEMON                                   │
│                                                                    │
│  daemon.py                                                         │
│    ├── MqttHandler  (paho-mqtt consumer)                          │
│    └── _IngestHTTPHandler  (stdlib HTTPServer)                    │
│                                                                    │
│  processor.py  (event pipeline)                                   │
│    ├── Parser selection  → ingest/parsers/                        │
│    ├── Classification    → classification/                        │
│    ├── Geolocation       → enrichment/geo                        │
│    ├── DB store          → database/                              │
│    ├── Async enrichment  → enrichment/ (thread)                  │
│    ├── Alert evaluation  → alerts/engine                          │
│    └── Publish processed → MQTT (meli/events/processed)          │
└──────────────────────────┬───────────────────────────────────────┘
                          │              │
                 SQLite DB │              │ MQTT
                          │              │
┌──────────────────────────▼──────────────▼───────────────────────┐
│                       GTK4 GUI                                    │
│                                                                   │
│  app.py  (Adw.Application)                                        │
│    ├── SetupWizard  (first run)                                   │
│    ├── MeliMainWindow                                             │
│    │     ├── LockScreen                                           │
│    │     ├── Sidebar navigation                                   │
│    │     └── Stack of 16 views                                   │
│    ├── CSS theming + global shortcuts                             │
│    └── [opt] AtriumScene  (lazily imported on --kiosk / F12)     │
└───────────────────────────────────────────────────────────────────┘
```

## Data Flow: Incoming Event

```
1. Honeypot (or Labyrinth tarpit) publishes JSON to MQTT topic `meli/events/ingest`
           OR sends HTTP POST to :17654/api/v1/events/ingest

2. parser   → Normalise to internal format
              { source_ip, timestamp, honeypot_service, action_type,
                username, password, command, payload_hash, ... }

3. classify → Apply YAML rules (default_rules.yaml + DB custom rules)
              Returns (severity: CRITICAL|HIGH|MEDIUM|LOW|INFO,
                       matched_rule_names: [str])

4. geolocate → MaxMind GeoLite2 (offline, from mmdb files)
               Returns { country_code, city, asn, organization, ... }

5. store    → INSERT INTO events + UPSERT attackers table
              (within a single SQLAlchemy session, committed atomically)

6. enrich   → Background thread: query AbuseIPDB, GreyNoise, VT, Shodan, IPInfo
              Results cached in enrichment_cache table (TTL configurable)

7. alert    → AlertEngine evaluates each enabled AlertRule
              Cooldowns respected. Fires notifications via configured channels.

8. publish  → paho-mqtt publish to `meli/events/processed`
              GUI live feed picks this up immediately.
```

## Database Schema (14 tables)

| Table | Purpose |
|-------|---------|
| `events` | Every honeypot event (core table) |
| `event_sessions` | Groups of related events (same session ID) |
| `attackers` | Per-IP aggregate stats + enrichment results |
| `credentials` | Unique username:password pairs + attempt count |
| `commands` | Unique post-auth commands + execution count |
| `payloads` | Captured malware files with VT results |
| `honeypots` | Configured honeypot sources with ingest tokens |
| `alert_rules` | User-defined alert rules (conditions JSON) |
| `alerts` | Alert fire history with acknowledge state |
| `api_keys` | Encrypted API keys for enrichment services |
| `enrichment_cache` | TTL-based cache for enrichment results |
| `reports` | Generated report metadata and paths |
| `audit_log` | Security-relevant actions (login, config changes) |
| `user_settings` | Arbitrary key-value settings store |

## Classification Engine

Rules are defined in `classification/default_rules.yaml` and optionally in the database (user-created via the alert rules editor).

Each rule has:
- `name`, `severity` (CRITICAL/HIGH/MEDIUM/LOW/INFO), `priority` (lower fires first)
- `conditions[]`: field, operator, value

Operators: `eq`, `in`, `regex`, `exists`, `gte`, `lte`

The engine evaluates ALL rules in priority order and returns the **highest severity** that matched.

Example rule:
```yaml
- name: "Crypto miner indicators"
  severity: CRITICAL
  priority: 14
  conditions:
    - field: command
      operator: regex
      value: "(xmrig|minerd|stratum\\+tcp|pool\\.minexmr)"
```

## Enrichment Cache

All enrichment results are cached in SQLite with a configurable TTL (default 24h).
Cache key format: `{service}:{ip}` (e.g. `abuseipdb:1.2.3.4`).

The full composite result is also cached under `full:{ip}` to avoid redundant parallel calls on page refreshes.

## Labyrinth Tarpit Architecture

The Labyrinth daemon (`LabyrinthDaemon`) manages two independent listeners:

- **SSH** — paramiko on a bounded thread pool (`SSHListener`). One OS thread per connection, capped by a semaphore. All accepted passwords are logged. Sessions run the same command dispatch loop as Telnet.
- **Telnet** — asyncio. One coroutine per connection, all sharing a single event loop in a dedicated background thread.

Both share:
- `FakeFS` — per-session fake filesystem, procedurally seeded so each session sees a slightly different tree
- `commands.py` — 74 fake shell command handlers (duck-typed session interface)
- `taunts.py` — configurable reveal (off / subtle / full)
- `sink.py` — bounded worker pool that converts session events to Cowrie-format events and submits them to Meli's standard `process_event` pipeline

Key Labyrinth subsystems:

| Module | Purpose |
|--------|---------|
| `botdetect.py` | Weighted bot-vs-human score (0–100) per session |
| `canary.py` | Bait files; fires CRITICAL alert on read |
| `tripwire.py` | Regex rules that bump score + severity on hostile commands |
| `replay.py` | Per-session JSONL recorder (append-only, per-session 2 MiB cap, 200 MiB global cap) |
| `replay_export.py` | Asciinema-format export |
| `polaroid.py` | Auto-posts one-line session summary to notification channels |
| `cohort.py` | Command-sequence fingerprint clustering |
| `sticky.py` | Cross-restart IP roster |
| `blocklist.py` | Firewall-rule export (fail2ban / iptables / nftables / ufw / CIDR) |
| `digest.py` | Daily 24h Markdown + PDF summary |

## GTK4 / libadwaita UI

- `MeliApplication` (Adw.Application) — registers CSS, sets up actions
- `MeliMainWindow` (Adw.ApplicationWindow) — sidebar + stack navigation
- Views are loaded lazily via `importlib.import_module()` on first navigation
- All DB queries run in background threads, results posted back via `GLib.idle_add()`
- The live feed subscribes directly to MQTT in a daemon thread; events are posted to the list via `GLib.idle_add()`
- Atrium (`atrium.py`) is lazily imported only when the kiosk mode is invoked; it adds zero overhead to normal operation

## Keyboard Shortcuts

| Shortcut | Action |
|---------|--------|
| Ctrl+L | Lock session |
| Ctrl+Q | Quit |
| Ctrl+, | Open Settings |
| Ctrl+R | Refresh current view |
| F12 | Open / close Atrium kiosk |
| 1–9 | Switch to view by number |

## Security Boundaries

- The master password is **never stored in plaintext**. It is bcrypt-hashed for verification and used to derive the Fernet encryption key via Argon2id (64MB memory, 3 iterations).
- API keys are encrypted at rest using Fernet (AES-128-CBC).
- The SQLite database and config file are created with `chmod 600`.
- The config directory is `chmod 700`.
- Ingest tokens for honeypots are stored in the database (not in config) and are only readable after successful authentication.


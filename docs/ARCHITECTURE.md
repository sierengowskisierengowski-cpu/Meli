# Meli Architecture

## Overview

Meli is split into two independent processes:

1. **`meli-ingest` daemon** — runs as a systemd user service, receives events 24/7
2. **`meli` GUI** — GTK4 desktop application, reads the database and shows the live MQTT feed

The two processes communicate only through:
- The **SQLite database** (ingest writes, GUI reads)
- **MQTT** (ingest publishes processed events, GUI subscribes for the live feed)

This means the GUI is completely optional — your honeypot data is captured and classified even when you close the window.

## Component Map

```
External
  Honeypots
     │
     │ JSON events via MQTT (meli/events/ingest)
     │ or HTTP POST (:17654/api/v1/events/ingest)
     ▼
┌─────────────────────────────────────────────────┐
│             INGEST DAEMON                        │
│                                                  │
│  daemon.py                                       │
│    ├── MqttHandler  (paho-mqtt consumer)         │
│    └── _IngestHTTPHandler  (stdlib HTTPServer)   │
│                                                  │
│  processor.py  (event pipeline)                  │
│    ├── Parser selection  → parsers/              │
│    ├── Classification    → classification/       │
│    ├── Geolocation       → enrichment/geo        │
│    ├── DB store          → database/             │
│    ├── Async enrichment  → enrichment/ (thread)  │
│    ├── Alert evaluation  → alerts/engine         │
│    └── Publish processed → MQTT (meli/events/processed)
└─────────────────────────────────────────────────┘
                     │              │
            SQLite DB │              │ MQTT
                     │              │
┌─────────────────────────────────────────────────┐
│              GTK4 GUI                            │
│                                                  │
│  app.py  (Adw.Application)                       │
│    ├── SetupWizard  (first run)                  │
│    ├── MeliMainWindow                            │
│    │     ├── LockScreen                          │
│    │     ├── Sidebar navigation                  │
│    │     └── Stack of 14 views                   │
│    └── CSS theming + global shortcuts            │
└─────────────────────────────────────────────────┘
```

## Data Flow: Incoming Event

```
1. Honeypot publishes JSON to MQTT topic `meli/events/ingest`
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

## Database Schema (12 tables)

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

## GTK4 / libadwaita UI

- `MeliApplication` (Adw.Application) — registers CSS, sets up actions
- `MeliMainWindow` (Adw.ApplicationWindow) — sidebar + stack navigation
- Views are loaded lazily via `importlib.import_module()` on first navigation
- All DB queries run in background threads, results posted back via `GLib.idle_add()`
- The live feed subscribes directly to MQTT in a daemon thread; events are posted to the list via `GLib.idle_add()`

## Keyboard Shortcuts

| Shortcut | Action |
|---------|--------|
| Ctrl+L | Lock session |
| Ctrl+Q | Quit |
| Ctrl+, | Open Settings |
| Ctrl+R | Refresh current view |
| 1–9 | Switch to view by number |

## Security Boundaries

- The master password is **never stored in plaintext**. It is bcrypt-hashed for verification.
- API keys are encrypted at rest using Fernet (AES-128-CBC) with a key derived from the master password via Argon2id (64MB memory, 3 iterations).
- The SQLite database and config file are created with `chmod 600`.
- The config directory is `chmod 700`.
- Ingest tokens for honeypots are stored in the database (not in config) and are only readable after successful authentication.

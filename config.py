"""
Meli configuration management.
Config lives at ~/.config/meli/config.yaml
"""
from __future__ import annotations

import os
import yaml
import structlog
from pathlib import Path
from typing import Any

log = structlog.get_logger()

_CONFIG_DIR = Path(os.environ.get("MELI_CONFIG_DIR", Path.home() / ".config" / "meli"))
_DATA_DIR = Path(os.environ.get("MELI_DATA_DIR", Path.home() / ".local" / "share" / "meli"))
_CONFIG_FILE = _CONFIG_DIR / "config.yaml"

DEFAULTS: dict[str, Any] = {
    "general": {
        "language": "en",
        "datetime_format": "%Y-%m-%d %H:%M:%S",
        "default_view": "dashboard",
        "auto_refresh_seconds": 30,
        "confirm_destructive": True,
        "check_updates": "manual",
        "telemetry": False,
        "font_size_delta": 0,
    },
    "auth": {
        "auto_lock_minutes": 10,
        "failed_attempts_limit": 9,
        "session_timeout_hours": 24,
        "totp_enabled": False,
        "yubikey_enabled": False,
    },
    "database": {
        "path": str(_DATA_DIR / "meli.db"),
        "backend": "sqlite",
        "retention_days": 365,
        "auto_backup": True,
        "backup_frequency": "weekly",
        "backup_path": str(_DATA_DIR / "backups"),
    },
    "storage": {
        "payloads_path": str(_DATA_DIR / "payloads"),
        "max_payload_gb": 10,
        "payload_retention_days": 90,
    },
    "mqtt": {
        "host": "127.0.0.1",
        "port": 1883,
        "qos": 1,
        "topic_ingest": "meli/events/ingest",
        "topic_processed": "meli/events/processed",
        "topic_alerts": "meli/alerts/triggered",
        "topic_health": "meli/system/health",
    },
    "http_ingest": {
        "enabled": True,
        "host": "127.0.0.1",
        "port": 17654,
        "rate_limit_per_minute": 1000,
    },
    "enrichment": {
        "parallel_workers": 4,
        "cache_ttl_hours": 24,
        "auto_enrich": True,
        "services": {
            "abuseipdb": {"enabled": False, "api_key": None, "daily_limit": 1000},
            "greynoise": {"enabled": False, "api_key": None, "daily_limit": 1000},
            "virustotal": {"enabled": False, "api_key": None, "daily_limit": 500},
            "shodan": {"enabled": False, "api_key": None, "daily_limit": 100},
            "ipinfo": {"enabled": False, "api_key": None, "daily_limit": 50000},
        },
        "geoip_city_db": str(_DATA_DIR / "geoip" / "GeoLite2-City.mmdb"),
        "geoip_asn_db": str(_DATA_DIR / "geoip" / "GeoLite2-ASN.mmdb"),
        "maxmind_license_key": None,
    },
    "alerts": {
        "desktop_notifications": True,
        "notification_position": "top-right",
        "sound_enabled": True,
        "sound_volume": 0.7,
        "per_severity_sounds": {
            "INFO": None,
            "LOW": "alert-low.ogg",
            "MEDIUM": "alert-medium.ogg",
            "HIGH": "alert-high.ogg",
            "CRITICAL": "alert-critical.ogg",
        },
        "quiet_hours_enabled": False,
        "quiet_hours_start": "23:00",
        "quiet_hours_end": "07:00",
        "discord_webhook": None,
        "slack_webhook": None,
        "telegram_bot_token": None,
        "telegram_chat_id": None,
        "email_smtp_host": None,
        "email_smtp_port": 587,
        "email_smtp_tls": True,
        "email_smtp_user": None,
        "email_smtp_password": None,
        "email_from": None,
        "email_to": None,
    },
    "reports": {
        "output_path": str(_DATA_DIR / "reports"),
        "scheduled_daily": False,
        "scheduled_weekly": True,
        "scheduled_monthly": True,
        "email_on_generate": False,
    },
    "performance": {
        "max_events_in_memory": 10000,
        "background_worker_threads": 4,
        "enrichment_parallelism": 4,
    },
    "logging": {
        "level": "INFO",
        "path": str(_DATA_DIR / "logs"),
        "max_size_mb": 100,
        "backup_count": 5,
    },
    "ui": {
        "theme": "dark",
        "live_feed_max_events": 500,
        "window_width": 1440,
        "window_height": 900,
        "window_maximized": False,
        "sidebar_width": 220,
    },
    "splash": {
        "enabled": True,
        "sound_enabled": True,
    },
    "atrium": {
        # Full-screen kiosk display for wall-mounted monitors.
        # Launch via the sidebar button, `Ctrl+F12`, or `meli --kiosk`.
        "audio_enabled": True,
        "audio_volume": 0.7,
        # If True, --kiosk launches *without* showing the lock screen
        # first (for unattended wall-display boxes where the master
        # password lives in a sealed envelope, not at the keyboard).
        "bypass_lock_in_kiosk_mode": False,
    },
    "labyrinth": {
        # Opt-in: starting a tarpit on a real interface should always
        # be a deliberate choice, never a side-effect of installing.
        "enabled": False,
        "bind_host": "0.0.0.0",
        "bind_port": 2323,
        "max_sessions": 200,
        # Taunt personality: "off" / "subtle" / "full".
        # full = HA HA gotcha banners on login + tripwires + exit (default).
        # subtle = only on disconnect + destructive-command tripwires.
        # off = silent tarpit, looks like a real (slow) box.
        "taunt_intensity": "full",
        # SSH listener (paramiko). Independent of the telnet bind — you
        # can run either, both, or neither. Host key is auto-generated
        # at ~/.local/share/meli/labyrinth/host_rsa_key on first start.
        "ssh_enabled": False,
        "ssh_bind_port": 2222,
    },
}


class Config:
    """Application configuration with YAML persistence."""

    def __init__(self) -> None:
        self._data: dict[str, Any] = {}
        self._ensure_dirs()
        self.load()

    def _ensure_dirs(self) -> None:
        _CONFIG_DIR.mkdir(parents=True, exist_ok=True)
        _CONFIG_DIR.chmod(0o700)
        _DATA_DIR.mkdir(parents=True, exist_ok=True)
        _DATA_DIR.chmod(0o700)
        for sub in ["geoip", "cache/enrichment", "reports/daily", "reports/weekly",
                    "reports/monthly", "exports", "logs", "payloads", "backups"]:
            (_DATA_DIR / sub).mkdir(parents=True, exist_ok=True)

    def load(self) -> None:
        if _CONFIG_FILE.exists():
            try:
                with open(_CONFIG_FILE) as f:
                    loaded = yaml.safe_load(f) or {}
                self._data = self._deep_merge(DEFAULTS, loaded)
                return
            except Exception as e:
                log.error("Failed to load config, using defaults", error=str(e))
        self._data = dict(DEFAULTS)
        self.save()

    def save(self) -> None:
        try:
            with open(_CONFIG_FILE, "w") as f:
                yaml.safe_dump(self._data, f, default_flow_style=False, indent=2)
            _CONFIG_FILE.chmod(0o600)
        except Exception as e:
            log.error("Failed to save config", error=str(e))

    def get(self, *path: str, default: Any = None) -> Any:
        node: Any = self._data
        for key in path:
            if not isinstance(node, dict) or key not in node:
                return default
            node = node[key]
        return node

    def set(self, *path_and_value: Any) -> None:
        *path, value = path_and_value
        node = self._data
        for key in path[:-1]:
            node = node.setdefault(key, {})
        node[path[-1]] = value
        self.save()

    def _deep_merge(self, base: dict, override: dict) -> dict:
        result = dict(base)
        for key, val in override.items():
            if key in result and isinstance(result[key], dict) and isinstance(val, dict):
                result[key] = self._deep_merge(result[key], val)
            else:
                result[key] = val
        return result

    @property
    def config_dir(self) -> Path:
        return _CONFIG_DIR

    @property
    def data_dir(self) -> Path:
        return _DATA_DIR

    @property
    def db_path(self) -> str:
        return self.get("database", "path", default=str(_DATA_DIR / "meli.db"))


# Singleton
_config: Config | None = None


def get_config() -> Config:
    global _config
    if _config is None:
        _config = Config()
    return _config

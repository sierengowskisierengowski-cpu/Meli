"""Mailoney SMTP honeypot parser."""
from __future__ import annotations

from datetime import datetime, timezone
from typing import Any


class MaloneyParser:
    def parse(self, raw: dict[str, Any]) -> dict[str, Any] | None:
        src_ip = raw.get("src_ip") or raw.get("remote_ip", "")
        if not src_ip:
            return None

        return {
            "honeypot_service": "mailoney",
            "timestamp": self._parse_timestamp(raw.get("timestamp") or raw.get("time")),
            "source_ip": src_ip,
            "source_port": self._coerce_int(raw.get("src_port")),
            "destination_port": 25,
            "protocol": "tcp",
            "transport": "smtp",
            "action_type": "smtp_probe",
            "username": raw.get("mail_from", ""),
            "command": raw.get("data", "")[:500],
        }

    @staticmethod
    def _coerce_int(val: Any) -> int | None:
        try:
            return int(val)
        except (TypeError, ValueError):
            return None

    @staticmethod
    def _parse_timestamp(ts: Any) -> datetime:
        if isinstance(ts, str):
            for fmt in ("%Y-%m-%dT%H:%M:%S.%fZ", "%Y-%m-%dT%H:%M:%SZ",
                        "%Y-%m-%d %H:%M:%S"):
                try:
                    return datetime.strptime(ts, fmt).replace(tzinfo=timezone.utc)
                except ValueError:
                    continue
        return datetime.now(timezone.utc)

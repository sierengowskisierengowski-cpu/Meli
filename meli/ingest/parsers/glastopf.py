"""Glastopf web application honeypot parser."""
from __future__ import annotations

from datetime import datetime, timezone
from typing import Any


class GlastopfParser:
    def parse(self, raw: dict[str, Any]) -> dict[str, Any] | None:
        src_ip = raw.get("source") or raw.get("src_ip", "")
        if not src_ip:
            return None

        return {
            "honeypot_service": "glastopf",
            "timestamp": self._parse_timestamp(raw.get("time") or raw.get("timestamp")),
            "source_ip": src_ip,
            "source_port": None,
            "destination_port": 80,
            "protocol": "tcp",
            "transport": "http",
            "action_type": "web_request",
            "command": raw.get("request_raw", "")[:500],
        }

    @staticmethod
    def _parse_timestamp(ts: Any) -> datetime:
        if isinstance(ts, str):
            for fmt in ("%Y-%m-%dT%H:%M:%S", "%Y-%m-%d %H:%M:%S"):
                try:
                    return datetime.strptime(ts, fmt).replace(tzinfo=timezone.utc)
                except ValueError:
                    continue
        return datetime.now(timezone.utc)

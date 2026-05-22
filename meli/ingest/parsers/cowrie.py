"""
Cowrie SSH/Telnet honeypot parser.
Handles Cowrie JSON log format (cowrie.json / cowrie.log).
"""
from __future__ import annotations

import json
from datetime import datetime, timezone
from typing import Any


class CowrieParser:
    """Parse Cowrie JSON log events into Meli's internal format."""

    # Cowrie event IDs that map to meaningful actions
    _EVENT_MAP = {
        "cowrie.login.failed": ("login_attempt", "LOW"),
        "cowrie.login.success": ("successful_auth", "HIGH"),
        "cowrie.command.input": ("command", "MEDIUM"),
        "cowrie.command.failed": ("command", "LOW"),
        "cowrie.session.connect": ("connection", "INFO"),
        "cowrie.session.closed": ("session_close", "INFO"),
        "cowrie.session.file_download": ("file_download", "HIGH"),
        "cowrie.session.file_upload": ("file_upload", "HIGH"),
        "cowrie.direct-tcpip.request": ("port_forward", "MEDIUM"),
        "cowrie.direct-tcpip.data": ("port_forward_data", "MEDIUM"),
    }

    def parse(self, raw: dict[str, Any]) -> dict[str, Any] | None:
        event_id = raw.get("eventid", "")
        if not event_id:
            return self._parse_generic(raw)

        action_type, default_severity = self._EVENT_MAP.get(
            event_id, ("unknown", "INFO")
        )

        ts = self._parse_timestamp(raw.get("timestamp"))
        src_ip = raw.get("src_ip") or raw.get("peerIP", "")
        src_port = raw.get("src_port") or raw.get("peerPort")

        result: dict[str, Any] = {
            "honeypot_service": "cowrie",
            "timestamp": ts,
            "source_ip": src_ip,
            "source_port": int(src_port) if src_port else None,
            "destination_port": int(raw.get("dst_port", 22)),
            "protocol": "tcp",
            "transport": raw.get("protocol", "ssh"),
            "session_id": raw.get("session"),
            "action_type": action_type,
            "raw_event_id": event_id,
        }

        # Login attempt
        if event_id in ("cowrie.login.failed", "cowrie.login.success"):
            result["username"] = raw.get("username", "")
            result["password"] = raw.get("password", "")

        # Command execution
        if event_id in ("cowrie.command.input", "cowrie.command.failed"):
            result["command"] = raw.get("input", "")

        # File download
        if event_id == "cowrie.session.file_download":
            result["payload_url"] = raw.get("url", "")
            result["payload_hash"] = raw.get("shasum", "")
            result["payload_filename"] = raw.get("filename", "")

        return result

    def _parse_generic(self, raw: dict) -> dict[str, Any] | None:
        """Fallback: treat as generic if no eventid."""
        src_ip = raw.get("src_ip") or raw.get("peerIP", "")
        if not src_ip:
            return None
        return {
            "honeypot_service": "cowrie",
            "timestamp": self._parse_timestamp(raw.get("timestamp")),
            "source_ip": src_ip,
            "action_type": "unknown",
        }

    @staticmethod
    def _parse_timestamp(ts: Any) -> datetime:
        if isinstance(ts, datetime):
            return ts
        if isinstance(ts, str):
            for fmt in ("%Y-%m-%dT%H:%M:%S.%fZ", "%Y-%m-%dT%H:%M:%SZ", "%Y-%m-%dT%H:%M:%S"):
                try:
                    return datetime.strptime(ts, fmt).replace(tzinfo=timezone.utc)
                except ValueError:
                    continue
        return datetime.now(timezone.utc)

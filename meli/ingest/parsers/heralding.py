"""
Heralding credential honeypot parser.
Heralding captures credentials across SSH, FTP, HTTP, POP3, IMAP, SMTP, VNC, RDP.
Output: CSV or JSON log format.
"""
from __future__ import annotations

from datetime import datetime, timezone
from typing import Any


class HeraldingParser:
    """Parse Heralding log events."""

    # Port → protocol/transport mapping
    _PORT_PROTOCOLS = {
        21: "ftp", 22: "ssh", 23: "telnet", 25: "smtp",
        80: "http", 110: "pop3", 143: "imap", 389: "ldap",
        443: "https", 3389: "rdp", 5900: "vnc",
    }

    def parse(self, raw: dict[str, Any]) -> dict[str, Any] | None:
        src_ip = raw.get("source_ip") or raw.get("src_ip", "")
        if not src_ip:
            return None

        dest_port = self._coerce_int(raw.get("destination_port") or raw.get("dest_port"))
        protocol = self._PORT_PROTOCOLS.get(dest_port or 0, raw.get("protocol", "unknown"))

        username = raw.get("username") or raw.get("auth_username", "")
        password = raw.get("password") or raw.get("auth_password", "")
        auth_success = raw.get("auth_success", False)

        return {
            "honeypot_service": "heralding",
            "timestamp": self._parse_timestamp(raw.get("timestamp") or raw.get("time")),
            "source_ip": src_ip,
            "source_port": self._coerce_int(raw.get("source_port") or raw.get("src_port")),
            "destination_port": dest_port,
            "protocol": "tcp",
            "transport": protocol,
            "action_type": "successful_auth" if auth_success else "login_attempt",
            "username": username,
            "password": password,
            "session_id": raw.get("session_id"),
        }

    @staticmethod
    def _coerce_int(val: Any) -> int | None:
        try:
            return int(val)
        except (TypeError, ValueError):
            return None

    @staticmethod
    def _parse_timestamp(ts: Any) -> datetime:
        if isinstance(ts, datetime):
            return ts
        if isinstance(ts, (int, float)):
            return datetime.fromtimestamp(ts, tz=timezone.utc)
        if isinstance(ts, str):
            for fmt in ("%Y-%m-%dT%H:%M:%S.%fZ", "%Y-%m-%dT%H:%M:%SZ",
                        "%Y-%m-%d %H:%M:%S.%f", "%Y-%m-%d %H:%M:%S"):
                try:
                    return datetime.strptime(ts, fmt).replace(tzinfo=timezone.utc)
                except ValueError:
                    continue
        return datetime.now(timezone.utc)

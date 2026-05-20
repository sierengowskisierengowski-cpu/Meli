"""
Dionaea malware honeypot parser.
Dionaea captures payloads over SMB, FTP, HTTP, MySQL, MSSQL, SIP, etc.
Reads from Dionaea's SQLite log or JSON output.
"""
from __future__ import annotations

from datetime import datetime, timezone
from typing import Any


class DionaeaParser:
    """Parse Dionaea connection/capture events."""

    _PROTO_MAP = {
        "dionaea.services.smb": ("smb", 445),
        "dionaea.services.ftp": ("ftp", 21),
        "dionaea.services.http": ("http", 80),
        "dionaea.services.mysql": ("mysql", 3306),
        "dionaea.services.mssql": ("mssql", 1433),
        "dionaea.services.sip": ("sip", 5060),
        "dionaea.services.tftp": ("tftp", 69),
        "dionaea.services.upnp": ("upnp", 1900),
    }

    def parse(self, raw: dict[str, Any]) -> dict[str, Any] | None:
        src_ip = raw.get("src_ip") or raw.get("remote_host", "")
        if not src_ip:
            return None

        proto_str = raw.get("proto") or raw.get("protocol") or raw.get("service", "")
        transport, default_port = self._PROTO_MAP.get(proto_str, ("tcp", None))

        payload_hash = raw.get("sha512") or raw.get("sha256") or raw.get("md5", "")
        has_payload = bool(payload_hash or raw.get("filename"))

        return {
            "honeypot_service": "dionaea",
            "timestamp": self._parse_timestamp(raw.get("timestamp") or raw.get("starttime")),
            "source_ip": src_ip,
            "source_port": self._coerce_int(raw.get("src_port") or raw.get("remote_port")),
            "destination_port": self._coerce_int(
                raw.get("dst_port") or raw.get("local_port") or default_port
            ),
            "protocol": "tcp",
            "transport": transport,
            "action_type": "file_upload" if has_payload else "connection",
            "payload_hash": payload_hash or None,
            "session_id": raw.get("connection"),
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
                        "%Y-%m-%d %H:%M:%S"):
                try:
                    return datetime.strptime(ts, fmt).replace(tzinfo=timezone.utc)
                except ValueError:
                    continue
        return datetime.now(timezone.utc)

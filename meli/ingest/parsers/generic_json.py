"""
Generic JSON honeypot parser.
Normalises any Meli-format or near-Meli-format JSON event.
This is the default parser used internally by the event processor.
"""
from __future__ import annotations

from datetime import datetime, timezone
from typing import Any


_TS_FORMATS = (
    "%Y-%m-%dT%H:%M:%S.%fZ",
    "%Y-%m-%dT%H:%M:%SZ",
    "%Y-%m-%dT%H:%M:%S",
    "%Y-%m-%d %H:%M:%S.%f",
    "%Y-%m-%d %H:%M:%S",
)


def _parse_ts(ts: Any) -> datetime:
    if isinstance(ts, datetime):
        return ts if ts.tzinfo else ts.replace(tzinfo=timezone.utc)
    if isinstance(ts, (int, float)):
        return datetime.fromtimestamp(ts, tz=timezone.utc)
    if isinstance(ts, str):
        for fmt in _TS_FORMATS:
            try:
                return datetime.strptime(ts, fmt).replace(tzinfo=timezone.utc)
            except ValueError:
                continue
    return datetime.now(timezone.utc)


class GenericJsonParser:
    """
    Accepts events in the Meli canonical format or tries to extract
    common fields from arbitrary honeypot JSON structures.
    """

    def parse(self, raw: dict[str, Any]) -> dict[str, Any] | None:
        # Try canonical Meli format first
        if "network" in raw or "honeypot" in raw:
            return self._parse_canonical(raw)
        return self._parse_heuristic(raw)

    def _parse_canonical(self, raw: dict) -> dict[str, Any] | None:
        network = raw.get("network", {})
        honeypot = raw.get("honeypot", {})
        action = raw.get("action", {})
        session = raw.get("session", {})

        src_ip = network.get("source_ip", "")
        if not src_ip:
            return None

        return {
            "honeypot_service": honeypot.get("type", "unknown"),
            "timestamp": _parse_ts(raw.get("timestamp")),
            "source_ip": src_ip,
            "source_port": network.get("source_port"),
            "destination_port": network.get("destination_port"),
            "protocol": network.get("protocol", "tcp"),
            "transport": network.get("transport"),
            "session_id": session.get("session_id") or raw.get("event_id"),
            "action_type": action.get("type", "unknown"),
            "username": action.get("details", {}).get("username"),
            "password": action.get("details", {}).get("password"),
            "command": action.get("details", {}).get("command"),
            "payload_hash": action.get("details", {}).get("sha256"),
        }

    def _parse_heuristic(self, raw: dict) -> dict[str, Any] | None:
        """Best-effort extraction from unknown JSON structures."""
        src_ip = (raw.get("source_ip") or raw.get("src_ip") or raw.get("client_ip")
                  or raw.get("ip") or raw.get("remote_addr", ""))
        if not src_ip:
            return None

        return {
            "honeypot_service": raw.get("honeypot_type") or raw.get("service") or "unknown",
            "timestamp": _parse_ts(raw.get("timestamp") or raw.get("time") or raw.get("@timestamp")),
            "source_ip": src_ip,
            "source_port": raw.get("source_port") or raw.get("src_port"),
            "destination_port": raw.get("destination_port") or raw.get("dst_port") or raw.get("port"),
            "protocol": raw.get("protocol", "tcp"),
            "transport": raw.get("transport") or raw.get("service_proto"),
            "action_type": raw.get("action") or raw.get("event_type") or "unknown",
            "username": raw.get("username") or raw.get("user"),
            "password": raw.get("password") or raw.get("pass"),
            "command": raw.get("command") or raw.get("input") or raw.get("cmd"),
            "payload_hash": raw.get("sha256") or raw.get("sha512") or raw.get("md5"),
            "session_id": raw.get("session_id") or raw.get("session"),
        }

"""
HTTP honeypot parser — handles generic HTTP honeypot JSON output.
Compatible with: Snare/Tanner, ADBHoney HTTP mode, custom nginx log honeypots.
"""
from __future__ import annotations

from datetime import datetime, timezone
from typing import Any
import json


class HttpHoneypotParser:
    def parse(self, raw: dict[str, Any]) -> dict[str, Any] | None:
        src_ip = (raw.get("remote_addr") or raw.get("client_ip")
                  or raw.get("src_ip") or raw.get("source_ip", ""))
        if not src_ip:
            return None

        method = raw.get("method") or raw.get("request_method", "GET")
        path = raw.get("path") or raw.get("uri") or raw.get("request_uri", "/")
        user_agent = raw.get("user_agent") or raw.get("http_user_agent", "")
        post_data = raw.get("post_data") or raw.get("body", "")

        parsed_extra = json.dumps({
            "method": method,
            "path": path,
            "user_agent": user_agent,
            "post_data": post_data[:2000],  # cap payload in parsed_data
            "headers": raw.get("headers", {}),
        })

        return {
            "honeypot_service": "http",
            "timestamp": self._parse_timestamp(raw.get("timestamp") or raw.get("time")),
            "source_ip": src_ip,
            "source_port": self._coerce_int(raw.get("src_port") or raw.get("remote_port")),
            "destination_port": self._coerce_int(
                raw.get("dst_port") or raw.get("server_port", 80)
            ),
            "protocol": "tcp",
            "transport": "https" if raw.get("tls") else "http",
            "action_type": "web_request",
            "command": f"{method} {path}",
            "parsed_data_extra": parsed_extra,
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
                        "%d/%b/%Y:%H:%M:%S %z", "%Y-%m-%d %H:%M:%S"):
                try:
                    return datetime.strptime(ts, fmt).replace(
                        tzinfo=timezone.utc) if "+" not in ts else datetime.strptime(ts, fmt)
                except ValueError:
                    continue
        return datetime.now(timezone.utc)

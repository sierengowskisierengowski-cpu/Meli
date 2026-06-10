"""General-purpose helpers for Meli."""
from __future__ import annotations

import re
import socket
import ipaddress
from datetime import datetime, timezone
from typing import Any


def utcnow() -> datetime:
    return datetime.now(timezone.utc)


def format_bytes(n: int) -> str:
    for unit in ("B", "KB", "MB", "GB", "TB"):
        if n < 1024:
            return f"{n:.1f} {unit}"
        n /= 1024
    return f"{n:.1f} PB"


def format_duration(seconds: float) -> str:
    if seconds < 60:
        return f"{int(seconds)}s"
    if seconds < 3600:
        return f"{int(seconds // 60)}m {int(seconds % 60)}s"
    h = int(seconds // 3600)
    m = int((seconds % 3600) // 60)
    return f"{h}h {m}m"


def is_valid_ip(ip: str) -> bool:
    try:
        ipaddress.ip_address(ip)
        return True
    except ValueError:
        return False


# Explicit list of private/reserved networks (RFC 1918, loopback, link-local,
# ULA).  We intentionally do NOT use ipaddress.is_private here because its
# definition was expanded in Python 3.11 to include documentation/test ranges
# such as 192.0.2.0/24, 198.51.100.0/24, and 203.0.113.0/24 (RFC 5737), which
# are not routable but are not "private" in the colloquial sense used elsewhere
# in this codebase (i.e., "not a real public Internet address").
_PRIVATE_NETWORKS: list[ipaddress.IPv4Network | ipaddress.IPv6Network] = [
    # IPv4
    ipaddress.ip_network("10.0.0.0/8"),
    ipaddress.ip_network("172.16.0.0/12"),
    ipaddress.ip_network("192.168.0.0/16"),
    ipaddress.ip_network("127.0.0.0/8"),
    ipaddress.ip_network("169.254.0.0/16"),  # link-local
    ipaddress.ip_network("0.0.0.0/8"),
    # IPv6
    ipaddress.ip_network("::1/128"),          # loopback
    ipaddress.ip_network("fc00::/7"),          # ULA
    ipaddress.ip_network("fe80::/10"),         # link-local
]


def is_private_ip(ip: str) -> bool:
    """Return True if *ip* is a private/loopback/link-local address.

    Only RFC 1918, loopback, and link-local ranges are considered private.
    Documentation/test ranges (RFC 5737, RFC 3849) are treated as public so
    that behaviour is consistent across Python versions.
    """
    try:
        addr = ipaddress.ip_address(ip)
        return any(addr in net for net in _PRIVATE_NETWORKS)
    except ValueError:
        return False


def truncate(s: str, max_len: int = 80) -> str:
    return s if len(s) <= max_len else s[:max_len - 3] + "..."


def severity_color(severity: str) -> str:
    """Return CSS color name for a severity level."""
    return {
        "INFO": "#94a3b8",
        "LOW": "#60a5fa",
        "MEDIUM": "#f59e0b",
        "HIGH": "#f97316",
        "CRITICAL": "#ef4444",
    }.get(severity.upper(), "#94a3b8")


def severity_rank(severity: str) -> int:
    return {"INFO": 0, "LOW": 1, "MEDIUM": 2, "HIGH": 3, "CRITICAL": 4}.get(severity.upper(), 0)


def generate_token(length: int = 32) -> str:
    import secrets
    return secrets.token_urlsafe(length)


def country_flag_emoji(country_code: str) -> str:
    """Convert ISO-3166-1 alpha-2 code to flag emoji."""
    if not country_code or len(country_code) != 2:
        return "\U0001f3f3"
    offset = 127397
    return "".join(chr(ord(c) + offset) for c in country_code.upper())


def parse_cidr_or_ip(value: str) -> list[str]:
    """Expand a CIDR block or single IP into a list of IPs (max 256)."""
    try:
        net = ipaddress.ip_network(value, strict=False)
        hosts = list(net.hosts())
        return [str(h) for h in hosts[:256]]
    except ValueError:
        if is_valid_ip(value):
            return [value]
        return []

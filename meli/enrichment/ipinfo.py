"""IPInfo enrichment — ASN, org, hostname, VPN/proxy detection."""
from __future__ import annotations

import requests
import structlog
from meli.config import get_config
from meli.enrichment.cache import get_cached, set_cached

log = structlog.get_logger()
_BASE = "https://ipinfo.io"


def query_ipinfo(ip: str) -> dict | None:
    cache_key = f"ipinfo:{ip}"
    cached = get_cached(cache_key)
    if cached:
        return cached

    cfg = get_config()
    api_key = cfg.get("enrichment", "services", "ipinfo", "api_key")
    if not api_key:
        return None

    try:
        resp = requests.get(
            f"{_BASE}/{ip}/json",
            headers={"Authorization": f"Bearer {api_key}"},
            timeout=8,
        )
        resp.raise_for_status()
        d = resp.json()
        result = {
            "hostname": d.get("hostname"),
            "org": d.get("org"),
            "asn": d.get("org", "").split()[0] if d.get("org") else None,
            "country": d.get("country"),
            "city": d.get("city"),
            "region": d.get("region"),
            "timezone": d.get("timezone"),
            "is_vpn": d.get("privacy", {}).get("vpn", False),
            "is_proxy": d.get("privacy", {}).get("proxy", False),
            "is_tor": d.get("privacy", {}).get("tor", False),
            "is_relay": d.get("privacy", {}).get("relay", False),
        }
        ttl = cfg.get("enrichment", "cache_ttl_hours", default=24) * 3600
        set_cached(cache_key, result, ttl_seconds=ttl)
        return result
    except Exception as e:
        log.debug("IPInfo query failed", ip=ip, error=str(e))
        return None

"""Shodan enrichment — open ports, banners, vulnerabilities."""
from __future__ import annotations

import requests
import structlog
from meli.config import get_config
from meli.enrichment.cache import get_cached, set_cached

log = structlog.get_logger()
_BASE = "https://api.shodan.io"


def query_shodan(ip: str) -> dict | None:
    cache_key = f"shodan:{ip}"
    cached = get_cached(cache_key)
    if cached:
        return cached

    cfg = get_config()
    api_key = cfg.get("enrichment", "services", "shodan", "api_key")
    if not api_key:
        return None

    try:
        resp = requests.get(
            f"{_BASE}/shodan/host/{ip}",
            params={"key": api_key},
            timeout=10,
        )
        if resp.status_code == 404:
            return {"ports": [], "vulns": [], "tags": []}
        resp.raise_for_status()
        d = resp.json()
        result = {
            "ports": d.get("ports", []),
            "vulns": list(d.get("vulns", {}).keys()),
            "tags": d.get("tags", []),
            "hostnames": d.get("hostnames", []),
            "org": d.get("org"),
            "isp": d.get("isp"),
            "os": d.get("os"),
            "country_code": d.get("country_code"),
            "last_update": d.get("last_update"),
        }
        ttl = cfg.get("enrichment", "cache_ttl_hours", default=24) * 3600
        set_cached(cache_key, result, ttl_seconds=ttl)
        return result
    except Exception as e:
        log.debug("Shodan query failed", ip=ip, error=str(e))
        return None

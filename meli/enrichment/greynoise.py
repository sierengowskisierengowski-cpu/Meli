"""GreyNoise enrichment — noise/malicious/benign classification."""
from __future__ import annotations

import requests
import structlog
from meli.config import get_config
from meli.enrichment.cache import get_cached, set_cached

log = structlog.get_logger()
_BASE = "https://api.greynoise.io/v3/community"


def query_greynoise(ip: str) -> dict | None:
    cache_key = f"greynoise:{ip}"
    cached = get_cached(cache_key)
    if cached:
        return cached

    cfg = get_config()
    api_key = cfg.get("enrichment", "services", "greynoise", "api_key")
    if not api_key:
        return None

    try:
        resp = requests.get(
            f"{_BASE}/{ip}",
            headers={"key": api_key, "Accept": "application/json"},
            timeout=8,
        )
        if resp.status_code == 404:
            result = {"classification": "unknown", "noise": False, "riot": False, "tags": []}
        else:
            resp.raise_for_status()
            d = resp.json()
            result = {
                "classification": d.get("classification", "unknown"),
                "noise": d.get("noise", False),
                "riot": d.get("riot", False),
                "name": d.get("name"),
                "link": d.get("link"),
                "last_seen": d.get("last_seen"),
                "message": d.get("message"),
                "tags": [],
            }
        ttl = cfg.get("enrichment", "cache_ttl_hours", default=24) * 3600
        set_cached(cache_key, result, ttl_seconds=ttl)
        return result
    except Exception as e:
        log.debug("GreyNoise query failed", ip=ip, error=str(e))
        return None

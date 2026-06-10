"""AbuseIPDB enrichment — abuse confidence score and report history."""
from __future__ import annotations

import requests
import structlog
from meli.config import get_config
from meli.enrichment.cache import get_cached, set_cached

log = structlog.get_logger()
_BASE = "https://api.abuseipdb.com/api/v2"


def query_abuseipdb(ip: str) -> dict | None:
    cache_key = f"abuseipdb:{ip}"
    cached = get_cached(cache_key)
    if cached:
        return cached

    cfg = get_config()
    api_key = cfg.get("enrichment", "services", "abuseipdb", "api_key")
    if not api_key:
        return None

    try:
        resp = requests.get(
            f"{_BASE}/check",
            headers={"Key": api_key, "Accept": "application/json"},
            params={"ipAddress": ip, "maxAgeInDays": 90, "verbose": True},
            timeout=8,
        )
        resp.raise_for_status()
        d = resp.json().get("data", {})
        result = {
            "abuse_score": d.get("abuseConfidenceScore"),
            "total_reports": d.get("totalReports"),
            "last_reported": d.get("lastReportedAt"),
            "domain": d.get("domain"),
            "is_tor": d.get("isTor", False),
            "is_public": d.get("isPublic", True),
            "country_code": d.get("countryCode"),
            "isp": d.get("isp"),
            "usage_type": d.get("usageType"),
        }
        ttl = cfg.get("enrichment", "cache_ttl_hours", default=24) * 3600
        set_cached(cache_key, result, ttl_seconds=ttl)
        return result
    except Exception as e:
        log.debug("AbuseIPDB query failed", ip=ip, error=str(e))
        return None

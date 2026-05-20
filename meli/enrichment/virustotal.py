"""VirusTotal enrichment — IP reputation and file hash lookups."""
from __future__ import annotations

import requests
import structlog
from meli.config import get_config
from meli.enrichment.cache import get_cached, set_cached

log = structlog.get_logger()
_BASE = "https://www.virustotal.com/api/v3"


def _headers(api_key: str) -> dict:
    return {"x-apikey": api_key, "Accept": "application/json"}


def query_virustotal(ip: str) -> dict | None:
    cache_key = f"vt_ip:{ip}"
    cached = get_cached(cache_key)
    if cached:
        return cached

    cfg = get_config()
    api_key = cfg.get("enrichment", "services", "virustotal", "api_key")
    if not api_key:
        return None

    try:
        resp = requests.get(
            f"{_BASE}/ip_addresses/{ip}",
            headers=_headers(api_key),
            timeout=10,
        )
        resp.raise_for_status()
        attrs = resp.json().get("data", {}).get("attributes", {})
        stats = attrs.get("last_analysis_stats", {})
        result = {
            "malicious": stats.get("malicious", 0),
            "suspicious": stats.get("suspicious", 0),
            "harmless": stats.get("harmless", 0),
            "undetected": stats.get("undetected", 0),
            "country": attrs.get("country"),
            "as_owner": attrs.get("as_owner"),
            "reputation": attrs.get("reputation", 0),
            "tags": attrs.get("tags", []),
        }
        ttl = cfg.get("enrichment", "cache_ttl_hours", default=24) * 3600
        set_cached(cache_key, result, ttl_seconds=ttl)
        return result
    except Exception as e:
        log.debug("VirusTotal IP query failed", ip=ip, error=str(e))
        return None


def query_virustotal_hash(sha256: str) -> dict | None:
    cache_key = f"vt_hash:{sha256}"
    cached = get_cached(cache_key)
    if cached:
        return cached

    cfg = get_config()
    api_key = cfg.get("enrichment", "services", "virustotal", "api_key")
    if not api_key:
        return None

    try:
        resp = requests.get(
            f"{_BASE}/files/{sha256}",
            headers=_headers(api_key),
            timeout=10,
        )
        resp.raise_for_status()
        attrs = resp.json().get("data", {}).get("attributes", {})
        stats = attrs.get("last_analysis_stats", {})
        total = sum(stats.values()) or 1
        result = {
            "malicious": stats.get("malicious", 0),
            "suspicious": stats.get("suspicious", 0),
            "total": total,
            "score": f"{stats.get('malicious', 0)}/{total}",
            "name": attrs.get("meaningful_name"),
            "type": attrs.get("type_description"),
            "size": attrs.get("size"),
            "tags": attrs.get("tags", []),
            "first_seen": attrs.get("first_submission_date"),
        }
        set_cached(cache_key, result, ttl_seconds=86400 * 7)
        return result
    except Exception as e:
        log.debug("VirusTotal hash query failed", sha256=sha256[:16], error=str(e))
        return None

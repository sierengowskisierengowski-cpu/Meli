"""Enrichment package — parallel IP enrichment from multiple services."""
from __future__ import annotations

import json
import concurrent.futures
import structlog
from datetime import datetime, timezone

log = structlog.get_logger()


def enrich_ip(ip: str) -> dict:
    """
    Enrich an IP using all configured services in parallel.
    Results are stored in DB and returned.
    """
    from meli.config import get_config
    from meli.enrichment.cache import get_cached, set_cached
    from meli.enrichment.geolocation import geolocate_ip
    from meli.enrichment.abuseipdb import query_abuseipdb
    from meli.enrichment.greynoise import query_greynoise
    from meli.enrichment.virustotal import query_virustotal
    from meli.enrichment.shodan import query_shodan
    from meli.enrichment.ipinfo import query_ipinfo

    cfg = get_config()
    result: dict = {"ip": ip}

    # Check full cache first
    cached = get_cached(f"full:{ip}")
    if cached:
        return cached

    # Parallel enrichment
    services = {
        "geo": (geolocate_ip, ip),
    }
    enrichment_cfg = cfg.get("enrichment", "services", default={})

    if enrichment_cfg.get("abuseipdb", {}).get("enabled"):
        services["abuseipdb"] = (query_abuseipdb, ip)
    if enrichment_cfg.get("greynoise", {}).get("enabled"):
        services["greynoise"] = (query_greynoise, ip)
    if enrichment_cfg.get("virustotal", {}).get("enabled"):
        services["virustotal"] = (query_virustotal, ip)
    if enrichment_cfg.get("shodan", {}).get("enabled"):
        services["shodan"] = (query_shodan, ip)
    if enrichment_cfg.get("ipinfo", {}).get("enabled"):
        services["ipinfo"] = (query_ipinfo, ip)

    parallelism = cfg.get("performance", "enrichment_parallelism", default=4)

    with concurrent.futures.ThreadPoolExecutor(max_workers=parallelism) as ex:
        futures = {name: ex.submit(fn, arg) for name, (fn, arg) in services.items()}
        for name, future in futures.items():
            try:
                result[name] = future.result(timeout=10)
            except Exception as e:
                log.debug("Enrichment service failed", service=name, ip=ip, error=str(e))
                result[name] = None

    # Store enriched data to DB
    _store_enrichment(ip, result)

    # Cache composite result for 24h
    ttl = cfg.get("enrichment", "cache_ttl_hours", default=24) * 3600
    set_cached(f"full:{ip}", result, ttl_seconds=ttl)

    return result


def _store_enrichment(ip: str, data: dict) -> None:
    try:
        from meli.database import get_db
        from meli.database.models import Attacker
        from meli.utils.helpers import is_valid_ip

        if not is_valid_ip(ip):
            return

        geo = data.get("geo") or {}
        abuse = data.get("abuseipdb") or {}
        gn = data.get("greynoise") or {}
        vt = data.get("virustotal") or {}

        with get_db() as db:
            attacker = db.get(Attacker, ip)
            if attacker:
                attacker.country_code = geo.get("country_code") or attacker.country_code
                attacker.asn = geo.get("asn") or attacker.asn
                attacker.organization = geo.get("organization") or attacker.organization
                attacker.abuseipdb_score = abuse.get("abuse_score")
                attacker.greynoise_classification = gn.get("classification")
                attacker.greynoise_tags = json.dumps(gn.get("tags", []))
                attacker.virustotal_malicious = vt.get("malicious")
                attacker.enriched_at = datetime.now(timezone.utc)
    except Exception as e:
        log.debug("Failed to store enrichment in DB", ip=ip, error=str(e))

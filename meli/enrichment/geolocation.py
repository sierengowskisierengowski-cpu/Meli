"""Offline IP geolocation using MaxMind GeoLite2."""
from __future__ import annotations

import structlog
from typing import Any

log = structlog.get_logger()

_city_reader = None
_asn_reader = None


def _get_readers():
    global _city_reader, _asn_reader
    if _city_reader is None:
        import geoip2.database
        from meli.config import get_config
        cfg = get_config()
        city_db = cfg.get("enrichment", "geoip_city_db")
        asn_db = cfg.get("enrichment", "geoip_asn_db")
        try:
            _city_reader = geoip2.database.Reader(city_db)
        except Exception as e:
            log.warning("GeoLite2 City DB not available", path=city_db, error=str(e))
        try:
            _asn_reader = geoip2.database.Reader(asn_db)
        except Exception as e:
            log.warning("GeoLite2 ASN DB not available", path=asn_db, error=str(e))
    return _city_reader, _asn_reader


def geolocate_ip(ip: str) -> dict[str, Any]:
    """Return geolocation data for an IP address."""
    from meli.enrichment.cache import get_cached, set_cached
    cache_key = f"geo:{ip}"
    cached = get_cached(cache_key)
    if cached:
        return cached

    result: dict[str, Any] = {"ip": ip}

    try:
        city_reader, asn_reader = _get_readers()

        if city_reader:
            try:
                city = city_reader.city(ip)
                result.update({
                    "country_code": city.country.iso_code,
                    "country_name": city.country.name,
                    "city": city.city.name,
                    "latitude": float(city.location.latitude or 0),
                    "longitude": float(city.location.longitude or 0),
                    "timezone": city.location.time_zone,
                })
            except Exception:
                pass

        if asn_reader:
            try:
                asn = asn_reader.asn(ip)
                result["asn"] = f"AS{asn.autonomous_system_number}"
                result["organization"] = asn.autonomous_system_organization
            except Exception:
                pass

        set_cached(cache_key, result, ttl_seconds=604800)  # 7 days
    except Exception as e:
        log.debug("Geolocation failed", ip=ip, error=str(e))

    return result


def download_geolite2(license_key: str, output_dir: str) -> bool:
    """Download latest GeoLite2 databases from MaxMind."""
    import requests
    import tarfile
    from pathlib import Path

    base_url = "https://download.maxmind.com/app/geoip_download"
    dbs = ["GeoLite2-City", "GeoLite2-ASN"]
    out = Path(output_dir)
    out.mkdir(parents=True, exist_ok=True)

    for db_name in dbs:
        url = f"{base_url}?edition_id={db_name}&license_key={license_key}&suffix=tar.gz"
        try:
            resp = requests.get(url, timeout=60, stream=True)
            resp.raise_for_status()
            tar_path = out / f"{db_name}.tar.gz"
            with open(tar_path, "wb") as f:
                for chunk in resp.iter_content(65536):
                    f.write(chunk)
            with tarfile.open(tar_path) as tf:
                for member in tf.getmembers():
                    if member.name.endswith(".mmdb"):
                        member.name = Path(member.name).name
                        tf.extract(member, path=str(out))
            tar_path.unlink()
            log.info("GeoLite2 downloaded", db=db_name, dest=str(out))
        except Exception as e:
            log.error("GeoLite2 download failed", db=db_name, error=str(e))
            return False

    global _city_reader, _asn_reader
    _city_reader = None
    _asn_reader = None
    return True

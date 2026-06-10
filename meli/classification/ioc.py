"""IoC (Indicator of Compromise) matching against threat feeds."""
from __future__ import annotations

import re
import json
import structlog
import threading
import time
from pathlib import Path
from typing import Any

from meli.config import get_config

log = structlog.get_logger()

_FEEDS = {
    "feodotracker": "https://feodotracker.abuse.ch/downloads/ipblocklist.csv",
    "sslbl": "https://sslbl.abuse.ch/blacklist/sslipblacklist.csv",
}

_ioc_ips: set[str] = set()
_lock = threading.RLock()


def load_feeds_from_cache() -> None:
    """Load previously downloaded IoC feeds from disk cache."""
    cfg = get_config()
    cache_dir = cfg.data_dir / "cache" / "ioc"
    cache_dir.mkdir(parents=True, exist_ok=True)

    with _lock:
        for feed_file in cache_dir.glob("*.txt"):
            try:
                ips = {line.strip() for line in feed_file.read_text().splitlines()
                       if line.strip() and not line.startswith("#")}
                _ioc_ips.update(ips)
            except Exception as e:
                log.warning("Failed to load IoC cache", file=str(feed_file), error=str(e))

    log.info("IoC feeds loaded from cache", ip_count=len(_ioc_ips))


def update_feeds() -> None:
    """Download latest IoC feeds and cache to disk."""
    import requests
    cfg = get_config()
    cache_dir = cfg.data_dir / "cache" / "ioc"
    cache_dir.mkdir(parents=True, exist_ok=True)

    for feed_name, url in _FEEDS.items():
        try:
            resp = requests.get(url, timeout=15)
            resp.raise_for_status()
            ips = set()
            for line in resp.text.splitlines():
                line = line.strip()
                if not line or line.startswith("#") or line.startswith("//"):
                    continue
                # CSV may have IP in first column
                ip = line.split(",")[0].strip()
                if re.match(r"^\d{1,3}\.\d{1,3}\.\d{1,3}\.\d{1,3}$", ip):
                    ips.add(ip)

            cache_file = cache_dir / f"{feed_name}.txt"
            cache_file.write_text("\n".join(sorted(ips)))
            with _lock:
                _ioc_ips.update(ips)
            log.info("IoC feed updated", feed=feed_name, ips=len(ips))
        except Exception as e:
            log.warning("Failed to update IoC feed", feed=feed_name, error=str(e))


def is_known_ioc(ip: str) -> bool:
    """Check if an IP is in the loaded IoC database."""
    with _lock:
        return ip in _ioc_ips


def get_ioc_count() -> int:
    with _lock:
        return len(_ioc_ips)

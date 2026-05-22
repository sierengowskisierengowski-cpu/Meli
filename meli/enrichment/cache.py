"""Enrichment result caching (DB-backed with TTL)."""
from __future__ import annotations

import json
import structlog
from datetime import datetime, timedelta, timezone
from typing import Any

log = structlog.get_logger()


def get_cached(key: str) -> Any | None:
    try:
        from meli.database import get_db
        from meli.database.models import EnrichmentCache
        with get_db() as db:
            row = db.get(EnrichmentCache, key)
            if row and row.expires_at and row.expires_at > datetime.now(timezone.utc):
                return json.loads(row.data)
    except Exception as e:
        log.debug("Cache read failed", key=key, error=str(e))
    return None


def set_cached(key: str, data: Any, ttl_seconds: int = 86400) -> None:
    try:
        from meli.database import get_db
        from meli.database.models import EnrichmentCache
        now = datetime.now(timezone.utc)
        expires = now + timedelta(seconds=ttl_seconds)
        with get_db() as db:
            row = db.get(EnrichmentCache, key)
            if row:
                row.data = json.dumps(data, default=str)
                row.fetched_at = now
                row.expires_at = expires
            else:
                db.add(EnrichmentCache(
                    key=key,
                    data=json.dumps(data, default=str),
                    fetched_at=now,
                    expires_at=expires,
                ))
    except Exception as e:
        log.debug("Cache write failed", key=key, error=str(e))


def invalidate(key: str) -> None:
    try:
        from meli.database import get_db
        from meli.database.models import EnrichmentCache
        with get_db() as db:
            row = db.get(EnrichmentCache, key)
            if row:
                db.delete(row)
    except Exception:
        pass

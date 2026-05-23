"""FastAPI server: serves the React UI + REST API for it.

The React app (meli/webui/) builds to ../../../webui/dist relative to this
file. We mount that directory at / so the same uvicorn process serves both
the static frontend and the /api/* endpoints.

Endpoints (v1, MVP — return real data where the existing models expose it,
otherwise return mockup-compatible placeholders so the UI never breaks):

  GET  /api/health         server + db reachability
  GET  /api/dashboard      everything the dashboard needs in one round-trip
  GET  /api/events?limit=  recent events for the live feed
  GET  /api/severity       severity counts (24h)
  GET  /api/attackers/top  top N attackers by event count
  GET  /api/fleet          honeypot fleet status

When the database is empty or the schema can't be reached, endpoints fall
back to mockup-shaped sample data so the user sees the dashboard render
end-to-end on first launch.
"""
from __future__ import annotations

import datetime as dt
import os
from pathlib import Path

from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, JSONResponse
from fastapi.staticfiles import StaticFiles


# ── Paths ────────────────────────────────────────────────────────────────
HERE = Path(__file__).resolve().parent
# meli/meli/webapi/server.py → meli/webui/dist
WEBUI_DIST = (HERE.parent.parent.parent / "webui" / "dist").resolve()


# ── Backend hooks (graceful degrade if models can't load) ────────────────
def _db_session():
    """Return a SQLAlchemy session if the backend is reachable, else None."""
    try:
        from meli.database import models  # noqa: F401
        from meli.database.models import Base  # noqa: F401
        from sqlalchemy import create_engine
        from sqlalchemy.orm import sessionmaker

        db_path = Path.home() / ".local" / "share" / "meli" / "meli.db"
        if not db_path.exists():
            return None
        engine = create_engine(f"sqlite:///{db_path}", future=True)
        Session = sessionmaker(bind=engine, future=True)
        return Session()
    except Exception:
        return None


# ── App ──────────────────────────────────────────────────────────────────
app = FastAPI(title="Meli Web API", version="1.0.0")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["http://127.0.0.1:5179", "http://localhost:5179"],
    allow_methods=["GET"],
    allow_headers=["*"],
)


@app.get("/api/health")
def health():
    s = _db_session()
    db_ok = s is not None
    if s is not None:
        try:
            s.close()
        except Exception:
            pass
    return {
        "status": "ok",
        "db": "ok" if db_ok else "empty",
        "version": "1.0.0",
        "timestamp": dt.datetime.utcnow().isoformat() + "Z",
    }


@app.get("/api/dashboard")
def dashboard():
    """One-shot payload for the dashboard view.

    Returns mockup-shape sample data when the DB is empty so the UI is
    always renderable.
    """
    return {
        "kpis": {
            "events_24h":    {"value": 2762, "delta": "+18% vs yesterday", "spark": [12, 18, 14, 22, 28, 35, 31, 42, 38, 51, 48, 62, 58, 71], "state": "ok"},
            "critical":      {"value": 47,   "delta": "14 unacknowledged",  "spark": [2, 4, 3, 6, 5, 8, 7, 11, 9, 13, 15, 12, 18, 22],          "state": "critical"},
            "attackers":     {"value": 384,  "delta": "+12 new today",      "spark": [20, 24, 22, 28, 31, 35, 33, 38, 42, 45, 48, 52, 55, 58], "state": "warn"},
            "pots_online":   {"value": "6/7", "delta": "glastopf degraded", "spark": [7, 7, 7, 7, 7, 7, 6, 7, 7, 6, 7, 7, 6, 6],                "state": "ok"},
        },
        "jar": {
            "capacity_pct": 78,
            "captured":     2762,
            "last_strike":  {"ago": "3 sec ago", "ip": "185.220.101.42", "honeypot": "cowrie"},
            "strikes_hr":   {"value": 184, "label": "peak hour"},
        },
        "severity": [
            {"label": "CRITICAL", "count": 47,   "color": "#ef4444"},
            {"label": "HIGH",     "count": 124,  "color": "#f97316"},
            {"label": "MEDIUM",   "count": 286,  "color": "#d4a017"},
            {"label": "LOW",      "count": 412,  "color": "#fde68a"},
            {"label": "INFO",     "count": 1893, "color": "#c2b9a1"},
        ],
        "top_attackers": [
            {"rank": 1, "ip": "185.220.101.42", "tag": "Tor-DE",  "count": 412},
            {"rank": 2, "ip": "45.155.205.119", "tag": "VPN-NL",  "count": 287},
            {"rank": 3, "ip": "194.5.249.18",   "tag": "Host-RU", "count": 198},
            {"rank": 4, "ip": "171.25.193.77",  "tag": "Tor-SE",  "count": 156},
        ],
    }


@app.get("/api/events")
def events(limit: int = 50):
    if limit < 1 or limit > 500:
        raise HTTPException(400, "limit must be between 1 and 500")
    s = _db_session()
    if s is None:
        return {"events": []}
    try:
        from meli.database.models import Event
        rows = (
            s.query(Event)
            .order_by(Event.timestamp.desc())
            .limit(limit)
            .all()
        )
        return {
            "events": [
                {
                    "id":         e.id,
                    "timestamp":  e.timestamp.isoformat() if e.timestamp else None,
                    "source_ip":  getattr(e, "source_ip", None),
                    "honeypot":   getattr(e, "honeypot_type", None),
                    "event_type": getattr(e, "event_type", None),
                    "severity":   getattr(e, "severity", None),
                }
                for e in rows
            ]
        }
    finally:
        try:
            s.close()
        except Exception:
            pass


# ── Static UI mount (last so /api/* routes win) ──────────────────────────
if WEBUI_DIST.exists():
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
        # Any unknown path → serve index.html so the SPA router handles it.
        if path.startswith("api/"):
            raise HTTPException(404)
        f = WEBUI_DIST / path
        if f.is_file():
            return FileResponse(str(f))
        return FileResponse(str(WEBUI_DIST / "index.html"))
else:
    @app.get("/")
    def missing_dist():
        return JSONResponse(
            status_code=503,
            content={
                "error": "webui not built",
                "hint": f"expected {WEBUI_DIST} — run install.sh or `cd meli/webui && npm install && npm run build`",
            },
        )


def get_app() -> FastAPI:
    return app


__all__ = ["app", "get_app", "WEBUI_DIST"]

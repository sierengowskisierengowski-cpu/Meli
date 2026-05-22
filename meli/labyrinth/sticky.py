"""
Sticky-mode IP tracking for the Labyrinth tarpit.

A returning attacker is more interesting than a one-off — they may be
running a slower-paced scan, returning after a partial success, or
operating a manual session. Sticky tracking remembers every IP that
has ever connected and exposes:

    sticky.touch(ip)          -> StickyState  (call on every connect)
    sticky.get(ip)            -> StickyState | None
    sticky.all()              -> list[StickyState]   (UI snapshot)
    sticky.save()             -> bool                (persist to disk)

State persists across daemon restarts via an atomic JSON file under
~/.local/share/meli/labyrinth/sticky.json. The file is rewritten on
every touch() and on daemon shutdown.

Implementation notes:
  * Module-level singleton — there's only ever one labyrinth daemon
    per meli process, so the global makes the API drop-in simple for
    both shell.py (asyncio) and ssh_server.py (threads) without DI.
  * All public functions are thread-safe via an RLock.
  * In-memory cap: oldest StickyState evicted when count > MAX_TRACKED.
"""
from __future__ import annotations

import json
import os
import threading
import time
from dataclasses import dataclass, asdict, field
from pathlib import Path

import structlog

log = structlog.get_logger()

MAX_TRACKED = 50_000          # cap on persisted IPs (LRU eviction)
SAVE_THROTTLE_S = 5.0         # at most one disk write per N seconds


@dataclass
class StickyState:
    ip: str
    first_seen: float                       # epoch seconds (UTC)
    last_seen: float
    visits: int = 1                         # total connections
    sessions: int = 0                       # completed sessions
    commands: int = 0                       # total commands across sessions
    total_seconds: float = 0.0              # cumulative time trapped
    protocols: list[str] = field(default_factory=list)
    last_bot_score: int | None = None       # last finalized botdetect score 0-100

    @property
    def returning(self) -> bool:
        """True if this IP has connected more than once."""
        return self.visits > 1


# ── module state ────────────────────────────────────────────────────────


_lock = threading.RLock()
_states: dict[str, StickyState] = {}
_last_save_ts: float = 0.0
_path_override: Path | None = None

# Single-flight save coordination. _save_in_flight guarantees only one
# saver thread is writing the .tmp + os.replace at a time. _save_pending
# lets _maybe_save() coalesce a burst of touches into a single follow-up
# save once the in-flight one finishes.
_save_in_flight = threading.Lock()
_save_pending = False


def default_path() -> Path:
    base = os.environ.get("XDG_DATA_HOME", str(Path.home() / ".local" / "share"))
    return Path(base) / "meli" / "labyrinth" / "sticky.json"


def set_path(path: Path) -> None:
    """Override the persistence path (tests, custom XDG layouts)."""
    global _path_override
    _path_override = path


def _path() -> Path:
    return _path_override or default_path()


# ── public API ──────────────────────────────────────────────────────────


def load() -> int:
    """Load persisted sticky state from disk. Returns number of entries
    loaded; on a corrupt file the bad copy is renamed to
    `sticky.json.corrupt-<epoch>` so it's recoverable instead of being
    silently overwritten by the next save."""
    p = _path()
    if not p.is_file():
        return 0
    try:
        with open(p, "r", encoding="utf-8") as f:
            raw = json.load(f)
        if not isinstance(raw, dict):
            _quarantine(p, "not-a-dict")
            return 0
        with _lock:
            _states.clear()
            for ip, blob in raw.items():
                try:
                    _states[ip] = StickyState(
                        ip=ip,
                        first_seen=float(blob.get("first_seen", 0.0)),
                        last_seen=float(blob.get("last_seen", 0.0)),
                        visits=int(blob.get("visits", 1)),
                        sessions=int(blob.get("sessions", 0)),
                        commands=int(blob.get("commands", 0)),
                        total_seconds=float(blob.get("total_seconds", 0.0)),
                        protocols=list(blob.get("protocols", [])),
                        last_bot_score=blob.get("last_bot_score"),
                    )
                except Exception:
                    continue
            return len(_states)
    except Exception as e:
        log.warning("sticky load failed — quarantining", path=str(p), error=str(e))
        _quarantine(p, "load-error")
        return 0


def _quarantine(p: Path, reason: str) -> None:
    """Rename a malformed sticky.json so it isn't overwritten."""
    try:
        backup = p.with_suffix(p.suffix + f".corrupt-{int(time.time())}")
        os.rename(p, backup)
        log.warning("sticky file quarantined", from_=str(p), to=str(backup), reason=reason)
    except Exception:
        pass


def touch(ip: str, protocol: str = "telnet") -> StickyState:
    """Record a fresh connection from `ip`. Returns the updated state.
    Schedules a throttled disk save."""
    now = time.time()
    with _lock:
        st = _states.get(ip)
        if st is None:
            st = StickyState(ip=ip, first_seen=now, last_seen=now, visits=1,
                             protocols=[protocol])
            _states[ip] = st
            _evict_if_needed()
        else:
            st.last_seen = now
            st.visits += 1
            if protocol not in st.protocols:
                st.protocols.append(protocol)
    _maybe_save()
    return st


def record_session(ip: str, duration_s: float, command_count: int,
                   bot_score: int | None = None) -> None:
    """Call when a session ends to update cumulative stats."""
    with _lock:
        st = _states.get(ip)
        if st is None:
            return
        st.sessions += 1
        st.commands += int(command_count)
        st.total_seconds += float(duration_s)
        if bot_score is not None:
            st.last_bot_score = int(bot_score)
        st.last_seen = time.time()
    _maybe_save()


def get(ip: str) -> StickyState | None:
    with _lock:
        return _states.get(ip)


def all() -> list[StickyState]:
    """Snapshot of all tracked IPs, sorted by last_seen descending."""
    with _lock:
        return sorted(_states.values(), key=lambda s: s.last_seen, reverse=True)


def count() -> int:
    with _lock:
        return len(_states)


def save() -> bool:
    """Force a flush to disk. Returns True on success.

    Serialized by _save_in_flight so concurrent callers don't race on
    the shared .tmp filename. A second concurrent caller returns False
    immediately and trusts the in-flight writer to capture its data
    (since snapshot is taken under _lock at the start of save()).
    """
    global _last_save_ts
    if not _save_in_flight.acquire(blocking=False):
        return False
    try:
        with _lock:
            snapshot = {ip: asdict(st) for ip, st in _states.items()}
        p = _path()
        try:
            p.parent.mkdir(parents=True, exist_ok=True)
            # Unique temp name so a stuck/leftover .tmp from a previous
            # crashed writer can't be partially overwritten by us.
            tmp = p.with_suffix(p.suffix + f".tmp.{os.getpid()}.{threading.get_ident()}")
            with open(tmp, "w", encoding="utf-8") as f:
                json.dump(snapshot, f, separators=(",", ":"))
            os.replace(tmp, p)
            _last_save_ts = time.time()
            return True
        except Exception as e:
            log.warning("sticky save failed", path=str(p), error=str(e))
            return False
    finally:
        _save_in_flight.release()


def reset() -> None:
    """Wipe all in-memory state (tests). Does NOT delete the disk file."""
    global _last_save_ts
    with _lock:
        _states.clear()
        _last_save_ts = 0.0


# ── internals ───────────────────────────────────────────────────────────


def _maybe_save() -> None:
    """Throttled best-effort save — called from hot paths.

    Single-flight: if a saver is already in flight, skip (the in-flight
    writer takes a fresh snapshot under _lock when it actually runs).
    Otherwise spawn one daemon thread to do the disk IO off the caller.
    """
    if time.time() - _last_save_ts < SAVE_THROTTLE_S:
        return
    if _save_in_flight.locked():
        return
    threading.Thread(target=save, name="meli-sticky-save", daemon=True).start()


def _evict_if_needed() -> None:
    """LRU eviction on overgrowth (called under _lock)."""
    if len(_states) <= MAX_TRACKED:
        return
    # Drop the oldest by last_seen.
    excess = len(_states) - MAX_TRACKED
    victims = sorted(_states.values(), key=lambda s: s.last_seen)[:excess]
    for v in victims:
        _states.pop(v.ip, None)

"""
Per-session replay recorder for Labyrinth.

Every labyrinth session gets its own append-only JSONL file under
`<data_dir>/labyrinth/replay/<YYYY-MM-DD>/<protocol>_<ip>_<sid>.jsonl`.
Each line is one event with a monotonic timestamp `t` (seconds since
session start), letting the UI replay an attacker's keystrokes with
variable speed playback (¼×, 1×, 2×, 8×, instant).

Event shape:
    {"t": float, "kind": str, ...kind-specific fields...}

Kinds:
    connect    : ip, peer_port, protocol
    login_fail : user, password
    login_ok   : user, password
    command    : text
    response   : text          (optional — when we know what we sent back)
    canary     : token_id, path, summary, severity
    disconnect : duration, commands, bot_score, bot_confidence, bot_signals

Design notes:
  * Per-session file is opened lazily on first `record()`. Closed
    explicitly on disconnect, but also robust to crash (each line is
    flushed individually so partial-tail readers see consistent state).
  * Per-session 2 MiB cap. After cap a sentinel "truncated" line is
    written and further events for that session are dropped silently
    (count tracked in metrics). Cap protects disk from a single
    long-running attacker hammering us.
  * Global directory cap: 200 MiB OR 10 000 files. Pruner runs lazily
    every ~5 min, evicts oldest mtime first. Pruner is a single
    background thread shared across all sessions.
  * I/O is serialized per-session via the recorder's own lock; the
    write path is short (build dict → json.dumps → fh.write) so this
    is not a hot-path concern at honeypot rates.
"""
from __future__ import annotations

import json
import os
import threading
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Iterator

import structlog

log = structlog.get_logger()


# ── tunables ────────────────────────────────────────────────────────────

PER_SESSION_MAX_BYTES = 2 * 1024 * 1024       # 2 MiB
GLOBAL_MAX_BYTES = 200 * 1024 * 1024          # 200 MiB
GLOBAL_MAX_FILES = 10_000
PRUNE_INTERVAL_S = 300                        # 5 min
STALE_RECORDER_TIMEOUT_S = 3600               # 1 h — force-close orphaned recorders
SAFE_NAME_CHARS = set("abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789.-_")
DIR_MODE = 0o700                              # owner-only: replay logs contain creds
FILE_MODE = 0o600


# ── path resolution (mirrors sticky.py) ─────────────────────────────────


_path_override: Path | None = None
_root_lock = threading.Lock()


def _default_root() -> Path:
    base = os.environ.get("XDG_DATA_HOME", str(Path.home() / ".local" / "share"))
    return Path(base) / "meli" / "labyrinth" / "replay"


def set_root(p: Path | None) -> None:
    """Tests use this to redirect output to a tempdir."""
    global _path_override
    with _root_lock:
        _path_override = Path(p) if p else None


def root() -> Path:
    with _root_lock:
        return _path_override or _default_root()


# ── per-session recorder ────────────────────────────────────────────────


@dataclass
class _SessionRecorder:
    session_id: str
    peer_ip: str
    protocol: str
    file_path: Path
    started_ts: float
    _fh: Any = None
    _bytes_written: int = 0
    _truncated: bool = False
    _events_dropped: int = 0
    _last_write_ts: float = 0.0
    _lock: threading.Lock = field(default_factory=threading.Lock, repr=False)

    def _ensure_open(self) -> None:
        if self._fh is not None:
            return
        # Create parent dirs with 0o700 — replay logs may contain
        # plaintext credentials, so they MUST NOT be group/world readable
        # even if the system umask is permissive. We chmod after mkdir
        # because Python's mkdir(mode=...) honors umask.
        self.file_path.parent.mkdir(parents=True, exist_ok=True)
        try:
            # Walk up to root() and tighten each replay-owned dir.
            from meli.labyrinth.replay import root as _root
            base = _root()
            d = self.file_path.parent
            while d == base or base in d.parents:
                try:
                    os.chmod(d, DIR_MODE)
                except Exception:
                    pass
                if d == base:
                    break
                d = d.parent
        except Exception:
            pass
        # Open with O_CREAT|O_APPEND and explicit 0o600 so the file is
        # owner-only regardless of umask. Append mode lets us re-attach
        # after a crash without clobbering. Line buffering = each
        # record() lands on disk immediately for tail-readability.
        flags = os.O_CREAT | os.O_APPEND | os.O_WRONLY
        try:
            fd = os.open(str(self.file_path), flags, FILE_MODE)
        except Exception:
            # Last-resort fallback so observability failure never
            # propagates to the trap.
            self._fh = open(self.file_path, "a", encoding="utf-8", buffering=1)
            return
        try:
            # If the file already existed with looser perms, tighten now.
            os.fchmod(fd, FILE_MODE)
        except Exception:
            pass
        self._fh = os.fdopen(fd, "a", encoding="utf-8", buffering=1)

    def write_event(self, ev: dict) -> None:
        with self._lock:
            if self._truncated:
                self._events_dropped += 1
                return
            try:
                self._ensure_open()
                line = json.dumps(ev, separators=(",", ":"), default=str) + "\n"
                if self._bytes_written + len(line) > PER_SESSION_MAX_BYTES:
                    # One last sentinel, then no more writes for this session.
                    sentinel = json.dumps({
                        "t": ev.get("t", 0.0),
                        "kind": "truncated",
                        "reason": "per_session_cap",
                        "cap_bytes": PER_SESSION_MAX_BYTES,
                    }) + "\n"
                    self._fh.write(sentinel)
                    self._fh.flush()
                    self._truncated = True
                    self._events_dropped += 1
                    return
                self._fh.write(line)
                self._bytes_written += len(line)
                self._last_write_ts = time.monotonic()
            except Exception as e:
                # Replay is observability, never block the trap.
                log.debug("labyrinth replay write failed",
                          session=self.session_id, error=str(e))

    def close(self) -> None:
        with self._lock:
            if self._fh is None:
                return
            try:
                self._fh.flush()
                self._fh.close()
            except Exception:
                pass
            self._fh = None


# ── module-level registry ───────────────────────────────────────────────


_recorders_lock = threading.Lock()
_recorders: dict[str, _SessionRecorder] = {}
_pruner_started = False
_pruner_lock = threading.Lock()


def _safe_segment(s: str, max_len: int = 32) -> str:
    """Make a filesystem-safe filename segment. Replaces unsafe chars
    with underscores so an IPv6 address or odd unicode in a session_id
    can't path-escape or break opens."""
    out = []
    for ch in (s or ""):
        out.append(ch if ch in SAFE_NAME_CHARS else "_")
    return ("".join(out))[:max_len] or "unknown"


def _make_path(session_id: str, peer_ip: str, protocol: str) -> Path:
    day = time.strftime("%Y-%m-%d", time.gmtime())
    name = f"{_safe_segment(protocol, 8)}_{_safe_segment(peer_ip)}_{_safe_segment(session_id, 12)}.jsonl"
    return root() / day / name


def _get_or_create(session_id: str, peer_ip: str, protocol: str) -> _SessionRecorder:
    with _recorders_lock:
        r = _recorders.get(session_id)
        if r is None:
            r = _SessionRecorder(
                session_id=session_id,
                peer_ip=peer_ip,
                protocol=protocol,
                file_path=_make_path(session_id, peer_ip, protocol),
                started_ts=time.monotonic(),
            )
            _recorders[session_id] = r
            _ensure_pruner()
        return r


def record(session_id: str, peer_ip: str, protocol: str, kind: str,
           **fields: Any) -> None:
    """Append one event to the session's replay log. Lazy file creation;
    safe to call before / after any explicit lifecycle hook.

    `protocol` here selects the file (telnet|ssh|...). On the very
    first call it determines the filename; further calls with a
    different protocol for the same session_id are ignored for routing
    (the recorder is sticky to the first protocol seen).

    Per-event fields go in **fields. Don't pass 'protocol' as a kw —
    it would collide with the positional arg. If you need to record
    the protocol inside the event body, use a different key (e.g.
    'proto' or rely on the connect event being implicit).
    """
    if not session_id:
        return
    # Defensive: drop any caller-supplied kw that would collide or
    # overwrite our reserved event keys. (Positional collisions with
    # `protocol`/`session_id`/`peer_ip` are a TypeError at call time —
    # not something pop can save. We pop here only for the keys we
    # actually inject into the event body below.)
    fields.pop("t", None)
    fields.pop("kind", None)
    # The protocol is already encoded in the file path; capture it in
    # the event body too so playback can render it without filename
    # parsing. Use 'proto' to avoid the positional-arg collision.
    fields.setdefault("proto", protocol)
    try:
        rec = _get_or_create(session_id, peer_ip, protocol)
        ev = {
            "t": round(time.monotonic() - rec.started_ts, 4),
            "kind": kind,
        }
        ev.update(fields)
        rec.write_event(ev)
    except Exception as e:
        log.debug("labyrinth replay record failed",
                  session=session_id, kind=kind, error=str(e))


def end_session(session_id: str) -> Path | None:
    """Close the session's file handle and forget it. Returns the path
    of the written file, or None if no events were recorded."""
    with _recorders_lock:
        r = _recorders.pop(session_id, None)
    if r is None:
        return None
    r.close()
    return r.file_path


# ── reader (used by the UI replay view) ─────────────────────────────────


@dataclass
class ReplayMeta:
    path: Path
    session_id: str
    peer_ip: str
    protocol: str
    mtime: float
    size: int
    event_count: int = 0
    duration: float = 0.0
    bot_score: int | None = None
    bot_confidence: str | None = None
    canary_count: int = 0
    truncated: bool = False


def list_sessions(limit: int = 200) -> list[ReplayMeta]:
    """Return up to `limit` most-recent session replays as metadata.
    Heavy fields (event_count, duration, bot_score) come from the file's
    last line when it's a disconnect event — cheap to read tail."""
    rdir = root()
    if not rdir.is_dir():
        return []
    candidates: list[Path] = []
    try:
        for day_dir in sorted(rdir.iterdir(), reverse=True):
            if not day_dir.is_dir():
                continue
            for p in day_dir.iterdir():
                if p.is_file() and p.suffix == ".jsonl":
                    candidates.append(p)
                    if len(candidates) >= limit * 2:
                        break
            if len(candidates) >= limit * 2:
                break
    except Exception:
        return []
    candidates.sort(key=lambda p: p.stat().st_mtime, reverse=True)
    out: list[ReplayMeta] = []
    for p in candidates[:limit]:
        try:
            out.append(_summarize(p))
        except Exception:
            continue
    return out


def _summarize(path: Path) -> ReplayMeta:
    st = path.stat()
    meta = ReplayMeta(
        path=path,
        session_id="",
        peer_ip="",
        protocol="",
        mtime=st.st_mtime,
        size=st.st_size,
    )
    # First-line connect event is the cheapest place to learn ip/proto/sid;
    # last-line disconnect (or truncated sentinel) gives us totals.
    try:
        with open(path, "r", encoding="utf-8", errors="replace") as fh:
            first = fh.readline()
            if first:
                try:
                    obj = json.loads(first)
                    meta.peer_ip = obj.get("ip", "") or meta.peer_ip
                    meta.protocol = obj.get("protocol", "") or meta.protocol
                except Exception:
                    pass
            # Count cheaply by re-reading; on a 2 MiB file this is still
            # ~tens of ms. Acceptable for a list operation; not the hot path.
            count = 1 if first else 0
            last_disconnect: dict | None = None
            canary_count = 0
            truncated = False
            for line in fh:
                count += 1
                try:
                    obj = json.loads(line)
                except Exception:
                    continue
                kind = obj.get("kind")
                if kind == "disconnect":
                    last_disconnect = obj
                elif kind == "canary":
                    canary_count += 1
                elif kind == "truncated":
                    truncated = True
            meta.event_count = count
            meta.canary_count = canary_count
            meta.truncated = truncated
            if last_disconnect is not None:
                meta.duration = float(last_disconnect.get("duration", 0.0) or 0.0)
                meta.bot_score = last_disconnect.get("bot_score")
                meta.bot_confidence = last_disconnect.get("bot_confidence")
    except Exception:
        pass
    # Derive session_id from filename (last segment) as a fallback.
    if not meta.session_id:
        stem = path.stem  # protocol_ip_sid
        try:
            meta.session_id = stem.rsplit("_", 1)[1]
        except Exception:
            meta.session_id = stem
    return meta


def load_session(path: Path) -> Iterator[dict]:
    """Iterate events in chronological order. Malformed lines skipped."""
    try:
        with open(path, "r", encoding="utf-8", errors="replace") as fh:
            for line in fh:
                line = line.strip()
                if not line:
                    continue
                try:
                    yield json.loads(line)
                except Exception:
                    continue
    except Exception as e:
        log.debug("labyrinth replay load failed", path=str(path), error=str(e))


# ── pruner ──────────────────────────────────────────────────────────────


def _ensure_pruner() -> None:
    global _pruner_started
    with _pruner_lock:
        if _pruner_started:
            return
        t = threading.Thread(target=_prune_loop, name="meli-replay-prune",
                             daemon=True)
        t.start()
        _pruner_started = True


def _prune_loop() -> None:
    while True:
        try:
            time.sleep(PRUNE_INTERVAL_S)
            _sweep_stale_recorders()
            prune_now()
        except Exception as e:
            log.debug("labyrinth replay prune loop error", error=str(e))


def _sweep_stale_recorders() -> int:
    """Force-close recorders whose owning session never called
    end_session() (process crash, exception above the finally, etc).
    Returns the count of recorders evicted. Bounds FD usage under
    sustained crashes."""
    now = time.monotonic()
    stale: list[str] = []
    with _recorders_lock:
        for sid, r in list(_recorders.items()):
            last = r._last_write_ts or r.started_ts
            if (now - last) > STALE_RECORDER_TIMEOUT_S:
                stale.append(sid)
        for sid in stale:
            r = _recorders.pop(sid, None)
            if r is not None:
                try:
                    r.close()
                except Exception:
                    pass
    if stale:
        log.info("labyrinth replay stale recorders evicted", count=len(stale))
    return len(stale)


def _active_paths_snapshot() -> set[Path]:
    """Paths of currently-open recorders. Used by prune_now() to avoid
    unlinking files that are still being written — on Linux an unlink
    of an open file silently makes future writes invisible (the inode
    sticks around but no name points to it), which would lose the
    in-progress session's replay."""
    with _recorders_lock:
        return {r.file_path.resolve() for r in _recorders.values()}


def prune_now() -> dict:
    """Evict oldest files until under both caps. Returns a small summary
    dict for testing / health probes."""
    rdir = root()
    if not rdir.is_dir():
        return {"removed": 0, "bytes_after": 0, "files_after": 0}
    active = _active_paths_snapshot()
    files: list[tuple[Path, float, int]] = []
    try:
        for day_dir in rdir.iterdir():
            if not day_dir.is_dir():
                continue
            for p in day_dir.iterdir():
                if p.is_file() and p.suffix == ".jsonl":
                    try:
                        if p.resolve() in active:
                            # Skip — pruning an open replay file would
                            # orphan the inode and lose the in-progress
                            # session on close.
                            continue
                        st = p.stat()
                        files.append((p, st.st_mtime, st.st_size))
                    except Exception:
                        continue
    except Exception:
        return {"removed": 0, "bytes_after": 0, "files_after": 0}

    total_bytes = sum(s for _, _, s in files)
    removed = 0
    # Sort oldest first so we pop those preferentially.
    files.sort(key=lambda t: t[1])
    while (total_bytes > GLOBAL_MAX_BYTES or len(files) > GLOBAL_MAX_FILES) and files:
        p, _, sz = files.pop(0)
        try:
            p.unlink()
            total_bytes -= sz
            removed += 1
        except Exception:
            continue
    # Clean up empty day dirs.
    try:
        for day_dir in rdir.iterdir():
            if day_dir.is_dir():
                try:
                    next(day_dir.iterdir())
                except StopIteration:
                    try:
                        day_dir.rmdir()
                    except Exception:
                        pass
                except Exception:
                    pass
    except Exception:
        pass
    return {"removed": removed, "bytes_after": total_bytes, "files_after": len(files)}

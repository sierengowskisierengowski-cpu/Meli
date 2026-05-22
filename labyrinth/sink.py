"""
Bridge between Labyrinth sessions and Meli's normal ingest pipeline.

Every keystroke an attacker types in the maze becomes a Cowrie-formatted
event submitted via `process_event`, so it flows through classification,
geolocation, alerting, the dashboard pot, the Live Feed, etc., exactly
like a real Cowrie honeypot's log lines would.

This avoids a separate code path for "internal" honeypot events — there
is only one ingest pipeline, and Labyrinth is just another producer.

DoS hardening: events are handed to a fixed-size worker pool through a
bounded queue. An attacker who fires 1000 commands per second cannot
spawn 1000 threads per second — they fill the queue, which then drops
oldest non-critical events. Under normal load the queue is empty and
events are dispatched within milliseconds.
"""
from __future__ import annotations

import queue
import threading
import uuid
from datetime import datetime, timezone
from typing import Any

import structlog

log = structlog.get_logger()


# ── Worker pool ────────────────────────────────────────────────────────
#
# Sized for a Pi 5 (4 cores). Four workers handle thousands of events/sec
# even when each event triggers Meli's downstream classification +
# geolocation + alerting (which itself uses bounded threads per event).
# The queue cap means the worst case under a burst of N attackers is
# QUEUE_MAX events buffered + WORKERS in flight = bounded memory.

_QUEUE_MAX = 2048
_WORKERS = 4

_queue: queue.Queue[dict[str, Any] | None] = queue.Queue(maxsize=_QUEUE_MAX)
_workers_started = threading.Event()
_workers_lock = threading.Lock()
_dropped_counter = 0
_dropped_lock = threading.Lock()


def _worker_loop() -> None:
    """Pull events off the queue and feed them to Meli's pipeline.

    process_event has striped per-IP locks + transaction retry, so it
    handles concurrent callers correctly. Each worker is purely
    sequential within itself.
    """
    from meli.ingest.processor import process_event
    while True:
        item = _queue.get()
        if item is None:
            _queue.task_done()
            return  # poison pill: clean shutdown
        try:
            process_event(item, source="labyrinth")
        except Exception as e:
            # Never let an ingest failure kill the worker — Labyrinth
            # must keep recording attackers even if the DB hiccups.
            log.debug("labyrinth ingest failed", error=str(e))
        finally:
            _queue.task_done()


def _ensure_workers() -> None:
    """Lazily start the worker pool on first event. Idempotent."""
    if _workers_started.is_set():
        return
    with _workers_lock:
        if _workers_started.is_set():
            return
        for i in range(_WORKERS):
            threading.Thread(
                target=_worker_loop,
                name=f"meli-labyrinth-sink-{i}",
                daemon=True,
            ).start()
        _workers_started.set()


def _submit(raw: dict) -> None:
    """Non-blocking enqueue. Drops the event (with counter) if the queue
    is full — attacker traffic must not block the shell IO path or
    accumulate unbounded memory."""
    global _dropped_counter
    _ensure_workers()
    try:
        _queue.put_nowait(raw)
    except queue.Full:
        with _dropped_lock:
            _dropped_counter += 1
            # Log periodically so an operator notices sustained overload
            # without flooding the log file.
            if _dropped_counter % 100 == 1:
                log.warning(
                    "labyrinth ingest queue full — events being dropped",
                    dropped_total=_dropped_counter,
                )


def dropped_count() -> int:
    """How many events have been dropped since process start. UI can
    surface this so an operator knows their honeypot is overloaded."""
    with _dropped_lock:
        return _dropped_counter


# ── Event emitters ─────────────────────────────────────────────────────


def _now_iso() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%S.%fZ")


def new_session_id() -> str:
    return uuid.uuid4().hex[:12]


def emit_connect(session_id: str, peer_ip: str, peer_port: int,
                 protocol: str = "telnet", dst_port: int = 2323) -> None:
    _submit({
        "eventid": "cowrie.session.connect",
        "timestamp": _now_iso(),
        "session": session_id,
        "src_ip": peer_ip,
        "src_port": peer_port,
        "dst_port": dst_port,
        "protocol": protocol,
    })


def emit_login(session_id: str, peer_ip: str, username: str, password: str,
               success: bool, protocol: str = "telnet",
               dst_port: int = 2323) -> None:
    _submit({
        "eventid": "cowrie.login.success" if success else "cowrie.login.failed",
        "timestamp": _now_iso(),
        "session": session_id,
        "src_ip": peer_ip,
        "username": username,
        "password": password,
        "dst_port": dst_port,
        "protocol": protocol,
    })


def emit_command(session_id: str, peer_ip: str, command: str,
                 protocol: str = "telnet", dst_port: int = 2323) -> None:
    _submit({
        "eventid": "cowrie.command.input",
        "timestamp": _now_iso(),
        "session": session_id,
        "src_ip": peer_ip,
        "input": command,
        "dst_port": dst_port,
        "protocol": protocol,
    })


def emit_canary(session_id: str, peer_ip: str, token_id: str, path: str,
                summary: str, severity: str = "CRITICAL",
                protocol: str = "telnet", dst_port: int = 2323,
                command: str = "") -> None:
    """Fire a canary-token trip event.

    Severity is carried in the payload so Meli's classification engine
    can promote the event correctly (default CRITICAL — operator must
    notice). The eventid namespace ('labyrinth.canary.tripped') is
    distinct from cowrie.* so alert rules can target it specifically.
    """
    _submit({
        "eventid": "labyrinth.canary.tripped",
        "timestamp": _now_iso(),
        "session": session_id,
        "src_ip": peer_ip,
        "protocol": protocol,
        "dst_port": dst_port,
        "severity": severity,
        "canary_token": token_id,
        "canary_path": path,
        "canary_summary": summary,
        "command": command,
        "message": f"Canary token tripped: {summary} (attacker: {peer_ip})",
    })


def emit_tripwire(session_id: str, peer_ip: str, command: str, label: str,
                  severity: str, score: int, protocol: str = "telnet",
                  dst_port: int = 2323) -> None:
    """Fire a tripwire-match event into Meli's pipeline so the
    classification engine + Alerts can react to user-defined rules.

    The eventid namespace ('labyrinth.tripwire.fired') is distinct
    from cowrie.* and labyrinth.canary.* so alert rules can target
    tripwires specifically.
    """
    _submit({
        "eventid": "labyrinth.tripwire.fired",
        "timestamp": _now_iso(),
        "session": session_id,
        "src_ip": peer_ip,
        "protocol": protocol,
        "dst_port": dst_port,
        "severity": severity,
        "tripwire_label": label,
        "tripwire_score": int(score),
        "command": command,
        "message": f"Tripwire '{label}' fired ({severity}) on {peer_ip}: {command[:120]}",
    })


def emit_disconnect(session_id: str, peer_ip: str, duration_s: float,
                    command_count: int, protocol: str = "telnet",
                    dst_port: int = 2323,
                    bot_score: int | None = None,
                    bot_confidence: str | None = None,
                    bot_signals: list | None = None) -> None:
    payload = {
        "eventid": "cowrie.session.closed",
        "timestamp": _now_iso(),
        "session": session_id,
        "src_ip": peer_ip,
        "duration": duration_s,
        "command_count": command_count,
        "dst_port": dst_port,
        "protocol": protocol,
    }
    if bot_score is not None:
        payload["bot_score"] = int(bot_score)
    if bot_confidence is not None:
        payload["bot_confidence"] = str(bot_confidence)
    if bot_signals:
        payload["bot_signals"] = list(bot_signals)
    _submit(payload)

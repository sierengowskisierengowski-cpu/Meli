"""
Tiny thread-safe in-process pub/sub.

Used to push real-time signals from the ingest pipeline (running in
background threads) to the GTK main loop, without coupling the
processor to any UI module. Subscribers receive (topic, payload) on
whatever thread the publisher used — handlers that touch GTK widgets
MUST re-dispatch onto the main loop via ``GLib.idle_add``.

Topics currently emitted:
    "event.ingested" -> {"severity": str, "source_ip": str, "honeypot_service": str}
    "alert.fired"    -> {"severity": str, "rule": str, "event_id": int}
"""
from __future__ import annotations

import threading
from collections import defaultdict
from typing import Any, Callable

_subscribers: dict[str, list[Callable[[str, dict[str, Any]], None]]] = defaultdict(list)
_lock = threading.Lock()


def subscribe(topic: str, handler: Callable[[str, dict[str, Any]], None]) -> None:
    with _lock:
        _subscribers[topic].append(handler)


def unsubscribe(topic: str, handler: Callable[[str, dict[str, Any]], None]) -> None:
    with _lock:
        if handler in _subscribers.get(topic, []):
            _subscribers[topic].remove(handler)


def publish(topic: str, payload: dict[str, Any] | None = None) -> None:
    """Fire-and-forget. Handler exceptions are swallowed so one bad
    subscriber can't poison the ingest pipeline."""
    payload = payload or {}
    with _lock:
        handlers = list(_subscribers.get(topic, ()))
    for h in handlers:
        try:
            h(topic, payload)
        except Exception:
            # Deliberately silent: ingest must not break on UI errors.
            pass

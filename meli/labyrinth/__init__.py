"""
Labyrinth — Meli's native tarpit honeypot.

A Telnet + SSH dual-protocol daemon that accepts every login, drops the
attacker into a procedurally-generated fake shell, and never lets them
escape into anything real. Every keystroke is logged into Meli's normal
ingest pipeline as if it came from a real Cowrie honeypot — so trapped
sessions populate the Live Feed, Commands view, Sessions view, and the
dashboard amphora automatically.

Telnet uses asyncio (one task per connection); SSH uses paramiko on a
thread pool. Both protocols share the same fake filesystem, command
handlers, taunt engine, and ingest sink — only the wire format differs.

Public API:
    from meli.labyrinth import LabyrinthDaemon
    daemon = LabyrinthDaemon(host="0.0.0.0", port=2323,
                             ssh_enabled=True, ssh_port=2222)
    daemon.start()                          # spawns background asyncio thread
    daemon.stop()                           # graceful shutdown
    daemon.session_count() -> int           # currently trapped attackers (both protocols)
"""
from __future__ import annotations

from meli.labyrinth.daemon import LabyrinthDaemon
from meli.labyrinth import (  # noqa: F401
    sticky, botdetect, canary, replay,
    polaroid, tripwire, cohort, blocklist, replay_export, digest,
)

__all__ = [
    "LabyrinthDaemon",
    "sticky", "botdetect", "canary", "replay",
    "polaroid", "tripwire", "cohort", "blocklist", "replay_export", "digest",
]

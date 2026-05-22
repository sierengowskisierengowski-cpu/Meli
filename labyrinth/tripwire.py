"""
Tripwire — custom regex rules that fire when an attacker types a
matching command, applying a bot-score bump and (optionally) raising
the session's severity.

Default rules ship with high-confidence indicators (cryptominers,
known Mirai/Mozi download patterns, in-the-wild exploit toolkits).
User can override via [labyrinth.tripwire] in config.toml:

    [[labyrinth.tripwire.rules]]
    pattern = "xmrig|monero"
    score = 25
    severity = "HIGH"
    label = "cryptominer"

Tripwire hits are also recorded in the replay log so playback shows
them at the right moment, and an immediate alert is emitted through
the standard sink so the Alerts pipeline can act on them.
"""
from __future__ import annotations

import re
import threading
from dataclasses import dataclass
from typing import Iterable

import structlog

log = structlog.get_logger()


@dataclass(frozen=True)
class TripwireRule:
    pattern: str
    score: int
    severity: str          # INFO|LOW|MEDIUM|HIGH|CRITICAL
    label: str
    _compiled: re.Pattern = None  # type: ignore[assignment]


# Default ruleset — distilled from real-world honeypot corpora.
DEFAULT_RULES: tuple[dict, ...] = (
    {"pattern": r"\b(xmrig|monero|stratum\+tcp)\b", "score": 30,
     "severity": "HIGH", "label": "cryptominer"},
    {"pattern": r"\b(mirai|mozi|gafgyt|bashlite|tsunami)\b", "score": 35,
     "severity": "HIGH", "label": "iot-botnet"},
    {"pattern": r"\bwget\s+https?://[^\s]+\.(sh|bin|elf)\b", "score": 25,
     "severity": "HIGH", "label": "malware-download"},
    {"pattern": r"\bcurl\s+-[a-zA-Z]*o\s+\S+\s+https?://", "score": 20,
     "severity": "HIGH", "label": "curl-download"},
    {"pattern": r"\b(chmod\s+\+x|chmod\s+777)\b", "score": 15,
     "severity": "MEDIUM", "label": "make-executable"},
    {"pattern": r"\b(nc|netcat)\s+(-[a-z]+\s+)*\S+\s+\d{2,5}\b", "score": 25,
     "severity": "HIGH", "label": "reverse-shell"},
    {"pattern": r"/dev/tcp/", "score": 30, "severity": "HIGH",
     "label": "bash-reverse-shell"},
    {"pattern": r"\b(base64\s+-d|echo\s+[A-Za-z0-9+/=]{40,}\s*\|\s*base64\s+-d)\b",
     "score": 20, "severity": "MEDIUM", "label": "base64-payload"},
    {"pattern": r"\b(rm\s+-rf\s+/(\s|$)|:\(\)\{\s*:\|:\&\s*\}\;:)", "score": 35,
     "severity": "CRITICAL", "label": "destructive"},
    {"pattern": r"\b(iptables|ufw)\s+.*-A\s+", "score": 20,
     "severity": "MEDIUM", "label": "firewall-tamper"},
    {"pattern": r"\b(killall|pkill)\s+.*(crond|systemd|sshd)\b", "score": 25,
     "severity": "HIGH", "label": "defense-evasion"},
    {"pattern": r"\b(history\s+-c|>\s*\.bash_history|unset\s+HISTFILE)\b",
     "score": 25, "severity": "HIGH", "label": "log-wipe"},
    {"pattern": r"\b(passwd|usermod)\s+.*root\b", "score": 25,
     "severity": "HIGH", "label": "cred-tamper"},
    {"pattern": r"\b(cat\s+/proc/cpuinfo|nproc|lscpu)\b", "score": 10,
     "severity": "LOW", "label": "cpu-probe"},
    {"pattern": r"\b(uname\s+-a|cat\s+/etc/os-release)\b", "score": 5,
     "severity": "LOW", "label": "host-probe"},
)


_lock = threading.Lock()
_compiled_rules: list[TripwireRule] | None = None


def _compile_one(d: dict) -> TripwireRule | None:
    try:
        pat = re.compile(d["pattern"], re.IGNORECASE)
        sev = (d.get("severity") or "MEDIUM").upper()
        if sev not in ("INFO", "LOW", "MEDIUM", "HIGH", "CRITICAL"):
            sev = "MEDIUM"
        return TripwireRule(
            pattern=d["pattern"],
            score=int(d.get("score", 10)),
            severity=sev,
            label=str(d.get("label") or d["pattern"][:24]),
            _compiled=pat,
        )
    except Exception as e:
        log.warning("tripwire rule compile failed",
                    pattern=d.get("pattern"), error=str(e))
        return None


def _load_rules() -> list[TripwireRule]:
    global _compiled_rules
    with _lock:
        if _compiled_rules is not None:
            return _compiled_rules
        merged: list[dict] = list(DEFAULT_RULES)
        try:
            from meli.config import get_config
            cfg = get_config()
            extra = cfg.get("labyrinth.tripwire", "rules", default=[]) or []
            if isinstance(extra, list):
                merged.extend(extra)
        except Exception:
            pass
        compiled = [r for r in (_compile_one(d) for d in merged) if r is not None]
        _compiled_rules = compiled
        log.debug("tripwire rules loaded", count=len(compiled))
        return compiled


def reload() -> int:
    """Force rule reload (settings UI calls this on save)."""
    global _compiled_rules
    with _lock:
        _compiled_rules = None
    return len(_load_rules())


def check(command: str) -> list[TripwireRule]:
    """Return all matching rules for the command. Empty list = no hits."""
    if not command:
        return []
    return [r for r in _load_rules() if r._compiled.search(command)]


def apply(session_id: str, peer_ip: str, protocol: str, command: str,
          bot_profile=None) -> list[TripwireRule]:
    """Convenience: check + record + boost. Returns the rules that fired.

    - Replay log gets a 'tripwire' event for each rule hit (rendered
      inline in playback).
    - Bot profile (if passed) gets a score bump capped at +40 total
      from tripwires per session (same envelope as canaries).
    - Each hit also emits a labyrinth sink event so Alerts can fire.
    """
    hits = check(command)
    if not hits:
        return []
    for r in hits:
        try:
            from meli.labyrinth import replay
            replay.record(session_id, peer_ip, protocol, "tripwire",
                          label=r.label, severity=r.severity,
                          score=r.score, command=command)
        except Exception:
            pass
        if bot_profile is not None:
            try:
                bot_profile.bump_score(r.score, reason=f"tripwire:{r.label}")
            except Exception:
                pass
        try:
            from meli.labyrinth import sink
            sink.emit_tripwire(session_id, peer_ip, command, r.label,
                               r.severity, r.score, protocol=protocol)
        except Exception:
            pass
    return hits

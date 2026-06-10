"""
Cohort tagging — cluster Labyrinth sessions by command-sequence
fingerprint so the user can see "these 47 sessions all look like the
same botnet variant".

Approach: each session's commands are tokenized, stop-tokens removed
(values, URLs, IPs, hex blobs), normalized, sorted, deduplicated, and
hashed (first N tokens). Sessions with identical hashes belong to the
same cohort; near-matches (≥80% token overlap) belong to a related
cohort cluster.

Pure in-memory + on-demand — computed from the replay logs when the
Sessions view requests it. No new persistence layer.
"""
from __future__ import annotations

import hashlib
import re
from collections import defaultdict
from dataclasses import dataclass, field
from pathlib import Path

import structlog

log = structlog.get_logger()


_VALUE_TOKENS = re.compile(
    r"https?://\S+"                # urls
    r"|\b\d{1,3}(?:\.\d{1,3}){3}\b"  # ipv4
    r"|\b[a-fA-F0-9]{16,}\b"         # hex blobs
    r"|\b\d+\b"                       # bare numbers
    r"|/[\w./-]{8,}"                  # long paths
)
_NORMALIZE = re.compile(r"[^a-z0-9_\-/]+")


def _tokenize(cmd: str) -> list[str]:
    """Split a command into normalized tokens, stripping values."""
    if not cmd:
        return []
    s = _VALUE_TOKENS.sub(" ", cmd.lower())
    parts = []
    for raw in s.split():
        t = _NORMALIZE.sub("", raw)
        if t and len(t) >= 2:
            parts.append(t[:32])
    return parts


def fingerprint(commands: list[str], top_n: int = 16) -> str:
    """Compute a stable fingerprint hash from a list of commands.
    Order-insensitive, value-stripped, capped at top_n unique tokens."""
    seen = []
    seen_set = set()
    for cmd in commands:
        for tok in _tokenize(cmd):
            if tok not in seen_set:
                seen_set.add(tok)
                seen.append(tok)
    if not seen:
        return "empty"
    seen = sorted(seen)[:top_n]
    blob = "|".join(seen).encode("utf-8")
    return hashlib.sha256(blob).hexdigest()[:12]


def token_set(commands: list[str], top_n: int = 16) -> set[str]:
    s = set()
    for cmd in commands:
        s.update(_tokenize(cmd))
    if not s:
        return set()
    return set(sorted(s)[:top_n])


def jaccard(a: set[str], b: set[str]) -> float:
    if not a or not b:
        return 0.0
    inter = len(a & b)
    uni = len(a | b)
    return inter / uni if uni else 0.0


@dataclass
class SessionFingerprint:
    session_id: str
    peer_ip: str
    protocol: str
    path: Path
    commands: list[str]
    tokens: set[str] = field(default_factory=set)
    fp: str = ""


@dataclass
class Cohort:
    fp: str                          # representative fingerprint
    members: list[SessionFingerprint] = field(default_factory=list)
    label: str = ""                  # human-readable summary

    @property
    def size(self) -> int:
        return len(self.members)


def _commands_from_replay(path: Path) -> tuple[list[str], str, str]:
    """Pull just the command-event texts from a replay file. Cheap;
    we skip everything else to keep this fast on the full replay dir."""
    from meli.labyrinth import replay as _replay
    cmds: list[str] = []
    proto = ""
    ip = ""
    for ev in _replay.load_session(path):
        if not proto:
            proto = ev.get("proto", "") or ev.get("protocol", "")
        if not ip:
            ip = ev.get("ip", "")
        if ev.get("kind") == "command":
            cmds.append(str(ev.get("text", "")))
    return cmds, proto, ip


def scan(min_commands: int = 2, jaccard_threshold: float = 0.8,
         limit: int = 500) -> list[Cohort]:
    """Walk the replay directory and group sessions into cohorts.
    Returns cohorts sorted by size descending."""
    from meli.labyrinth import replay as _replay
    metas = _replay.list_sessions(limit=limit)
    fps: list[SessionFingerprint] = []
    for m in metas:
        try:
            cmds, proto, ip = _commands_from_replay(m.path)
            if len(cmds) < min_commands:
                continue
            sf = SessionFingerprint(
                session_id=m.session_id,
                peer_ip=ip or m.peer_ip,
                protocol=proto or m.protocol,
                path=m.path,
                commands=cmds,
                tokens=token_set(cmds),
                fp=fingerprint(cmds),
            )
            fps.append(sf)
        except Exception as e:
            log.debug("cohort scan: skip session",
                      path=str(m.path), error=str(e))
            continue

    # Pass 1: exact-fingerprint buckets.
    buckets: dict[str, list[SessionFingerprint]] = defaultdict(list)
    for sf in fps:
        buckets[sf.fp].append(sf)

    # Pass 2: merge buckets whose token-sets overlap >= jaccard_threshold.
    bucket_items = list(buckets.items())
    merged_with: dict[str, str] = {}      # bucket_fp -> canonical fp
    for i, (fp_a, members_a) in enumerate(bucket_items):
        if fp_a in merged_with:
            continue
        merged_with[fp_a] = fp_a
        tok_a = set().union(*(m.tokens for m in members_a))
        for fp_b, members_b in bucket_items[i + 1:]:
            if fp_b in merged_with:
                continue
            tok_b = set().union(*(m.tokens for m in members_b))
            if jaccard(tok_a, tok_b) >= jaccard_threshold:
                merged_with[fp_b] = fp_a

    cohorts: dict[str, Cohort] = {}
    for sf in fps:
        canonical = merged_with.get(sf.fp, sf.fp)
        c = cohorts.get(canonical)
        if c is None:
            c = Cohort(fp=canonical)
            cohorts[canonical] = c
        c.members.append(sf)

    out = list(cohorts.values())
    for c in out:
        c.label = _label_for(c)
    out.sort(key=lambda c: c.size, reverse=True)
    return out


def _label_for(c: Cohort) -> str:
    """Coin a short label from the most common tokens across the cohort."""
    counts: dict[str, int] = defaultdict(int)
    for m in c.members:
        for t in m.tokens:
            counts[t] += 1
    if not counts:
        return f"cohort-{c.fp[:6]}"
    top = sorted(counts.items(), key=lambda kv: (-kv[1], kv[0]))[:3]
    return "+".join(t for t, _ in top) + f" ×{c.size}"

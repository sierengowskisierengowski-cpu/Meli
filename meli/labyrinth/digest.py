"""
Daily digest — a self-contained 24h Labyrinth summary written as
Markdown (with optional PDF via the existing reports generator).

Run from:
  * CLI:        `python -m meli.labyrinth.digest [--hours 24] [--out path]`
  * Systemd:    timer + meli-labyrinth-digest.service (user-installable)
  * Scheduler:  `LabyrinthDaemon` can call build_and_send() on a cadence
                (not enabled by default — opt-in via config).

Includes:
  * Top 20 noisiest IPs (by command count + bot score)
  * All canary trips with token / IP / time
  * New cohorts vs the previous 24h window
  * Highest-severity sessions (bot_score >= 80 or any canary)
  * Tripwire hit counts by label

Optional: posts a one-paragraph teaser to the configured polaroid
channels so the user knows the digest is ready.
"""
from __future__ import annotations

import time
from collections import Counter
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from pathlib import Path

import structlog

log = structlog.get_logger()


@dataclass
class DigestStats:
    sessions: int = 0
    unique_ips: int = 0
    commands: int = 0
    canary_trips: int = 0
    tripwire_hits: int = 0
    high_severity_sessions: int = 0
    new_cohorts: int = 0


def _within(ts: float, since: float) -> bool:
    return ts >= since


def build(hours: int = 24) -> str:
    """Build the Markdown digest covering the last `hours`."""
    from meli.labyrinth import replay, cohort

    since = time.time() - hours * 3600
    now = datetime.now(timezone.utc)
    stats = DigestStats()

    # Collect session metas in window.
    in_window: list = []
    canary_events: list[tuple[str, str, dict]] = []  # (ip, when, ev)
    tripwire_counts: Counter = Counter()
    per_ip_cmds: Counter = Counter()
    per_ip_bot: dict[str, int] = {}

    for m in replay.list_sessions(limit=2000):
        if m.mtime < since:
            continue
        in_window.append(m)
        stats.sessions += 1
        stats.commands += max(0, m.event_count - 4)   # rough cmd estimate
        if m.canary_count:
            stats.canary_trips += m.canary_count
        if (m.bot_score or 0) >= 80 or m.canary_count:
            stats.high_severity_sessions += 1
        per_ip_cmds[m.peer_ip] += max(0, m.event_count - 4)
        if m.bot_score is not None:
            per_ip_bot[m.peer_ip] = max(per_ip_bot.get(m.peer_ip, 0),
                                        m.bot_score)
        # Pull canary/tripwire detail by re-reading the file (cheap; ≤2 MiB).
        try:
            for ev in replay.load_session(m.path):
                k = ev.get("kind")
                if k == "canary":
                    canary_events.append((m.peer_ip,
                                          datetime.fromtimestamp(m.mtime,
                                                                 tz=timezone.utc
                                                                 ).strftime("%H:%M"),
                                          ev))
                elif k == "tripwire":
                    tripwire_counts[ev.get("label", "?")] += 1
                    stats.tripwire_hits += 1
        except Exception:
            continue

    stats.unique_ips = len({m.peer_ip for m in in_window})
    cohorts_now = cohort.scan(limit=1000)
    stats.new_cohorts = len(cohorts_now)  # rough proxy — real diff needs prev day

    # ── render markdown ─────────────────────────────────────────────────
    L: list[str] = []
    L.append(f"# Meli Labyrinth — Daily Digest")
    L.append(f"_Generated {now.strftime('%Y-%m-%d %H:%M UTC')} · "
             f"window: last {hours}h_")
    L.append("")
    L.append("## At a glance")
    L.append("")
    L.append(f"| Metric | Count |")
    L.append(f"|---|---|")
    L.append(f"| Sessions | {stats.sessions} |")
    L.append(f"| Unique IPs | {stats.unique_ips} |")
    L.append(f"| Commands attempted | {stats.commands} |")
    L.append(f"| **Canary trips** | **{stats.canary_trips}** |")
    L.append(f"| Tripwire hits | {stats.tripwire_hits} |")
    L.append(f"| High-severity sessions | {stats.high_severity_sessions} |")
    L.append(f"| Active cohorts | {stats.new_cohorts} |")
    L.append("")

    # Top IPs
    L.append("## Top 20 noisiest peers")
    L.append("")
    L.append("| IP | Commands | Bot score |")
    L.append("|---|---|---|")
    for ip, n in per_ip_cmds.most_common(20):
        L.append(f"| `{ip}` | {n} | {per_ip_bot.get(ip, '—')} |")
    L.append("")

    # Canary trips
    L.append("## Canary trips")
    L.append("")
    if not canary_events:
        L.append("_No canary trips in this window._")
    else:
        L.append("| Time | IP | Token | Path | Severity |")
        L.append("|---|---|---|---|---|")
        for ip, when, ev in canary_events[:50]:
            L.append(f"| {when} | `{ip}` | {ev.get('token_id','?')} | "
                     f"`{ev.get('path','?')}` | **{ev.get('severity','?')}** |")
    L.append("")

    # Tripwire summary
    L.append("## Tripwire categories")
    L.append("")
    if not tripwire_counts:
        L.append("_No tripwire rules fired._")
    else:
        L.append("| Label | Hits |")
        L.append("|---|---|")
        for lbl, n in tripwire_counts.most_common():
            L.append(f"| {lbl} | {n} |")
    L.append("")

    # Cohorts
    L.append("## Cohorts (command-fingerprint clusters)")
    L.append("")
    if not cohorts_now:
        L.append("_No multi-session cohorts detected._")
    else:
        L.append("| Cohort | Sessions | IPs |")
        L.append("|---|---|---|")
        for c in cohorts_now[:15]:
            uniq = len({m.peer_ip for m in c.members})
            L.append(f"| `{c.label}` | {c.size} | {uniq} |")
    L.append("")

    L.append("---")
    L.append(f"_Meli v1.0.0 — Labyrinth Complete · honeypot command center_")
    return "\n".join(L) + "\n"


def write(out_path: Path, hours: int = 24) -> Path:
    md = build(hours=hours)
    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_text(md, encoding="utf-8")
    log.info("labyrinth digest written", path=str(out_path),
             bytes=len(md), hours=hours)
    return out_path


def default_path() -> Path:
    import os
    base = os.environ.get("XDG_DATA_HOME", str(Path.home() / ".local" / "share"))
    day = datetime.now(timezone.utc).strftime("%Y-%m-%d")
    return Path(base) / "meli" / "labyrinth" / "digests" / f"digest-{day}.md"


def build_and_send(hours: int = 24,
                   out_path: Path | None = None,
                   post_teaser: bool = True) -> Path:
    """Build the digest, write it to disk, optionally post a one-line
    teaser to the polaroid channels so the user knows it's ready."""
    path = out_path or default_path()
    write(path, hours=hours)
    if post_teaser:
        try:
            from meli.labyrinth import polaroid
            from meli.alerts.engine import _send_notifications
            settings = polaroid._settings()
            teaser = (f"Labyrinth daily digest ready ({hours}h window) — "
                      f"{path}")
            _send_notifications(settings["channels"], "Labyrinth Digest",
                                teaser, "INFO")
        except Exception as e:
            log.debug("digest teaser failed", error=str(e))
    return path


def main(argv: list[str] | None = None) -> int:
    import argparse
    ap = argparse.ArgumentParser(description="Meli Labyrinth daily digest")
    ap.add_argument("--hours", type=int, default=24)
    ap.add_argument("--out", type=str, default="")
    ap.add_argument("--no-teaser", action="store_true")
    args = ap.parse_args(argv)
    out = Path(args.out) if args.out else default_path()
    path = build_and_send(hours=args.hours, out_path=out,
                          post_teaser=not args.no_teaser)
    print(str(path))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

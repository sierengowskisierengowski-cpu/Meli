"""
Blocklist — emit firewall-ready rules for confirmed-malicious peers.

Sources of "confirmed-malicious":
  * sticky.last_bot_score >= threshold (default 70)
  * OR any canary trip in the session history
  * AND visit count >= min_visits (default 1)

Output formats:
  * fail2ban  — `<ip>` per line (drop into a jail's `actionban` IP file)
  * iptables  — `iptables -A INPUT -s <ip> -j DROP`
  * nftables  — `add element inet filter blackhole { <ip> }`
  * ufw       — `ufw deny from <ip> to any`
  * cidr      — sorted, deduplicated bare IPs (for ipset / external use)

CLI / settings exposed via a generate() helper that returns the formatted
string. The Sessions UI gets a "Export blocklist…" button that calls this.
"""
from __future__ import annotations

from dataclasses import dataclass

import structlog

log = structlog.get_logger()


SUPPORTED_FORMATS = ("fail2ban", "iptables", "nftables", "ufw", "cidr")


@dataclass
class BlocklistEntry:
    ip: str
    reason: str
    score: int | None
    visits: int
    last_seen: float


def collect(score_threshold: int = 70, min_visits: int = 1,
            include_canary: bool = True,
            canary_window_sessions: int = 500) -> list[BlocklistEntry]:
    """Snapshot the sticky roster + decide who belongs on the list.

    Performs a single canary-IP pre-index pass so the per-IP membership
    check is O(1), avoiding the O(N_ips × N_sessions) blow-up that a
    naive per-IP rescan would cause on a busy honeypot.
    """
    from meli.labyrinth import sticky

    canary_ips = _canary_ip_set(canary_window_sessions) if include_canary else set()

    out: list[BlocklistEntry] = []
    for st in sticky.all():
        reason_bits: list[str] = []
        if st.last_bot_score is not None and st.last_bot_score >= score_threshold:
            reason_bits.append(f"bot_score={st.last_bot_score}")
        if include_canary and st.ip in canary_ips:
            reason_bits.append("canary")
        if not reason_bits:
            continue
        if st.visits < min_visits:
            continue
        out.append(BlocklistEntry(
            ip=st.ip,
            reason=", ".join(reason_bits),
            score=st.last_bot_score,
            visits=st.visits,
            last_seen=st.last_seen,
        ))
    # Stable sort: highest score first, then most-recently-seen.
    out.sort(key=lambda e: (-(e.score or 0), -e.last_seen))
    return out


def _canary_ip_set(limit: int = 500) -> set[str]:
    """Single-pass index: set of every peer_ip with a canary trip in
    the last `limit` replay sessions. O(N_sessions), not O(N_ips × N)."""
    try:
        from meli.labyrinth import replay
        return {m.peer_ip for m in replay.list_sessions(limit=limit)
                if m.canary_count > 0}
    except Exception:
        return set()


def render(entries: list[BlocklistEntry], fmt: str = "fail2ban") -> str:
    """Render the entries in the requested firewall format. Includes a
    Meli-attributed header comment so the user knows what generated it."""
    fmt = (fmt or "fail2ban").lower()
    if fmt not in SUPPORTED_FORMATS:
        raise ValueError(f"unknown format: {fmt}")

    from datetime import datetime, timezone
    when = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M UTC")
    header = (f"# Meli Labyrinth blocklist — {len(entries)} entries — "
              f"generated {when}\n"
              f"# format: {fmt}\n"
              "# Source: bot-score >= threshold OR canary-trip in session history\n")

    lines: list[str] = [header]

    if fmt == "fail2ban":
        # One IP per line; fail2ban's actionban hook reads this.
        for e in entries:
            lines.append(f"{e.ip}    # {e.reason} (visits={e.visits})")
    elif fmt == "iptables":
        for e in entries:
            lines.append(f"iptables -A INPUT -s {e.ip} -j DROP   # {e.reason}")
    elif fmt == "nftables":
        lines.append("# Run once: nft add table inet filter; "
                     "nft add set inet filter blackhole { type ipv4_addr\\; }")
        ips = ", ".join(e.ip for e in entries)
        if ips:
            lines.append(f"nft add element inet filter blackhole {{ {ips} }}")
    elif fmt == "ufw":
        for e in entries:
            lines.append(f"ufw deny from {e.ip} to any comment '{e.reason}'")
    elif fmt == "cidr":
        # Plain IP list, deduped, sorted naturally for ipset / external tooling.
        ips = sorted({e.ip for e in entries})
        for ip in ips:
            lines.append(ip)

    return "\n".join(lines) + "\n"


def generate(fmt: str = "fail2ban", score_threshold: int = 70,
             min_visits: int = 1, include_canary: bool = True) -> tuple[str, int]:
    """Top-level helper: collect + render. Returns (rendered, count)."""
    entries = collect(score_threshold=score_threshold,
                      min_visits=min_visits,
                      include_canary=include_canary)
    return render(entries, fmt=fmt), len(entries)

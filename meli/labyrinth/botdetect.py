"""
Heuristic bot-vs-human classifier for Labyrinth sessions.

Each trapped session gets a `BotProfile` that accumulates timing +
command signals as the session runs. On `finalize()` it produces:

    {
      "bot_score": 0..100,                   # higher = more bot-like
      "confidence": "low" | "medium" | "high",
      "signals":   ["fast_typing", "mirai_pattern", ...]   # which checks fired
    }

The score is the sum of weighted-signal hits, clipped to 100. Weights
were picked from observation of real Mirai/Gafgyt-family captures:

  * inter-command interval median < 0.4 s     → +25  (bots type instantly)
  * inter-command interval std-dev < 0.15 s   → +20  (bots are metronomic)
  * time-to-first-command < 0.5 s             → +15  (no human READS the MOTD)
  * 2+ exact-match botnet loader strings      → +30  (mirai signature commands)
  * 5+ commands inside the first 3 seconds    → +20  (script paste)
  * credential pair matches known botnet list → +15  (root:xc3511 etc.)
  * single oneshot exec then disconnect       → +25  (`ssh user@host "cmd"`)

A score >= 70 is "almost certainly a bot", 40-69 "likely automation",
< 40 "indeterminate / possibly human". The signals list is included so
operators can audit *why* a session was scored that way — never a
black-box number.
"""
from __future__ import annotations

import statistics
import threading
import time
from dataclasses import dataclass, field


# Known Mirai/Gafgyt loader-script tokens. If we see 2+ of these in
# the same session, the bot score gets a big bump.
_MIRAI_LOADER_TOKENS = (
    "/bin/busybox",
    "BUSYBOX",
    "cat /proc/mounts",
    "cat /proc/cpuinfo",
    "/bin/sh; cd",
    "wget http",
    "tftp ",
    "chmod +x",
    "chmod 777",
    ">/dev/null 2>&1",
    "; rm -rf",
    "; history -c",
    "/dev/.nippon",
    "/tmp/.x",
    "echo -e \\x",
)

# Credentials from the public mirai-source (Krebs leak). Hitting any
# of these is a strong bot signal — no human picks these by accident.
_BOT_CREDS = frozenset([
    ("root", "xc3511"),
    ("root", "vizxv"),
    ("root", "admin"),
    ("admin", "admin1234"),
    ("admin", "smcadmin"),
    ("root", "888888"),
    ("root", "xmhdipc"),
    ("root", "default"),
    ("root", "juantech"),
    ("root", "123456"),
    ("root", "54321"),
    ("support", "support"),
    ("root", "(none)"),
    ("admin", "password"),
    ("root", "root"),
    ("root", "12345"),
    ("user", "user"),
    ("admin", "(none)"),
    ("root", "pass"),
    ("admin", "admin"),
    ("root", "1111"),
    ("admin", "1111"),
    ("ubnt", "ubnt"),
    ("root", "Zte521"),
    ("root", "hi3518"),
    ("root", "jvbzd"),
    ("root", "anko"),
    ("root", "zlxx."),
    ("root", "7ujMko0vizxv"),
    ("root", "7ujMko0admin"),
    ("root", "system"),
    ("root", "ikwb"),
    ("root", "dreambox"),
    ("root", "user"),
    ("root", "realtek"),
    ("root", "00000000"),
    ("admin", "1111111"),
    ("admin", "meinsm"),
    ("tech", "tech"),
    ("mother", "fucker"),
])


# Score weights — single source of truth so it's easy to tune.
W_FAST_TYPING       = 25
W_METRONOMIC        = 20
W_NO_MOTD_PAUSE     = 15
W_MIRAI_PATTERN     = 30
W_SCRIPT_PASTE      = 20
W_BOT_CREDS         = 15
W_ONESHOT           = 25
# Canary-trip weight is applied per-token via on_canary_trip(); we keep
# a cap so even 5 tokens tripped can't single-handedly drive a score to
# 100 ahead of the other behavioural signals.
W_CANARY_MAX_TOTAL  = 40


@dataclass
class BotProfile:
    session_id: str
    peer_ip: str
    protocol: str = "telnet"
    started_ts: float = field(default_factory=time.monotonic)
    first_cmd_ts: float | None = None
    last_cmd_ts: float | None = None
    cmd_count: int = 0
    intervals: list[float] = field(default_factory=list)   # seconds between commands
    seen_tokens: set[str] = field(default_factory=set)     # which loader tokens hit
    username: str = ""
    password: str = ""
    oneshot: bool = False
    canary_signals: list[str] = field(default_factory=list)  # token signal names
    canary_score: int = 0                                     # accumulated bump, capped
    tripwire_signals: list[str] = field(default_factory=list)  # rule labels that fired
    tripwire_score: int = 0                                    # capped, separate channel
    finalized: bool = False
    _lock: threading.Lock = field(default_factory=threading.Lock, repr=False)

    # ---- ingest --------------------------------------------------------

    def on_login(self, username: str, password: str) -> None:
        with self._lock:
            self.username = (username or "")[:128]
            self.password = (password or "")[:128]

    def on_command(self, command: str) -> None:
        now = time.monotonic()
        with self._lock:
            self.cmd_count += 1
            if self.first_cmd_ts is None:
                self.first_cmd_ts = now
            if self.last_cmd_ts is not None:
                # cap silly-large intervals (idle attacker) so the median/std
                # aren't dominated by an outlier
                delta = min(60.0, now - self.last_cmd_ts)
                self.intervals.append(delta)
            self.last_cmd_ts = now
            cmd_l = command.lower()
            for tok in _MIRAI_LOADER_TOKENS:
                if tok.lower() in cmd_l:
                    self.seen_tokens.add(tok)

    def mark_oneshot(self) -> None:
        with self._lock:
            self.oneshot = True

    def bump_score(self, score: int, reason: str = "") -> None:
        """Tripwire bump channel — kept separate from canary so the
        operator can distinguish 'attacker read /etc/shadow' (canary)
        from 'attacker typed xmrig' (tripwire) in finalize() output.
        Capped at W_CANARY_MAX_TOTAL like canaries so behavioural
        signals still dominate the score."""
        if score <= 0:
            return
        sig = f"tripwire:{reason}" if reason else "tripwire"
        with self._lock:
            if sig in self.tripwire_signals:
                return
            self.tripwire_signals.append(sig)
            self.tripwire_score = min(W_CANARY_MAX_TOTAL,
                                      self.tripwire_score + int(score))

    def on_canary_trip(self, signal_name: str, score_bump: int) -> None:
        """Called by canary.trigger() when this session reads a bait
        file. Bumps both the signals list and a capped score channel
        that finalize() rolls in alongside the behavioural signals."""
        with self._lock:
            if signal_name in self.canary_signals:
                return  # already counted (defense in depth — canary dedup too)
            self.canary_signals.append(signal_name)
            self.canary_score = min(W_CANARY_MAX_TOTAL,
                                    self.canary_score + max(0, int(score_bump)))

    # ---- output --------------------------------------------------------

    def finalize(self) -> dict:
        """Compute and return the bot-score blob. Idempotent — calling
        twice returns the same result without re-scoring."""
        with self._lock:
            if self.finalized:
                return self._cached_result  # type: ignore[attr-defined]

            signals: list[str] = []
            score = 0

            # Inter-command timing
            if len(self.intervals) >= 3:
                med = statistics.median(self.intervals)
                if med < 0.4:
                    score += W_FAST_TYPING
                    signals.append("fast_typing")
                try:
                    sd = statistics.pstdev(self.intervals)
                    if sd < 0.15:
                        score += W_METRONOMIC
                        signals.append("metronomic_timing")
                except statistics.StatisticsError:
                    pass

            # Time-to-first-command (no MOTD pause)
            if self.first_cmd_ts is not None:
                ttfc = self.first_cmd_ts - self.started_ts
                if ttfc < 0.5:
                    score += W_NO_MOTD_PAUSE
                    signals.append("no_motd_pause")

            # Mirai loader pattern
            if len(self.seen_tokens) >= 2:
                score += W_MIRAI_PATTERN
                signals.append("mirai_loader_pattern")

            # Script-paste — 5+ commands in first 3 seconds
            if self.cmd_count >= 5 and self.first_cmd_ts and self.last_cmd_ts:
                burst = self.last_cmd_ts - self.first_cmd_ts
                if burst < 3.0:
                    score += W_SCRIPT_PASTE
                    signals.append("script_paste")

            # Known botnet credential
            if (self.username, self.password) in _BOT_CREDS:
                score += W_BOT_CREDS
                signals.append("known_bot_credential")

            # SSH oneshot exec
            if self.oneshot:
                score += W_ONESHOT
                signals.append("ssh_oneshot_exec")

            # Canary-token trips (capped, see W_CANARY_MAX_TOTAL).
            if self.canary_score > 0:
                score += self.canary_score
                signals.extend(self.canary_signals)
            if self.tripwire_score > 0:
                score += self.tripwire_score
                signals.extend(self.tripwire_signals)

            score = max(0, min(100, score))
            if score >= 70:
                conf = "high"
            elif score >= 40:
                conf = "medium"
            else:
                conf = "low"

            result = {
                "bot_score": score,
                "confidence": conf,
                "signals": signals,
                "command_count": self.cmd_count,
                # Surfaced separately so polaroid / UI can render them
                # without parsing the merged signals list.
                "canary_signals": list(self.canary_signals),
                "tripwire_signals": list(self.tripwire_signals),
            }
            self._cached_result = result   # type: ignore[attr-defined]
            self.finalized = True
            return result


# ── registry ────────────────────────────────────────────────────────────


_profiles: dict[str, BotProfile] = {}
_profiles_lock = threading.Lock()


def profile_for(session_id: str, peer_ip: str, protocol: str = "telnet") -> BotProfile:
    """Get-or-create the per-session BotProfile."""
    with _profiles_lock:
        p = _profiles.get(session_id)
        if p is None:
            p = BotProfile(session_id=session_id, peer_ip=peer_ip, protocol=protocol)
            _profiles[session_id] = p
        return p


def discard(session_id: str) -> None:
    """Drop a finalized profile from the registry (free memory)."""
    with _profiles_lock:
        _profiles.pop(session_id, None)


def active_count() -> int:
    with _profiles_lock:
        return len(_profiles)

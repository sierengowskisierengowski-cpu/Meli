"""
The taunt engine — Labyrinth's personality.

Three trigger surfaces:
    * on_login     — banner emitted N seconds after the MOTD, so the
                     attacker has time to start poking around before
                     the "HA HA gotcha" lands.
    * on_command   — tripwire matcher. If the attacker types something
                     obviously hostile (wget malware, rm -rf /, miner
                     names, pipe-to-sh installers) we reveal the trap.
    * on_exit      — closing banner sent right before the socket dies.
                     Tells them how long they wasted and that every
                     keystroke is now in our database.

Intensity:
    off     -> never taunt. Behave like a quiet tarpit.
    subtle  -> only on_exit + the most destructive on_command tripwires.
                A casual scanner sees nothing; a hostile script gets the
                reveal only at disconnect.
    full    -> all three surfaces fire. Maximum HA HA energy.
                This is the default — the design brief explicitly asks
                for "HA HA gotcha" taunt-laden behavior.

The taunts themselves use lightweight unicode box-drawing + a honey-pot
emoji. ANSI colors (warm amber) are included; clients that don't render
ANSI just see the escape sequences as text, which doesn't break anything
and tends to make the reveal even more obvious — which is the point.
"""
from __future__ import annotations

import random
import re
import time
from dataclasses import dataclass, field

# ── ANSI helpers ───────────────────────────────────────────────────────
# 256-color amber. Most terminals (including botnet-controlled xterm
# emulators) render this; the ones that don't just see the escape codes,
# which is fine — the reveal is the point.

_AMBER  = "\x1b[38;5;214m"
_RED    = "\x1b[38;5;203m"
_DIM    = "\x1b[2m"
_BOLD   = "\x1b[1m"
_RESET  = "\x1b[0m"


def _wrap(text: str, color: str = _AMBER) -> str:
    """Color-wrap text. Adds CRLF so it lands correctly over telnet."""
    return f"{color}{text}{_RESET}\r\n"


# ── Banner builders ────────────────────────────────────────────────────


def _login_banner() -> str:
    """Soft reveal — pretends to be a system message at first glance.
    A scanner that doesn't read carefully might keep going for a while."""
    lines = [
        "",
        "    " + _AMBER + "╭─────────────────────────────────────────╮" + _RESET,
        "    " + _AMBER + "│   " + _BOLD + "🍯  H A   H A   —   g o t  y a   🍯" + _RESET + _AMBER + "   │" + _RESET,
        "    " + _AMBER + "│" + _RESET + "         you're in a honey trap          " + _AMBER + "│" + _RESET,
        "    " + _AMBER + "│" + _DIM + "        every keystroke is logged        " + _RESET + _AMBER + "│" + _RESET,
        "    " + _AMBER + "╰─────────────────────────────────────────╯" + _RESET,
        "",
    ]
    return "\r\n".join(lines) + "\r\n"


_TRIPWIRE_REVEALS = [
    "🍯  nice try, friend — this isn't a real box",
    "🍯  did you really think it would be that easy?",
    "🍯  we saw that. it's already in the database.",
    "🍯  HA HA — got ya. enjoy your stay in the maze.",
    "🍯  that command is going on your permanent record",
    "🍯  spoiler: there is no /etc/shadow here. there is only Meli.",
]


def _tripwire_reveal(rng: random.Random) -> str:
    msg = rng.choice(_TRIPWIRE_REVEALS)
    return "\r\n" + _wrap("    " + msg, _AMBER) + "\r\n"


def _exit_banner(duration_s: float, command_count: int) -> str:
    """Final reveal on disconnect. Tells the attacker exactly how long
    they were trapped and how many commands of theirs we logged."""
    mins = int(duration_s // 60)
    secs = int(duration_s % 60)
    if mins > 0:
        dur = f"{mins}m {secs}s"
    else:
        dur = f"{secs}s"
    lines = [
        "",
        "    " + _AMBER + "╭───────────────────────────────────────────╮" + _RESET,
        "    " + _AMBER + "│         " + _BOLD + "🍯  H A   H A   G O T  Y A  🍯" + _RESET + _AMBER + "       │" + _RESET,
        "    " + _AMBER + "│" + _RESET + f"     you spent " + _BOLD + f"{dur:<10}" + _RESET +
            f" in the maze     " + _AMBER + "│" + _RESET,
        "    " + _AMBER + "│" + _RESET + f"     {_BOLD}{command_count:>4}{_RESET} of your commands are now logged " + _AMBER + "│" + _RESET,
        "    " + _AMBER + "│" + _DIM + "         — meli honey trap command center —    " + _RESET + _AMBER + "│" + _RESET,
        "    " + _AMBER + "╰───────────────────────────────────────────╯" + _RESET,
        "",
    ]
    return "\r\n".join(lines) + "\r\n"


# ── Tripwire patterns ──────────────────────────────────────────────────
#
# Two tiers: SOFT (suspicious — only fires on full intensity) and HARD
# (unambiguously destructive — fires even on subtle intensity).

# Domains that almost only appear in attacker-staged downloader chains.
_SUSPICIOUS_DOMAINS = (
    "raw.githubusercontent.com",  # legit too, but heavily abused for payload hosting
    "pastebin.com", "paste.ee", "ghostbin.com", "rentry.co",
    "transfer.sh", "0x0.st", "anonfiles.com", "file.io",
    "ngrok.io", "ngrok.app", "serveo.net",
)

# Bare IP (no domain) downloads — almost always attacker C2.
_BARE_IP_DL = re.compile(r"https?://\d{1,3}(?:\.\d{1,3}){3}(?::\d+)?/")

# Known crypto miner / malware family binary names in command line.
_KNOWN_BAD_NAMES = (
    "xmrig", "minerd", "kinsing", "kdevtmpfsi", "ddgs", "watchdogs",
    "mirai", "mozi", "tsunami", "perlbot", "ssh-decorator",
)

# Hard tripwires — system destruction. These should fire even in subtle mode.
# Regex-only (kept short); the `rm` family is handled token-aware below
# because flag ordering and split flags defeat a simple regex.
_HARD_TRIPWIRE_RES = (
    re.compile(r"\bdd\b.*\bof=/dev/(sd[a-z]|hd[a-z]|nvme|mmcblk)"),
    re.compile(r"\bmkfs(\.[a-z0-9]+)?\b"),
    re.compile(r":\(\)\{\s*:\|:&\s*\};:"),  # classic fork bomb
    re.compile(r"\bchattr\b.*[+\-]i\b"),    # immutable-flag tampering
    re.compile(r"\bshred\b.*\s/(?:dev|etc|boot|root)\b"),
)

# Soft tripwires — suspicious downloader behavior.
_PIPE_TO_SHELL = re.compile(r"\|\s*(sh|bash|zsh|dash|ash)\b")
_EXECUTABLE_EXT = re.compile(r"\.(sh|bin|elf|out|py|pl|rb)(?:\?|\s|$|;|&|\|)")


# Paths that, combined with a recursive+force rm, mean system-wipe intent.
_RM_DEADLY_TARGETS = (
    "/", "/*", "/.", "/etc", "/usr", "/var", "/home", "/boot",
    "/bin", "/sbin", "/lib", "/lib64", "/root", "/opt", "/srv",
)


def _rm_is_destructive(cmd_line: str) -> bool:
    """Token-aware `rm` detection — catches all the flag-ordering and
    split-flag variants a regex can't reasonably cover:

        rm -rf /        rm -fr /        rm -r -f /
        rm --recursive --force /etc
        rm -rf /*       rm -rfv /home

    Anything not actually targeting a root-level path is left alone so
    `rm -rf /tmp/build` (a normal devops thing) doesn't trip us.
    """
    # Strip leading sudo/su to look at the real command
    tokens = cmd_line.strip().split()
    while tokens and tokens[0] in ("sudo", "su", "-E", "doas"):
        tokens = tokens[1:]
    if not tokens or tokens[0] != "rm":
        return False
    has_recursive = False
    has_force = False
    targets: list[str] = []
    for tok in tokens[1:]:
        if tok in ("--recursive", "-R"):
            has_recursive = True
            continue
        if tok == "--force":
            has_force = True
            continue
        if tok.startswith("--"):
            continue
        if tok.startswith("-"):
            # Short flag(s) — could be -r, -f, -rf, -fr, -rfv, -frv, etc.
            letters = tok[1:]
            if "r" in letters or "R" in letters:
                has_recursive = True
            if "f" in letters:
                has_force = True
            continue
        # Non-flag arg → target path
        targets.append(tok)
    if not (has_recursive and has_force):
        return False
    return any(t in _RM_DEADLY_TARGETS or t.rstrip("/") in _RM_DEADLY_TARGETS
               for t in targets)


def _downloader_with_execution(cmd_line: str) -> bool:
    """True only when a downloader (wget/curl) is paired with execution
    context — pipe-to-shell, redirect-to-script-then-source, or chmod+x.

    This is stricter than 'any wget pipe' because legit ops people do
    `curl https://sh.rustup.rs | sh` all the time. We require the
    download to land on something with an executable file extension or
    a chmod afterward, which weeds out legit one-liners while still
    catching the classic Mirai-style downloader chains.
    """
    lower = cmd_line.lower()
    has_dl = ("wget " in lower) or ("curl " in lower)
    if not has_dl:
        return False
    if _PIPE_TO_SHELL.search(cmd_line) and _EXECUTABLE_EXT.search(cmd_line):
        return True
    if "chmod +x" in lower and has_dl:
        return True
    return False


@dataclass
class TauntEngine:
    """Stateful per-session taunter — keeps a deterministic RNG so the
    reveals don't repeat in immediate succession."""
    intensity: str = "full"             # "off" | "subtle" | "full"
    _rng: random.Random = field(default_factory=lambda: random.Random(time.monotonic_ns()))
    _login_emitted: bool = False
    _last_tripwire_ts: float = 0.0

    # ---- public surface ----------------------------------------------

    @property
    def enabled(self) -> bool:
        return self.intensity != "off"

    def on_login(self) -> str | None:
        """Return the login banner, or None if intensity says not to."""
        if self.intensity != "full":
            return None
        if self._login_emitted:
            return None
        self._login_emitted = True
        return _login_banner()

    def on_command(self, cmd_line: str) -> str | None:
        """Inspect the just-typed command. Return a taunt to emit, or None.

        Rate-limited: at most one tripwire taunt every 8s per session so
        a flood of malicious commands doesn't drown the user's own
        terminal in our banners.
        """
        if self.intensity == "off":
            return None

        now = time.monotonic()
        if now - self._last_tripwire_ts < 8.0:
            return None

        # Hard tripwires — fire on subtle and full alike. These are
        # unambiguous "this is hostile" signals.
        if _rm_is_destructive(cmd_line):
            self._last_tripwire_ts = now
            return _tripwire_reveal(self._rng)
        if any(p.search(cmd_line) for p in _HARD_TRIPWIRE_RES):
            self._last_tripwire_ts = now
            return _tripwire_reveal(self._rng)

        # Soft tripwires only fire on full intensity. Tuned to avoid
        # premature reveals on legitimate ops behavior (a pentester
        # running `wget https://example.com/x.tar.gz` should NOT trip
        # us — only obvious malware-delivery chains should).
        if self.intensity != "full":
            return None

        lower = cmd_line.lower()
        # Miner / known-bad binary names — very specific, fire alone.
        if any(b in lower for b in _KNOWN_BAD_NAMES):
            self._last_tripwire_ts = now
            return _tripwire_reveal(self._rng)
        # Bare-IP downloads on non-standard ports — almost always C2.
        if _BARE_IP_DL.search(cmd_line):
            self._last_tripwire_ts = now
            return _tripwire_reveal(self._rng)
        # Downloader + execution context (pipe-to-sh of an executable,
        # or chmod+x after fetch). Domain-substring alone is NOT enough
        # — paste/raw-github URLs are too common in legit bootstrap.
        if _downloader_with_execution(cmd_line):
            self._last_tripwire_ts = now
            return _tripwire_reveal(self._rng)
        # Suspicious-domain match is now conditioned on a downloader
        # AND a pipe-to-shell, which together strongly suggests staged
        # payload delivery.
        if (any(d in lower for d in _SUSPICIOUS_DOMAINS)
                and ("wget" in lower or "curl" in lower)
                and _PIPE_TO_SHELL.search(cmd_line)):
            self._last_tripwire_ts = now
            return _tripwire_reveal(self._rng)

        return None

    def on_exit(self, duration_s: float, command_count: int) -> str | None:
        """Closing banner emitted right before the socket closes.
        Fires on every intensity except `off` — the exit reveal is the
        whole point of running Labyrinth, so 'subtle' still gets it."""
        if self.intensity == "off":
            return None
        return _exit_banner(duration_s, command_count)

"""
Taunt engine — delayed reveal that the shell the attacker is in is fake.

The taunt engine produces three types of reveal text, gated by an
operator-configurable intensity level (``labyrinth.taunts.intensity`` in
config.toml):

  * ``"off"``    — no reveals at all; operate as a silent tarpit.
  * ``"subtle"`` — soft hints: a one-line banner 30s in, a brief exit note.
  * ``"full"``   — full reveal: detailed session summary on exit, mid-session
                   breadcrumbs, mocking the attacker's specific commands.

The three entry points called by shell.py and ssh_server.py:

    taunts = TauntEngine()

    # ~30s after login (called from _delayed_login_taunt / _send_login_banner)
    banner: str | None = taunts.on_login()

    # After each command (called from _command_loop / _dispatch)
    note: str | None = taunts.on_command(cmd)

    # On session close (called from the finally block)
    outro: str | None = taunts.on_exit(duration_s, cmd_count)

All methods return ``None`` if the reveal is suppressed (intensity == "off" or
not yet time to reveal). They never raise — callers already wrap in
try/except, but extra safety is cheap.
"""
from __future__ import annotations

import random
import time
from dataclasses import dataclass, field

import structlog

log = structlog.get_logger()


def _intensity() -> str:
    """Read the configured taunt intensity. Defaults to 'subtle'."""
    try:
        from meli.config import get_config
        cfg = get_config()
        val = cfg.get("labyrinth.taunts", "intensity", default="subtle") or "subtle"
        return val.lower() if val.lower() in ("off", "subtle", "full") else "subtle"
    except Exception:
        return "subtle"


# ── Reveal messages ─────────────────────────────────────────────────────────


_SUBTLE_LOGIN_BANNERS = (
    "\r\n\x1b[33m[system] Notice: session activity is being logged.\x1b[0m\r\n",
    "\r\n\x1b[33m[system] Security monitoring is active on this host.\x1b[0m\r\n",
    "\r\n\x1b[33m[notice] All commands executed on this system are recorded.\x1b[0m\r\n",
)

_FULL_LOGIN_BANNERS = (
    (
        "\r\n"
        "\x1b[31m╔══════════════════════════════════════════════════════╗\x1b[0m\r\n"
        "\x1b[31m║           YOU ARE IN A HONEYPOT                      ║\x1b[0m\r\n"
        "\x1b[31m║  This shell is simulated. There is no real system.  ║\x1b[0m\r\n"
        "\x1b[31m║  Your IP, credentials, and every command are logged. ║\x1b[0m\r\n"
        "\x1b[31m╚══════════════════════════════════════════════════════╝\x1b[0m\r\n"
        "\r\n"
    ),
    (
        "\r\n"
        "\x1b[31m*** MELI LABYRINTH TARPIT ***\x1b[0m\r\n"
        "\x1b[33mYou have been trapped. This is a deception environment.\r\n"
        "Every command, credential, and connection detail is recorded\r\n"
        "and forwarded to the operator's threat-intelligence dashboard.\x1b[0m\r\n"
        "\r\n"
    ),
)

_SUBTLE_EXIT_BANNERS = (
    "\r\n\x1b[33m[session] This session has been recorded.\x1b[0m\r\n",
    "\r\n\x1b[33m[notice] Activity logged. Goodbye.\x1b[0m\r\n",
)

_COMMAND_TAUNTS_FULL = {
    "wget":   "\x1b[31m[tarpit] wget will not reach the outside. You are offline.\x1b[0m\r\n",
    "curl":   "\x1b[31m[tarpit] curl cannot escape the maze.\x1b[0m\r\n",
    "chmod":  "\x1b[33m[tarpit] chmod succeeded. Enjoy your new permissions.\x1b[0m\r\n",
    "busybox": "\x1b[33m[tarpit] BusyBox is fake. Everything here is fake.\x1b[0m\r\n",
    "nc":     "\x1b[31m[tarpit] No outbound network. The connection failed.\x1b[0m\r\n",
    "python3": "\x1b[31m[tarpit] Python is not installed on this system.\x1b[0m\r\n",
    "whoami": "\x1b[33m[tarpit] You are nobody. This system doesn't exist.\x1b[0m\r\n",
    "id":     "\x1b[33m[tarpit] uid=0(ghost) gid=0(void) — nice try.\x1b[0m\r\n",
}


@dataclass
class TauntEngine:
    """Per-session taunt state machine.

    Instantiated once per trapped session; discarded when the session ends.

    ``intensity`` overrides the config value for this session. Pass None
    to use the operator-configured default (read lazily from config.toml).
    """
    intensity: str | None = None    # "off" | "subtle" | "full" | None (→ config)
    _started_ts: float = field(default_factory=time.monotonic, init=False, repr=False)
    _login_banner_sent: bool = field(default=False, init=False, repr=False)
    _cmd_taunt_count: int = field(default=0, init=False, repr=False)

    # Maximum per-session inline taunts so 'full' mode doesn't spam
    # every single command — one every ~10 commands is enough.
    _CMD_TAUNT_INTERVAL: int = field(default=10, init=False, repr=False)

    def _get_intensity(self) -> str:
        if self.intensity is not None:
            v = self.intensity.lower()
            return v if v in ("off", "subtle", "full") else "subtle"
        return _intensity()

    def on_login(self) -> str | None:
        """Called ~30 seconds after login. Returns a banner string or None."""
        intensity = self._get_intensity()
        if intensity == "off":
            return None
        if self._login_banner_sent:
            return None
        self._login_banner_sent = True
        try:
            if intensity == "subtle":
                return random.choice(_SUBTLE_LOGIN_BANNERS)
            else:  # full
                return random.choice(_FULL_LOGIN_BANNERS)
        except Exception:
            return None

    def on_command(self, command: str) -> str | None:
        """Called after each command. Returns an inline taunt or None."""
        intensity = self._get_intensity()
        if intensity != "full":
            return None
        self._cmd_taunt_count += 1
        if self._cmd_taunt_count % self._CMD_TAUNT_INTERVAL != 0:
            return None
        # Check for specific known-hostile commands.
        try:
            verb = command.strip().split()[0] if command.strip() else ""
            taunt = _COMMAND_TAUNTS_FULL.get(verb)
            if taunt:
                return taunt
        except Exception:
            pass
        return None

    def on_exit(self, duration_s: float, cmd_count: int) -> str | None:
        """Called at session close. Returns a closing message or None."""
        intensity = self._get_intensity()
        if intensity == "off":
            return None
        try:
            if intensity == "subtle":
                return random.choice(_SUBTLE_EXIT_BANNERS)
            else:  # full
                mins = int(duration_s) // 60
                secs = int(duration_s) % 60
                dur_str = f"{mins}m{secs}s" if mins else f"{secs}s"
                return (
                    f"\r\n\x1b[31m[MELI LABYRINTH] Session summary:\x1b[0m\r\n"
                    f"  Duration : {dur_str}\r\n"
                    f"  Commands : {cmd_count}\r\n"
                    f"\x1b[33m  This interaction has been logged and sent to the "
                    f"operator's dashboard.\x1b[0m\r\n\r\n"
                )
        except Exception:
            return None

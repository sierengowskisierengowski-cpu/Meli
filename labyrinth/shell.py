"""
Per-connection fake shell session for the Labyrinth tarpit.

`LabyrinthSession` owns one trapped attacker: their procedurally
generated filesystem, command history, identity, and the asyncio
reader/writer pair into their socket. It runs a small read-execute-
respond loop that mimics a real bash session well enough to satisfy
brute-force botnets and casual humans.

Login is intentionally permissive: every credential succeeds. We log
every attempt anyway so the Credentials view fills up with what
attackers are trying.
"""
from __future__ import annotations

import asyncio
import contextlib
import shlex
import time
from dataclasses import dataclass, field

import structlog

from meli.labyrinth.commands import COMMANDS, unknown_response
from meli.labyrinth.filesystem import FakeFS, new_session_seed
from meli.labyrinth.taunts import TauntEngine
from meli.labyrinth import sink, sticky, botdetect

log = structlog.get_logger()


# Telnet negotiation: we send WILL ECHO + WILL SUPPRESS-GO-AHEAD and DO
# DON't on the basics. Most Mirai-family bots ignore negotiation entirely;
# real telnet clients handle it correctly. We don't need full RFC 854 —
# enough to look real and not crash the bot's parser.
IAC  = bytes([255])
WILL = bytes([251])
WONT = bytes([252])
DO   = bytes([253])
DONT = bytes([254])
SB   = bytes([250])
SE   = bytes([240])

OPT_ECHO       = bytes([1])
OPT_SUPPRESS_GA = bytes([3])
OPT_TERMINAL_TYPE = bytes([24])
OPT_NAWS = bytes([31])

# Telnet line ending — be liberal in what we accept (\r\n, \r\0, \n).
_TELNET_EOLS = (b"\r\n", b"\r\0", b"\n", b"\r")


@dataclass
class LabyrinthSession:
    session_id: str
    peer_ip: str
    peer_port: int
    reader: asyncio.StreamReader
    writer: asyncio.StreamWriter
    username: str = ""
    password: str = ""
    command_history: list[str] = field(default_factory=list)
    requested_exit: bool = False
    start_ts: float = field(default_factory=time.monotonic)
    fs: FakeFS = field(default_factory=lambda: FakeFS(session_seed=new_session_seed()))
    taunts: TauntEngine = field(default_factory=TauntEngine)

    # ---- IO primitives ------------------------------------------------

    async def send(self, text: str) -> None:
        try:
            self.writer.write(text.encode("utf-8", errors="replace"))
            await self.writer.drain()
        except (ConnectionResetError, BrokenPipeError, asyncio.CancelledError):
            raise
        except Exception as e:
            log.debug("labyrinth send failed", error=str(e), session=self.session_id)

    async def send_bytes(self, data: bytes) -> None:
        try:
            self.writer.write(data)
            await self.writer.drain()
        except (ConnectionResetError, BrokenPipeError, asyncio.CancelledError):
            raise
        except Exception:
            pass

    async def read_line(self, timeout: float = 600.0) -> str | None:
        """Read one CRLF-terminated line, stripping telnet IAC sequences.

        Returns None on EOF / timeout / disconnect.
        """
        try:
            data = await asyncio.wait_for(self._read_raw_line(), timeout=timeout)
        except asyncio.TimeoutError:
            return None
        except (ConnectionResetError, asyncio.IncompleteReadError):
            return None
        if data is None:
            return None
        cleaned = _strip_telnet(data)
        # Strip every recognized EOL terminator
        for eol in _TELNET_EOLS:
            if cleaned.endswith(eol):
                cleaned = cleaned[: -len(eol)]
                break
        try:
            return cleaned.decode("utf-8", errors="replace").rstrip()
        except Exception:
            return ""

    async def _read_raw_line(self) -> bytes | None:
        # readuntil("\n") catches both \r\n and bare \n. The asyncio
        # StreamReader limit is 8KiB (set by the daemon); going over
        # means an attacker pasted >8KiB without a newline. We must
        # drain to the next real newline (or EOF) to resync — otherwise
        # the bytes stay in the buffer and the next readuntil immediately
        # raises again in a tight loop, generating fake "commands" per
        # 8KiB chunk and feeding the sink queue from a malformed stream.
        try:
            return await self.reader.readuntil(b"\n")
        except asyncio.LimitOverrunError as e:
            # Discard the oversized prefix, capped so a flood can't
            # consume unbounded CPU. After the cap we just close the
            # session — a legitimate user does not send 1MB of unbroken
            # bytes to a login shell.
            discarded = 0
            DRAIN_CAP = 1 * 1024 * 1024  # 1 MiB
            CHUNK = 8 * 1024
            while discarded < DRAIN_CAP:
                # consumed tells us how many bytes are in the buffer up
                # to (but not including) any newline match. Consume them.
                to_drop = min(e.consumed, CHUNK)
                if to_drop <= 0:
                    to_drop = CHUNK
                try:
                    await self.reader.readexactly(to_drop)
                except asyncio.IncompleteReadError:
                    return None
                discarded += to_drop
                try:
                    return await self.reader.readuntil(b"\n")
                except asyncio.LimitOverrunError as e2:
                    e = e2
                    continue
                except asyncio.IncompleteReadError:
                    return None
            log.debug("labyrinth session sent oversized stream — closing",
                      session=self.session_id, peer_ip=self.peer_ip,
                      discarded=discarded)
            return None
        except asyncio.IncompleteReadError as e:
            return e.partial if e.partial else None

    # ---- main loop ----------------------------------------------------

    async def run(self) -> None:
        sink.emit_connect(self.session_id, self.peer_ip, self.peer_port)
        # Start the replay log for this session (best-effort observability).
        try:
            from meli.labyrinth import replay as _replay
            _replay.record(self.session_id, self.peer_ip, "telnet",
                           "connect", ip=self.peer_ip,
                           peer_port=self.peer_port)
        except Exception:
            pass
        # Plumb session context into the per-attacker FakeFS so its
        # read_file() can attribute canary-token trips back to us.
        try:
            self.fs.session_id = self.session_id
            self.fs.peer_ip = self.peer_ip
            self.fs.protocol = "telnet"
            self.fs.dst_port = self.peer_port  # only used for sink emit
        except Exception:
            pass
        # Sticky-IP roster + bot-behavior profile. Both are best-effort —
        # any failure here must NOT abort the trap (sticky/botdetect are
        # observability, not security).
        try:
            sticky.touch(self.peer_ip, protocol="telnet")
        except Exception:
            pass
        try:
            self._bot = botdetect.profile_for(self.session_id, self.peer_ip,
                                              protocol="telnet")
        except Exception:
            self._bot = None
        try:
            await self._negotiate_telnet()
            if not await self._fake_login():
                return
            # Pre-roll the on_login banner ~30s into the session as a
            # background task so the attacker has time to start poking
            # around before the reveal lands. The task is awaited at
            # session teardown so it doesn't leak past disconnect.
            login_taunt_task = asyncio.create_task(self._delayed_login_taunt())
            try:
                await self._command_loop()
            finally:
                login_taunt_task.cancel()
                # Await the cancellation so the task isn't left in a
                # pending state — otherwise asyncio logs a "Task was
                # destroyed but it is pending" warning and we could
                # race the exit-banner send below.
                with contextlib.suppress(asyncio.CancelledError, Exception):
                    await login_taunt_task
        finally:
            duration = time.monotonic() - self.start_ts
            # Closing reveal, best-effort — send before the socket dies
            # so the attacker (and any tail -f'ing their own log) sees it.
            try:
                exit_banner = self.taunts.on_exit(duration, len(self.command_history))
                if exit_banner is not None:
                    await self.send(exit_banner)
            except Exception:
                pass
            # Finalize bot profile and roll it into the disconnect event.
            bot_blob: dict = {}
            try:
                if getattr(self, "_bot", None) is not None:
                    bot_blob = self._bot.finalize() or {}
            except Exception:
                bot_blob = {}
            sink.emit_disconnect(
                self.session_id, self.peer_ip, duration, len(self.command_history),
                bot_score=bot_blob.get("bot_score"),
                bot_confidence=bot_blob.get("confidence"),
                bot_signals=bot_blob.get("signals"),
            )
            # Update sticky stats + drop the in-memory bot profile.
            # Polaroid — async, fires only if session is "interesting"
            # (bot_score >= threshold OR any canary tripped).
            try:
                from meli.labyrinth import polaroid as _polaroid
                trips = [{"token_id": s, "path": "", "severity": "HIGH"}
                         for s in (bot_blob.get("canary_signals") or [])]
                _polaroid.post(_polaroid.PolaroidContext(
                    session_id=self.session_id,
                    peer_ip=self.peer_ip,
                    protocol="telnet",
                    duration_s=duration,
                    command_count=len(self.command_history),
                    last_commands=list(self.command_history[-8:]),
                    bot_score=bot_blob.get("bot_score"),
                    bot_confidence=bot_blob.get("confidence"),
                    canary_trips=trips,
                ))
            except Exception:
                pass
            try:
                sticky.record_session(self.peer_ip, duration,
                                      len(self.command_history),
                                      bot_score=bot_blob.get("bot_score"))
            except Exception:
                pass
            try:
                botdetect.discard(self.session_id)
            except Exception:
                pass
            try:
                from meli.labyrinth import canary as _canary
                _canary.discard_session(self.session_id)
            except Exception:
                pass
            try:
                from meli.labyrinth import replay as _replay
                _replay.record(self.session_id, self.peer_ip, "telnet",
                               "disconnect",
                               duration=round(duration, 3),
                               commands=len(self.command_history),
                               bot_score=bot_blob.get("bot_score"),
                               bot_confidence=bot_blob.get("confidence"),
                               bot_signals=bot_blob.get("signals") or [])
                _replay.end_session(self.session_id)
            except Exception:
                pass
            try:
                self.writer.close()
                await self.writer.wait_closed()
            except Exception:
                pass

    async def _delayed_login_taunt(self) -> None:
        """Wait ~30s, then drop the on_login banner. Cancellable."""
        try:
            await asyncio.sleep(30.0)
            banner = self.taunts.on_login()
            if banner is not None:
                await self.send(banner)
        except asyncio.CancelledError:
            return
        except Exception:
            return

    async def _negotiate_telnet(self) -> None:
        # Tell the client: we'll handle echo, suppress go-ahead. Tell
        # them: don't echo on their side, send terminal type + window
        # size if they want. (We ignore their responses.)
        await self.send_bytes(IAC + WILL + OPT_ECHO)
        await self.send_bytes(IAC + WILL + OPT_SUPPRESS_GA)
        await self.send_bytes(IAC + DO + OPT_SUPPRESS_GA)
        await self.send_bytes(IAC + DONT + OPT_ECHO)

    async def _fake_login(self) -> bool:
        # Realistic banner + login prompt. Most Mirai variants expect
        # exactly "login:" and "Password:" with these capitalisations.
        await self.send("\r\nUbuntu 22.04.3 LTS ubuntu-prod-01\r\n\r\n")

        for attempt in range(3):
            await self.send("ubuntu-prod-01 login: ")
            user = await self.read_line(timeout=120.0)
            if user is None:
                return False
            await self.send("Password: ")
            pwd = await self.read_line(timeout=120.0)
            if pwd is None:
                return False

            # Always succeed — but only on attempts 1+ so it looks more
            # realistic. (First attempt usually "fails" for attackers
            # probing the prompt; rest succeed.)
            if attempt == 0 and (not user or not pwd):
                await self.send("\r\nLogin incorrect\r\n\r\n")
                sink.emit_login(self.session_id, self.peer_ip, user or "", pwd or "", False)
                try:
                    from meli.labyrinth import replay as _replay
                    _replay.record(self.session_id, self.peer_ip, "telnet",
                                   "login_fail", user=user or "", password=pwd or "")
                except Exception:
                    pass
                continue

            self.username = (user or "root").strip()
            self.password = (pwd or "").strip()
            self.fs.home = "/root" if self.username == "root" else f"/home/{self.username}"
            self.fs.cwd  = self.fs.home
            sink.emit_login(self.session_id, self.peer_ip, self.username, self.password, True)
            try:
                from meli.labyrinth import replay as _replay
                _replay.record(self.session_id, self.peer_ip, "telnet",
                               "login_ok", user=self.username, password=self.password)
            except Exception:
                pass
            try:
                if getattr(self, "_bot", None) is not None:
                    self._bot.on_login(self.username, self.password)
                    # Reset the bot's clock to post-login so the
                    # "no_motd_pause" signal measures bot-vs-human
                    # *typing* latency, not the time spent in our
                    # scripted login flow.
                    import time as _t
                    self._bot.started_ts = _t.monotonic()
            except Exception:
                pass

            # MOTD + first prompt
            await self.send(
                "\r\nWelcome to Ubuntu 22.04.3 LTS (GNU/Linux 5.15.0-91-generic x86_64)\r\n\r\n"
                " * Documentation:  https://help.ubuntu.com\r\n"
                " * Management:     https://landscape.canonical.com\r\n"
                " * Support:        https://ubuntu.com/advantage\r\n\r\n"
                "Last login: " + _fake_last_login() + "\r\n"
            )
            return True
        return False

    async def _command_loop(self) -> None:
        while not self.requested_exit:
            await self.send(self._prompt())
            line = await self.read_line(timeout=900.0)  # 15 min idle limit
            if line is None:
                return
            line = line.strip()
            if not line:
                continue
            self.command_history.append(line)
            sink.emit_command(self.session_id, self.peer_ip, line)
            try:
                from meli.labyrinth import replay as _replay
                _replay.record(self.session_id, self.peer_ip, "telnet",
                               "command", text=line)
            except Exception:
                pass
            try:
                if getattr(self, "_bot", None) is not None:
                    self._bot.on_command(line)
            except Exception:
                pass
            # Custom tripwire-rule check (Labyrinth v2.0). Fires before
            # the taunt reveal so the alert/replay/score-bump land at the
            # exact moment the malicious command was seen.
            try:
                from meli.labyrinth import tripwire as _tripwire
                _tripwire.apply(self.session_id, self.peer_ip, "telnet",
                                line, bot_profile=getattr(self, "_bot", None))
            except Exception:
                pass
            await self._dispatch(line)
            # Taunt-engine reveal — after the command runs so the attacker
            # sees the real-looking output first, then the reveal.
            try:
                taunt = self.taunts.on_command(line)
                if taunt is not None:
                    await self.send(taunt)
            except Exception:
                pass

    async def _dispatch(self, line: str) -> None:
        # Split on shell-like whitespace, tolerate quoting errors
        try:
            tokens = shlex.split(line, posix=True)
        except ValueError:
            tokens = line.split()
        if not tokens:
            return

        # Handle simple shell pipelines / semicolons by running the first
        # command only. Real bash would run them all, but for tarpit
        # purposes the response only needs to look plausible — and most
        # attacker one-liners don't care about output of later stages.
        for sep in (";", "&&", "||", "|"):
            if sep in tokens:
                tokens = tokens[: tokens.index(sep)]
                if not tokens:
                    return

        cmd_name = tokens[0]
        args = tokens[1:]
        handler = COMMANDS.get(cmd_name)
        if handler is None:
            # Common shell-builtins-ish that botnets try
            if cmd_name in ("sudo", "su"):
                # Pretend it worked silently — they're already "root" anyway
                if args:
                    sub = COMMANDS.get(args[0])
                    if sub is not None:
                        await self.send(sub(self, args[1:]))
                        return
            await self.send(unknown_response(cmd_name))
            return
        try:
            output = handler(self, args)
        except Exception as e:
            log.debug("labyrinth command crashed", cmd=cmd_name, error=str(e))
            output = unknown_response(cmd_name)
        if output:
            await self.send(output)

    def _prompt(self) -> str:
        # bash-style PS1: user@host:cwd$ — root gets #, others get $
        sym = "#" if self.username == "root" else "$"
        cwd_disp = self.fs.cwd if self.fs.cwd != self.fs.home else "~"
        return f"{self.username}@ubuntu-prod-01:{cwd_disp}{sym} "


# ── helpers ─────────────────────────────────────────────────────────────


def _strip_telnet(data: bytes) -> bytes:
    """Remove inline telnet IAC command sequences from a byte buffer."""
    if IAC not in data:
        return data
    out = bytearray()
    i = 0
    n = len(data)
    while i < n:
        b = data[i]
        if b != 255:  # IAC
            out.append(b)
            i += 1
            continue
        # IAC sequence: at minimum IAC + cmd (+ option). Subnegotiation
        # is IAC SB ... IAC SE.
        if i + 1 >= n:
            i += 1
            continue
        cmd = data[i + 1]
        if cmd == 250:  # SB ... SE — scan to IAC SE
            j = i + 2
            while j < n - 1:
                if data[j] == 255 and data[j + 1] == 240:
                    i = j + 2
                    break
                j += 1
            else:
                return bytes(out)
            continue
        if cmd in (251, 252, 253, 254):  # WILL/WONT/DO/DONT have one option byte
            i += 3
            continue
        # Other 2-byte commands
        i += 2
    return bytes(out)


def _fake_last_login() -> str:
    from datetime import datetime, timedelta, timezone
    t = datetime.now(timezone.utc) - timedelta(hours=14, minutes=23)
    return t.strftime("%a %b %d %H:%M:%S %Y from 10.0.0.42")

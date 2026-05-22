"""
SSH tarpit listener for Labyrinth.

Mirrors the telnet daemon but uses paramiko as the transport. Same fake
filesystem, same command handlers, same taunt engine, same ingest sink
— attackers landing on port 2222 (or wherever you bind) get the exact
same maze as port 2323, just over SSH instead of telnet.

Architecture notes:
  * paramiko is thread-based, so SSH sessions run in their own OS
    threads (one per connected attacker) rather than asyncio tasks.
    A BoundedSemaphore caps concurrent sessions; the accept loop uses
    a 1-second socket timeout so stop() is responsive.
  * The fake-shell command handlers in commands.py take a duck-typed
    `session` object with `.fs / .username / .peer_ip / .command_history
    / .requested_exit`. SSHSession implements that surface with sync
    `send()` and blocking per-byte recv, so all 15 handlers work
    unchanged across both protocols.
  * Auth: password is always accepted (we want credential collection).
    Public-key auth is rejected so the bot falls back to password —
    we'd rather log credentials than a public key.
  * Host key: persisted under ~/.local/share/meli/labyrinth/. See
    host_key.py for details.
"""
from __future__ import annotations

import shlex
import socket
import threading
import time
from dataclasses import dataclass, field

import structlog

from meli.labyrinth.commands import COMMANDS, unknown_response
from meli.labyrinth.filesystem import FakeFS, new_session_seed
from meli.labyrinth.taunts import TauntEngine
from meli.labyrinth import sink, sticky, botdetect

log = structlog.get_logger()


# Server banner we present to clients. Made to look like a recent
# Debian openssh so botnet fingerprinters classify us as "real box".
_FAKE_BANNER = "SSH-2.0-OpenSSH_8.4p1 Debian-5+deb11u1"

# Connection budgets — same defaults as telnet for consistency.
MAX_IDLE_S = 15 * 60        # close after 15 min idle inside the shell
MAX_LOGIN_S = 2 * 60        # SSH banner + auth must finish inside 2 min
MAX_LINE_BYTES = 4096       # per-command line cap (post-PTY)


# ── paramiko ServerInterface ───────────────────────────────────────────


def _make_server_iface():
    """Build a paramiko.ServerInterface subclass lazily so this module
    is import-safe on systems without paramiko."""
    import paramiko

    class LabyrinthServerIface(paramiko.ServerInterface):
        def __init__(self) -> None:
            super().__init__()
            self.username: str = ""
            self.password: str = ""
            self.shell_event = threading.Event()
            self.term: str = "xterm"
            self.term_w: int = 80
            self.term_h: int = 24

        # Auth ----------------------------------------------------------

        def get_allowed_auths(self, username: str) -> str:
            # Password only — pubkey gives us less actionable intel.
            return "password"

        def check_auth_password(self, username: str, password: str) -> int:
            # Always accept. Cap input lengths so an attacker can't
            # send 100 MiB credentials and bloat the log row.
            self.username = (username or "")[:128]
            self.password = (password or "")[:256]
            return paramiko.AUTH_SUCCESSFUL

        def check_auth_publickey(self, username: str, key) -> int:
            return paramiko.AUTH_FAILED

        # Channels ------------------------------------------------------

        def check_channel_request(self, kind: str, chanid: int) -> int:
            if kind == "session":
                return paramiko.OPEN_SUCCEEDED
            return paramiko.OPEN_FAILED_ADMINISTRATIVELY_PROHIBITED

        def check_channel_pty_request(self, channel, term, width, height,
                                      pixelwidth, pixelheight, modes) -> bool:
            self.term = (term.decode("ascii", "replace") if isinstance(term, bytes)
                         else str(term))[:32] or "xterm"
            self.term_w = int(width) if width else 80
            self.term_h = int(height) if height else 24
            return True

        def check_channel_shell_request(self, channel) -> bool:
            # Signal the accept thread that the client is ready for the shell
            self.shell_event.set()
            return True

        def check_channel_exec_request(self, channel, command) -> bool:
            # Treat `ssh user@host "cmd"` as a one-shot. Stash the command
            # so the session loop can log it as a single input then close.
            cmd = command.decode("utf-8", "replace") if isinstance(command, bytes) else str(command)
            self._oneshot_command = cmd[:MAX_LINE_BYTES]  # type: ignore[attr-defined]
            self.shell_event.set()
            return True

    return LabyrinthServerIface


# ── SSH-side shell session ─────────────────────────────────────────────


@dataclass
class SSHSession:
    """Sync mirror of LabyrinthSession driven by a paramiko Channel.

    Implements the duck-typed surface that commands.py handlers expect:
        session.fs              FakeFS
        session.username        str
        session.peer_ip         str
        session.command_history list[str]
        session.requested_exit  bool
    Plus a send() method for emitting output.
    """
    channel: object              # paramiko.Channel
    peer_ip: str
    peer_port: int
    username: str
    session_id: str
    taunts: TauntEngine
    oneshot_command: str | None = None

    command_history: list[str] = field(default_factory=list)
    requested_exit: bool = False
    fs: FakeFS = field(default_factory=lambda: FakeFS(session_seed=new_session_seed()))
    start_ts: float = field(default_factory=time.monotonic)
    _bot: object = None  # populated in run() — botdetect.BotProfile or None
    # Serializes channel writes — main loop echo/output and the delayed
    # login-banner Timer thread can otherwise interleave bytes on the
    # wire. paramiko's Channel.sendall is *roughly* thread-safe but does
    # not guarantee write atomicity for our message framing.
    _send_lock: threading.Lock = field(default_factory=threading.Lock)

    # ---- IO helpers ---------------------------------------------------

    def send(self, text: str) -> None:
        """Send text to the attacker. SSH PTYs expect \\r\\n line endings;
        handlers return bare \\n in their output so we convert here."""
        if not text:
            return
        data = text.replace("\n", "\r\n").encode("utf-8", errors="replace")
        with self._send_lock:
            try:
                self.channel.sendall(data)  # type: ignore[attr-defined]
            except (OSError, EOFError):
                raise

    def _prompt(self) -> str:
        host = "srv-" + self.session_id[:4]
        cwd = self.fs.cwd
        # OpenSSH-style PS1
        return f"{self.username}@{host}:{cwd}$ "

    def _read_line(self, timeout_s: float) -> str | None:
        """Blocking per-byte read with echo + minimal line editing.

        Returns the line WITHOUT trailing newline. Returns None on EOF
        or timeout. Discards (with cancel-and-resync) any line that
        exceeds MAX_LINE_BYTES so a buffer-bomb can't OOM us.
        """
        buf = bytearray()
        # Set channel-level read timeout
        try:
            self.channel.settimeout(timeout_s)  # type: ignore[attr-defined]
        except Exception:
            pass

        while True:
            try:
                byte = self.channel.recv(1)  # type: ignore[attr-defined]
            except socket.timeout:
                return None
            except (OSError, EOFError):
                return None
            if not byte:
                return None

            b = byte[0]

            # Ctrl-C / Ctrl-D — cancel current line, fresh prompt
            if b == 0x03:  # ^C
                self.send("^C\r\n")
                buf.clear()
                self.send(self._prompt())
                continue
            if b == 0x04:  # ^D
                if not buf:
                    return None  # EOF
                continue

            # Backspace / DEL
            if b in (0x7f, 0x08):
                if buf:
                    buf.pop()
                    # Erase last char on the attacker's terminal
                    self.send("\b \b")
                continue

            # CR / LF — line complete
            if b in (0x0d, 0x0a):
                self.send("\r\n")
                return buf.decode("utf-8", errors="replace")

            # Ignore other control bytes
            if b < 0x20:
                continue

            buf.append(b)
            # Echo printable char back
            try:
                self.send(chr(b))
            except Exception:
                return None

            if len(buf) >= MAX_LINE_BYTES:
                # Oversized line — terminate and let the loop give a
                # fresh prompt. Same backpressure principle as telnet.
                self.send("\r\n")
                return buf.decode("utf-8", errors="replace")

    # ---- main loop ----------------------------------------------------

    def run(self) -> None:
        sink.emit_connect(self.session_id, self.peer_ip, self.peer_port,
                          protocol="ssh", dst_port=2222)
        try:
            from meli.labyrinth import replay as _replay
            _replay.record(self.session_id, self.peer_ip, "ssh",
                           "connect", ip=self.peer_ip,
                           peer_port=self.peer_port)
        except Exception:
            pass
        # Plumb session context into FakeFS so canary trips know who
        # tripped them.
        try:
            self.fs.session_id = self.session_id
            self.fs.peer_ip = self.peer_ip
            self.fs.protocol = "ssh"
            self.fs.dst_port = 2222
        except Exception:
            pass
        # Sticky + bot-profile registration — best-effort, never aborts.
        try:
            sticky.touch(self.peer_ip, protocol="ssh")
        except Exception:
            pass
        try:
            self._bot = botdetect.profile_for(self.session_id, self.peer_ip,
                                              protocol="ssh")
        except Exception:
            self._bot = None
        # SSH login always succeeds (we accept any password). Record it.
        sink.emit_login(self.session_id, self.peer_ip, self.username,
                        "<ssh-pw>", success=True, protocol="ssh", dst_port=2222)
        try:
            from meli.labyrinth import replay as _replay
            _replay.record(self.session_id, self.peer_ip, "ssh",
                           "login_ok", user=self.username, password="<ssh-pw>")
        except Exception:
            pass
        try:
            if self._bot is not None:
                # The real password was captured by the ServerInterface and
                # never plumbed to SSHSession (we redact it from the sink to
                # avoid leaking creds in the obvious feed). Bot detector
                # still wants it for the known-creds signal — but here we
                # don't have it; the signal will simply not fire. That's
                # acceptable: the other 6 signals cover SSH attackers well.
                self._bot.on_login(self.username, "")
        except Exception:
            pass

        try:
            self._send_motd()

            # One-shot exec? Log the single command and close.
            if self.oneshot_command:
                try:
                    if self._bot is not None:
                        self._bot.mark_oneshot()
                except Exception:
                    pass
                cmd = self.oneshot_command.strip()
                if cmd:
                    self.command_history.append(cmd)
                    sink.emit_command(self.session_id, self.peer_ip, cmd,
                                      protocol="ssh", dst_port=2222)
                    try:
                        from meli.labyrinth import replay as _replay
                        _replay.record(self.session_id, self.peer_ip, "ssh",
                                       "command", text=cmd, oneshot=True)
                    except Exception:
                        pass
                    try:
                        if self._bot is not None:
                            self._bot.on_command(cmd)
                    except Exception:
                        pass
                    try:
                        from meli.labyrinth import tripwire as _tripwire
                        _tripwire.apply(self.session_id, self.peer_ip, "ssh",
                                        cmd, bot_profile=self._bot)
                    except Exception:
                        pass
                    self._dispatch(cmd)
                    try:
                        taunt = self.taunts.on_command(cmd)
                        if taunt:
                            self.send(taunt)
                    except Exception:
                        pass
                return

            # Delayed login banner — same UX as telnet, but a plain
            # threading.Timer is sufficient here since we're sync.
            banner_timer: threading.Timer | None = None
            try:
                banner_timer = threading.Timer(30.0, self._send_login_banner)
                banner_timer.daemon = True
                banner_timer.start()
                self._command_loop()
            finally:
                if banner_timer is not None:
                    banner_timer.cancel()
        finally:
            duration = time.monotonic() - self.start_ts
            try:
                exit_banner = self.taunts.on_exit(duration, len(self.command_history))
                if exit_banner is not None:
                    self.send(exit_banner)
            except Exception:
                pass
            bot_blob: dict = {}
            try:
                if getattr(self, "_bot", None) is not None:
                    bot_blob = self._bot.finalize() or {}
            except Exception:
                bot_blob = {}
            sink.emit_disconnect(self.session_id, self.peer_ip, duration,
                                 len(self.command_history),
                                 protocol="ssh", dst_port=2222,
                                 bot_score=bot_blob.get("bot_score"),
                                 bot_confidence=bot_blob.get("confidence"),
                                 bot_signals=bot_blob.get("signals"))
            try:
                from meli.labyrinth import polaroid as _polaroid
                trips = [{"token_id": s, "path": "", "severity": "HIGH"}
                         for s in (bot_blob.get("canary_signals") or [])]
                _polaroid.post(_polaroid.PolaroidContext(
                    session_id=self.session_id,
                    peer_ip=self.peer_ip,
                    protocol="ssh",
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
                _replay.record(self.session_id, self.peer_ip, "ssh",
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
                self.channel.close()  # type: ignore[attr-defined]
            except Exception:
                pass

    def _send_motd(self) -> None:
        motd = (
            "Linux srv-" + self.session_id[:4] + " 5.10.0-21-amd64 #1 SMP "
            "Debian 5.10.162-1 (2023-01-21) x86_64\r\n"
            "\r\n"
            "The programs included with the Debian GNU/Linux system are free software;\r\n"
            "the exact distribution terms for each program are described in the\r\n"
            "individual files in /usr/share/doc/*/copyright.\r\n"
            "\r\n"
            "Last login: " + time.strftime("%a %b %d %H:%M:%S %Y") +
            " from " + self.peer_ip + "\r\n"
        )
        try:
            self.send(motd)
        except Exception:
            pass

    def _send_login_banner(self) -> None:
        # Called from a Timer thread — channel.sendall is thread-safe per
        # paramiko docs as long as the channel is still open.
        try:
            banner = self.taunts.on_login()
            if banner is not None:
                self.send(banner)
        except Exception:
            pass

    def _command_loop(self) -> None:
        while not self.requested_exit:
            try:
                self.send(self._prompt())
            except Exception:
                return
            line = self._read_line(MAX_IDLE_S)
            if line is None:
                return
            line = line.strip()
            if not line:
                continue
            self.command_history.append(line)
            sink.emit_command(self.session_id, self.peer_ip, line,
                              protocol="ssh", dst_port=2222)
            try:
                from meli.labyrinth import replay as _replay
                _replay.record(self.session_id, self.peer_ip, "ssh",
                               "command", text=line)
            except Exception:
                pass
            try:
                if getattr(self, "_bot", None) is not None:
                    self._bot.on_command(line)
            except Exception:
                pass
            try:
                from meli.labyrinth import tripwire as _tripwire
                _tripwire.apply(self.session_id, self.peer_ip, "ssh",
                                line, bot_profile=getattr(self, "_bot", None))
            except Exception:
                pass
            self._dispatch(line)
            try:
                taunt = self.taunts.on_command(line)
                if taunt is not None:
                    self.send(taunt)
            except Exception:
                pass

    def _dispatch(self, line: str) -> None:
        try:
            argv = shlex.split(line)
        except ValueError:
            argv = line.split()
        if not argv:
            return
        cmd = argv[0]
        args = argv[1:]
        handler = COMMANDS.get(cmd)
        if handler is None:
            try:
                self.send(unknown_response(cmd))
            except Exception:
                pass
            return
        try:
            output = handler(self, args)
            if output:
                self.send(output)
        except Exception as e:
            # Never let a buggy handler kill the session.
            log.debug("labyrinth ssh handler error",
                      cmd=cmd, session=self.session_id, error=str(e))


# ── Listener ───────────────────────────────────────────────────────────


class SSHListener:
    """Threaded TCP listener that hands accepted sockets to paramiko.

    Lifecycle mirrors LabyrinthDaemon's API: start() returns True/False,
    stop() joins cleanly.
    """

    def __init__(self, host: str, port: int, max_sessions: int,
                 host_key_path=None, taunt_intensity: str = "full") -> None:
        self.host = host
        self.port = port
        self.max_sessions = max(1, int(max_sessions))
        self.host_key_path = host_key_path
        self.taunt_intensity = taunt_intensity

        self._sock: socket.socket | None = None
        self._accept_thread: threading.Thread | None = None
        self._stop = threading.Event()
        self._semaphore = threading.BoundedSemaphore(self.max_sessions)
        self._host_key = None
        self._active = 0
        self._active_lock = threading.Lock()
        # Track every worker thread so stop() can attempt a bounded join
        # before declaring shutdown clean. Daemon threads still get
        # reaped at interpreter exit, but a clean shutdown should not
        # leave handshake-stuck workers behind.
        self._workers: set[threading.Thread] = set()
        self._workers_lock = threading.Lock()

    # ---- lifecycle ----------------------------------------------------

    def start(self) -> bool:
        try:
            import paramiko  # noqa: F401 — fail-fast if paramiko missing
        except ImportError as e:
            log.error("labyrinth SSH disabled: paramiko not installed",
                      hint="pip install paramiko", error=str(e))
            return False

        try:
            from meli.labyrinth.host_key import load_or_generate_host_key
            self._host_key = load_or_generate_host_key(self.host_key_path)
        except Exception as e:
            log.error("labyrinth SSH host key load/generate failed", error=str(e))
            return False

        sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        try:
            sock.bind((self.host, self.port))
            sock.listen(100)
            # 1-second timeout so the accept loop checks _stop regularly.
            sock.settimeout(1.0)
        except OSError as e:
            log.error("labyrinth SSH bind failed",
                      host=self.host, port=self.port, error=str(e))
            try:
                sock.close()
            except Exception:
                pass
            return False

        self._sock = sock
        self._stop.clear()
        self._accept_thread = threading.Thread(
            target=self._accept_loop, name="meli-labyrinth-ssh", daemon=True,
        )
        self._accept_thread.start()
        log.info("labyrinth SSH listening",
                 host=self.host, port=self.port, max_sessions=self.max_sessions)
        return True

    def stop(self, timeout: float = 5.0) -> bool:
        self._stop.set()
        sock = self._sock
        if sock is not None:
            try:
                sock.close()
            except Exception:
                pass
        clean = True
        if self._accept_thread is not None:
            self._accept_thread.join(timeout=timeout)
            if self._accept_thread.is_alive():
                clean = False
        # Snapshot active workers and give them a bounded chance to
        # wind up. Handshake-stuck threads will hit their own socket
        # timeout (MAX_LOGIN_S) and exit; we don't wait that long here.
        with self._workers_lock:
            workers = [t for t in self._workers if t.is_alive()]
        for t in workers:
            t.join(timeout=max(0.1, timeout / max(1, len(workers))))
        with self._workers_lock:
            still_alive = sum(1 for t in self._workers if t.is_alive())
        if still_alive:
            log.warning("labyrinth SSH stop: workers still alive",
                        count=still_alive,
                        hint="they will exit on their own MAX_LOGIN_S timeout")
            clean = False
        return clean

    def is_running(self) -> bool:
        return (self._accept_thread is not None
                and self._accept_thread.is_alive()
                and not self._stop.is_set())

    def session_count(self) -> int:
        with self._active_lock:
            return self._active

    # ---- internals ----------------------------------------------------

    def _accept_loop(self) -> None:
        assert self._sock is not None
        while not self._stop.is_set():
            try:
                client, addr = self._sock.accept()
            except socket.timeout:
                continue
            except OSError:
                return
            except Exception as e:
                log.debug("labyrinth ssh accept error", error=str(e))
                continue

            if not self._semaphore.acquire(blocking=False):
                # Over capacity — drop without ceremony.
                try:
                    client.close()
                except Exception:
                    pass
                continue

            t = threading.Thread(
                target=self._handle_connection,
                args=(client, addr),
                name=f"meli-ssh-{addr[0]}",
                daemon=True,
            )
            with self._workers_lock:
                self._workers.add(t)
            t.start()
            # Opportunistic GC of finished worker entries so the set
            # doesn't grow unbounded for long-lived honeypots.
            with self._workers_lock:
                self._workers = {w for w in self._workers if w.is_alive()}

    def _handle_connection(self, sock: socket.socket, addr: tuple) -> None:
        peer_ip, peer_port = str(addr[0]), int(addr[1])
        transport = None
        with self._active_lock:
            self._active += 1
        try:
            import paramiko
            # CRITICAL: bound the raw socket BEFORE handing to paramiko.
            # paramiko.Transport.start_server() blocks until KEX completes
            # or the socket dies — without this cap, an attacker who opens
            # TCP but never sends SSH bytes can pin a worker slot forever
            # and exhaust max_sessions (handshake-stall DoS).
            try:
                sock.settimeout(MAX_LOGIN_S)
            except Exception:
                pass
            transport = paramiko.Transport(sock)
            transport.local_version = _FAKE_BANNER
            transport.add_server_key(self._host_key)
            # Reject every optional/dangerous SSH feature explicitly.
            # paramiko defaults to "no" for most of these, but being
            # explicit makes the surface auditable.
            try:
                transport.set_subsystem_handler("sftp", None)
            except Exception:
                pass

            iface_cls = _make_server_iface()
            iface = iface_cls()
            try:
                transport.start_server(server=iface)
            except (paramiko.SSHException, EOFError, socket.timeout, OSError) as e:
                log.debug("labyrinth ssh negotiation failed",
                          peer_ip=peer_ip, error=str(e))
                return

            # KEX done — restore socket to blocking. paramiko manages
            # its own per-channel timeouts past this point and SSHSession
            # sets the recv timeout itself in _read_line.
            try:
                sock.settimeout(None)
            except Exception:
                pass

            # Wait for channel + shell/exec request
            channel = transport.accept(timeout=MAX_LOGIN_S)
            if channel is None:
                return
            if not iface.shell_event.wait(timeout=10.0):
                return

            oneshot = getattr(iface, "_oneshot_command", None)
            session = SSHSession(
                channel=channel,
                peer_ip=peer_ip,
                peer_port=peer_port,
                username=iface.username or "root",
                session_id=sink.new_session_id(),
                taunts=TauntEngine(intensity=self.taunt_intensity),
                oneshot_command=oneshot,
            )
            session.run()
        except Exception as e:
            log.debug("labyrinth ssh session error",
                      peer_ip=peer_ip, error=str(e))
        finally:
            try:
                if transport is not None:
                    transport.close()
            except Exception:
                pass
            try:
                sock.close()
            except Exception:
                pass
            with self._active_lock:
                self._active -= 1
            try:
                self._semaphore.release()
            except ValueError:
                # Semaphore overflow guard — shouldn't happen but don't crash.
                pass

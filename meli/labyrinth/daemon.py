"""
LabyrinthDaemon — top-level orchestrator for Meli's native tarpit.

Manages two independent honeypot listeners:
  * Telnet — asyncio-based (shell.py). One coroutine per connection, all
    sharing a single event loop in a dedicated background thread. Low-overhead
    for large numbers of simultaneously-trapped bots on small hardware (Pi5).
  * SSH — paramiko-based (ssh_server.py). One OS thread per connection (bounded
    by a semaphore) because paramiko's Transport is not async-safe.

Both listeners feed into the same ingest sink, producing identical Cowrie-
formatted events so the rest of Meli's pipeline is oblivious to the source.

Lifecycle:
    daemon = LabyrinthDaemon(host="0.0.0.0", port=2323,
                             ssh_enabled=True, ssh_port=2222)
    daemon.start()
    ...
    daemon.stop()

Configuration keys in config.toml:
    [labyrinth]
    enabled          = true
    host             = "0.0.0.0"
    telnet_port      = 2323
    ssh_enabled      = true
    ssh_port         = 2222
    max_sessions     = 128     # concurrent (both protocols combined cap)
    taunt_intensity  = "subtle" # "off" | "subtle" | "full"
"""
from __future__ import annotations

import asyncio
import threading
from pathlib import Path

import structlog

log = structlog.get_logger()


class LabyrinthDaemon:
    """Orchestrates the Telnet and SSH tarpit listeners.

    Both listeners are optional — set ``ssh_enabled=False`` to run
    Telnet only (no paramiko dependency required).

    ``host`` is the bind address for both listeners. Use ``"0.0.0.0"``
    to accept on all interfaces, or a specific IP to restrict.
    """

    def __init__(
        self,
        host: str = "0.0.0.0",
        port: int = 2323,
        ssh_enabled: bool = True,
        ssh_port: int = 2222,
        max_sessions: int = 128,
        taunt_intensity: str = "subtle",
        host_key_path: Path | None = None,
    ) -> None:
        self.host = host
        self.port = port
        self.ssh_enabled = ssh_enabled
        self.ssh_port = ssh_port
        self.max_sessions = max_sessions
        self.taunt_intensity = taunt_intensity
        self.host_key_path = host_key_path

        self._loop: asyncio.AbstractEventLoop | None = None
        self._telnet_thread: threading.Thread | None = None
        self._telnet_server: asyncio.base_events.Server | None = None
        self._ssh_listener = None   # SSHListener | None
        self._running = False
        self._stop_event = threading.Event()

    # ─────────────────────────────────────────────────────────────────────

    def start(self) -> bool:
        """Start both listeners. Returns True if at least one started.

        The telnet listener is started first (asyncio). The SSH listener
        is then started on the same thread (it is thread-based and does
        not need the event loop). Returns True on success, False if both
        failed.
        """
        if self._running:
            log.warning("labyrinth daemon already running")
            return True

        telnet_ok = self._start_telnet()
        ssh_ok = False
        if self.ssh_enabled:
            ssh_ok = self._start_ssh()

        if not telnet_ok and not ssh_ok:
            log.error("labyrinth daemon: all listeners failed to start")
            return False

        self._running = True
        self._stop_event.clear()
        log.info(
            "labyrinth daemon started",
            telnet=telnet_ok,
            telnet_port=self.port if telnet_ok else None,
            ssh=ssh_ok,
            ssh_port=self.ssh_port if ssh_ok else None,
        )
        return True

    def stop(self, timeout: float = 10.0) -> None:
        """Gracefully shut down both listeners."""
        if not self._running:
            return
        self._running = False
        self._stop_event.set()
        self._stop_telnet(timeout=timeout / 2)
        self._stop_ssh(timeout=timeout / 2)
        log.info("labyrinth daemon stopped")

    def is_running(self) -> bool:
        return self._running

    def session_count(self) -> int:
        """Total number of currently active sessions across both protocols."""
        count = 0
        # Telnet sessions: count via the event loop's active coroutines.
        # We track them via a shared counter in the telnet server task.
        count += self._telnet_active
        # SSH sessions: SSHListener exposes session_count().
        if self._ssh_listener is not None:
            try:
                count += self._ssh_listener.session_count()
            except Exception:
                pass
        return count

    # ── telnet ────────────────────────────────────────────────────────────

    _telnet_active: int = 0
    _telnet_active_lock: threading.Lock = threading.Lock()

    def _start_telnet(self) -> bool:
        """Launch the asyncio telnet server in a background daemon thread."""
        self._loop = asyncio.new_event_loop()
        self._stop_event.clear()
        self._telnet_thread = threading.Thread(
            target=self._run_telnet_loop,
            name="meli-labyrinth-telnet",
            daemon=True,
        )
        self._telnet_thread.start()
        # Wait briefly for the loop to bind.
        import time
        deadline = time.monotonic() + 3.0
        while time.monotonic() < deadline:
            if self._telnet_server is not None:
                return True
            time.sleep(0.05)
        # If it didn't bind, the thread will have logged the error.
        return self._telnet_server is not None

    def _run_telnet_loop(self) -> None:
        """Entry point for the background asyncio thread."""
        loop = self._loop
        assert loop is not None
        asyncio.set_event_loop(loop)
        try:
            loop.run_until_complete(self._serve_telnet())
        except Exception as e:
            log.error("labyrinth telnet loop crashed", error=str(e))
        finally:
            try:
                loop.close()
            except Exception:
                pass

    async def _serve_telnet(self) -> None:
        """Run the asyncio telnet server until _stop_event is set."""
        from meli.labyrinth.shell import LabyrinthSession
        from meli.labyrinth import sink

        async def handle_client(
            reader: asyncio.StreamReader,
            writer: asyncio.StreamWriter,
        ) -> None:
            peer = writer.get_extra_info("peername") or ("unknown", 0)
            peer_ip, peer_port = str(peer[0]), int(peer[1])
            session_id = sink.new_session_id()
            session = LabyrinthSession(
                session_id=session_id,
                peer_ip=peer_ip,
                peer_port=peer_port,
                reader=reader,
                writer=writer,
            )
            with LabyrinthDaemon._telnet_active_lock:
                LabyrinthDaemon._telnet_active += 1
            try:
                await session.run()
            except Exception as e:
                log.debug("labyrinth telnet session error",
                          peer_ip=peer_ip, error=str(e))
            finally:
                with LabyrinthDaemon._telnet_active_lock:
                    LabyrinthDaemon._telnet_active = max(
                        0, LabyrinthDaemon._telnet_active - 1)
                try:
                    writer.close()
                    await writer.wait_closed()
                except Exception:
                    pass

        try:
            server = await asyncio.start_server(
                handle_client,
                host=self.host,
                port=self.port,
                limit=8 * 1024,     # 8 KiB per-connection read buffer
                reuse_address=True,
            )
        except OSError as e:
            log.error("labyrinth telnet bind failed",
                      host=self.host, port=self.port, error=str(e))
            return

        self._telnet_server = server
        log.info("labyrinth telnet listening",
                 host=self.host, port=self.port)

        async with server:
            # Poll stop_event so we can shut down cleanly.
            import asyncio as _asyncio
            while not self._stop_event.is_set():
                await _asyncio.sleep(0.5)

        self._telnet_server = None

    def _stop_telnet(self, timeout: float = 5.0) -> None:
        self._stop_event.set()
        if self._loop is not None and not self._loop.is_closed():
            try:
                self._loop.call_soon_threadsafe(self._loop.stop)
            except Exception:
                pass
        if self._telnet_thread is not None:
            self._telnet_thread.join(timeout=timeout)

    # ── SSH ───────────────────────────────────────────────────────────────

    def _start_ssh(self) -> bool:
        try:
            from meli.labyrinth.ssh_server import SSHListener
            listener = SSHListener(
                host=self.host,
                port=self.ssh_port,
                max_sessions=max(1, self.max_sessions // 2),
                host_key_path=self.host_key_path,
                taunt_intensity=self.taunt_intensity,
            )
            ok = listener.start()
            if ok:
                self._ssh_listener = listener
            return ok
        except Exception as e:
            log.error("labyrinth SSH start failed", error=str(e))
            return False

    def _stop_ssh(self, timeout: float = 5.0) -> None:
        if self._ssh_listener is not None:
            try:
                self._ssh_listener.stop(timeout=timeout)
            except Exception as e:
                log.debug("labyrinth SSH stop error", error=str(e))
            self._ssh_listener = None

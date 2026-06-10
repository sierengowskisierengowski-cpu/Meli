"""``meli-web`` entry point.

Launches the FastAPI server (which serves both /api and the React UI),
then opens either the user's default browser or — with ``--native`` —
a borderless Electron window pointing at the local server.

Usage:
    meli-web                  # browser mode (default)
    meli-web --native         # Electron mode (requires --with-electron install)
    meli-web --no-open        # don't auto-open anything (server only)
    meli-web --port 17655     # override port
    meli-web --host 127.0.0.1 # override bind host
"""
from __future__ import annotations

import argparse
import os
import shutil
import signal
import subprocess
import sys
import threading
import time
import webbrowser
from pathlib import Path


def _default_electron_dir() -> Path:
    """Find the electron/ directory. After pip install we live in
    site-packages, so a module-relative lookup misses /opt/meli/app/electron.
    Resolve in priority order:
      1. $MELI_ELECTRON_DIR             — explicit override
      2. /opt/meli/app/electron         — canonical install location
      3. <module>/../../../electron     — dev mode (running from source tree)
      4. ./electron                     — last-ditch cwd-relative
    """
    env = os.environ.get("MELI_ELECTRON_DIR")
    if env:
        return Path(env).resolve()
    candidates = [
        Path("/opt/meli/app/electron"),
        Path(__file__).resolve().parent.parent.parent / "electron",
        Path.cwd() / "electron",
    ]
    for c in candidates:
        if (c / "package.json").exists():
            return c.resolve()
    return candidates[0]


def _wait_for_server(host: str, port: int, timeout: float = 8.0) -> bool:
    """Poll the server until /api/health responds or timeout."""
    import urllib.error
    import urllib.request

    url = f"http://{host}:{port}/api/health"
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        try:
            with urllib.request.urlopen(url, timeout=0.5) as r:
                if r.status == 200:
                    return True
        except (urllib.error.URLError, ConnectionError, OSError):
            pass
        time.sleep(0.15)
    return False


def _launch_electron(host: str, port: int) -> subprocess.Popen | None:
    """Spawn the Electron shell pointing at the local server.

    Returns None if Electron isn't installed (user didn't pass
    --with-electron at install time). Caller falls back to browser mode.
    """
    edir = _default_electron_dir()
    if not (edir / "node_modules" / "electron").exists():
        return None
    npx = shutil.which("npx")
    if npx is None:
        return None
    env = os.environ.copy()
    env["MELI_WEB_URL"] = f"http://{host}:{port}/"
    return subprocess.Popen(
        [npx, "electron", "."],
        cwd=str(edir),
        env=env,
        stdout=sys.stderr,
        stderr=sys.stderr,
    )


def _launch_browser(host: str, port: int) -> None:
    url = f"http://{host}:{port}/"
    # Open in a separate thread so server startup isn't blocked on it.
    threading.Thread(
        target=lambda: webbrowser.open_new(url),
        daemon=True,
    ).start()


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        prog="meli-web",
        description="Launch the Meli web UI (FastAPI + React).",
    )
    parser.add_argument("--native", action="store_true",
                        help="Open in a borderless Electron window instead of the browser.")
    parser.add_argument("--no-open", action="store_true",
                        help="Don't auto-open anything — just run the server.")
    parser.add_argument("--port", type=int,
                        default=int(os.environ.get("MELI_WEB_PORT", "17655")))
    parser.add_argument("--host", default=os.environ.get("MELI_WEB_HOST", "127.0.0.1"))
    args = parser.parse_args(argv)

    try:
        import uvicorn
    except ImportError:
        print("error: uvicorn not installed. Re-run install.sh.", file=sys.stderr)
        return 2

    # Auto-open hook: wait for the server to come up, then launch UI.
    def _opener():
        if args.no_open:
            return
        if not _wait_for_server(args.host, args.port):
            print("warn: server didn't come up in time; not opening UI",
                  file=sys.stderr)
            return
        if args.native:
            proc = _launch_electron(args.host, args.port)
            if proc is None:
                print("warn: --native requested but Electron isn't installed; "
                      "falling back to browser. Re-run install.sh --with-electron.",
                      file=sys.stderr)
                _launch_browser(args.host, args.port)
        else:
            _launch_browser(args.host, args.port)

    threading.Thread(target=_opener, daemon=True).start()

    print(f"[meli-web] serving on http://{args.host}:{args.port}", file=sys.stderr)
    print(f"[meli-web] press Ctrl+C to stop", file=sys.stderr)

    # SIGINT cleanly stops uvicorn.
    try:
        uvicorn.run(
            "meli.webapi.server:app",
            host=args.host,
            port=args.port,
            log_level="warning",
            access_log=False,
        )
    except KeyboardInterrupt:
        pass
    return 0


if __name__ == "__main__":
    sys.exit(main())

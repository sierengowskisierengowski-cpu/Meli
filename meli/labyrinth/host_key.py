"""
SSH host key management for the Labyrinth tarpit.

Generates (or loads an existing) RSA host key and persists it under
~/.local/share/meli/labyrinth/ so the daemon presents a consistent key
across restarts. Attackers who connect twice will not see a changed-key
warning — that would blow the illusion.

The key is 2048-bit RSA (paramiko default). Ed25519 would be more modern
but RSA-2048 is accepted by every scanner vintage we've encountered.

Public API:
    key = load_or_generate_host_key(path: Path | str | None = None)
    # Returns a paramiko.RSAKey ready for transport.add_server_key().
"""
from __future__ import annotations

import os
from pathlib import Path

import structlog

log = structlog.get_logger()

_DEFAULT_DIR_PARTS = (".local", "share", "meli", "labyrinth")
_KEY_FILENAME = "ssh_host_rsa_key"


def _default_key_path() -> Path:
    base = os.environ.get("XDG_DATA_HOME",
                          str(Path.home() / ".local" / "share"))
    return Path(base) / "meli" / "labyrinth" / _KEY_FILENAME


def load_or_generate_host_key(path=None):
    """Return a paramiko.RSAKey, loading from *path* or generating + saving.

    *path* may be a string, Path, or None (uses the XDG data dir default).
    Raises ImportError if paramiko is not installed.
    """
    import paramiko

    key_path = Path(path) if path else _default_key_path()

    if key_path.is_file():
        try:
            key = paramiko.RSAKey(filename=str(key_path))
            log.debug("labyrinth: loaded SSH host key", path=str(key_path))
            return key
        except Exception as e:
            log.warning("labyrinth: failed to load SSH host key — regenerating",
                        path=str(key_path), error=str(e))

    # Generate a new key and persist it.
    key_path.parent.mkdir(parents=True, exist_ok=True)
    key = paramiko.RSAKey.generate(bits=2048)
    try:
        key.write_private_key_file(str(key_path))
        # chmod 600 so only the owner can read it.
        os.chmod(key_path, 0o600)
        log.info("labyrinth: generated new SSH host key", path=str(key_path))
    except Exception as e:
        log.warning("labyrinth: could not persist SSH host key",
                    path=str(key_path), error=str(e))
    return key

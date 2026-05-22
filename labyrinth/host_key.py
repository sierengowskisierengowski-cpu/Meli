"""
SSH host key persistence for the Labyrinth tarpit.

The honeypot needs a stable SSH server identity so:
  * Repeat-visiting botnets see the same fingerprint and don't immediately
    spook (they'd notice a fresh host key on every connection).
  * Operator tooling (your own ssh-keyscan, knownhosts, etc.) can pin
    the trap's identity for monitoring.

The key lives at ~/.local/share/meli/labyrinth/host_rsa_key with 0600
perms — only the meli user can read it. On first start, the daemon
generates a fresh RSA-2048 key and persists it. Subsequent starts
reuse it.

RSA-2048 was chosen over Ed25519 for paramiko compatibility — Ed25519
generation requires the `cryptography` library and additional ceremony.
2048-bit RSA is broadly accepted by every SSH client in the wild
(including the embedded clients used by IoT botnets), and "real boxes"
running OpenSSH still ship RSA host keys by default on most distros.
"""
from __future__ import annotations

import os
from pathlib import Path

import structlog

log = structlog.get_logger()


def default_host_key_path() -> Path:
    """Standard location under XDG data dir. Created lazily on first use."""
    base = os.environ.get("XDG_DATA_HOME", str(Path.home() / ".local" / "share"))
    return Path(base) / "meli" / "labyrinth" / "host_rsa_key"


def load_or_generate_host_key(path: Path | None = None):
    """Return a paramiko PKey — load from disk if present, otherwise
    generate a fresh RSA-2048 key, write it with 0600 perms, return it.

    paramiko is imported lazily so the module can be imported on systems
    where the package isn't installed yet (e.g. CI without ssh deps).
    """
    import paramiko  # local import — paramiko is an opt-in SSH dependency

    path = path or default_host_key_path()
    path.parent.mkdir(parents=True, exist_ok=True)

    if path.exists():
        try:
            return paramiko.RSAKey.from_private_key_file(str(path))
        except Exception as e:
            # Corrupted key — back it up and regenerate. Don't ever
            # silently delete the operator's key file.
            backup = path.with_suffix(path.suffix + ".broken")
            try:
                path.rename(backup)
            except Exception:
                pass
            log.warning("labyrinth host key unreadable — regenerating",
                        path=str(path), backup=str(backup), error=str(e))

    log.info("labyrinth generating new SSH host key (RSA-2048)", path=str(path))
    key = paramiko.RSAKey.generate(2048)
    # Write with restrictive perms BEFORE the key material lands on disk
    # to avoid a window where the file is world-readable.
    fd = os.open(str(path), os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
    try:
        with os.fdopen(fd, "w") as f:
            key.write_private_key(f)
    except Exception:
        # If anything goes wrong, make sure we don't leave a half-written
        # broken key file in place.
        try:
            path.unlink(missing_ok=True)
        except Exception:
            pass
        raise
    return key

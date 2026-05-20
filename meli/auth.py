"""
Meli authentication — master password, 2FA (TOTP + YubiKey), lockout logic.
"""
from __future__ import annotations

import json
import time
import structlog
from pathlib import Path
from dataclasses import dataclass, field
from typing import Optional

from meli.config import get_config
from meli.utils.crypto import hash_password, verify_password

log = structlog.get_logger()

_AUTH_FILE = None  # set on first get_auth_store()

_MAX_ATTEMPTS = 9  # total before app closes
_LOCKOUT_1 = 60    # seconds after 3 fails
_LOCKOUT_2 = 300   # seconds after 6 fails


@dataclass
class AuthState:
    """In-memory auth state for the current session."""
    authenticated: bool = False
    failed_attempts: int = 0
    locked_until: float = 0.0
    last_login: Optional[float] = None
    master_key_cache: Optional[str] = None  # for decrypting api keys within session


def _auth_file() -> Path:
    cfg = get_config()
    return cfg.config_dir / "auth.db"


def _load_auth_store() -> dict:
    p = _auth_file()
    if not p.exists():
        return {}
    try:
        data = json.loads(p.read_bytes())
        return data
    except Exception:
        return {}


def _save_auth_store(data: dict) -> None:
    p = _auth_file()
    p.write_text(json.dumps(data))
    p.chmod(0o600)


def is_setup_complete() -> bool:
    """Return True if the master password has been set."""
    store = _load_auth_store()
    return bool(store.get("password_hash"))


def set_master_password(password: str) -> None:
    """Hash and persist the master password."""
    store = _load_auth_store()
    store["password_hash"] = hash_password(password)
    _save_auth_store(store)
    log.info("Master password set")


def change_master_password(current: str, new_password: str) -> bool:
    """Change master password. Returns True on success."""
    if not verify_master_password(current):
        log.warning("Master password change failed — incorrect current password")
        return False
    set_master_password(new_password)
    log.info("Master password changed")
    return True


def verify_master_password(password: str) -> bool:
    """Verify master password against stored hash."""
    store = _load_auth_store()
    hashed = store.get("password_hash")
    if not hashed:
        return False
    return verify_password(password, hashed)


def setup_totp() -> tuple[str, str]:
    """Generate a new TOTP secret. Returns (secret, otpauth_uri)."""
    import pyotp
    secret = pyotp.random_base32()
    uri = pyotp.totp.TOTP(secret).provisioning_uri(
        name="meli",
        issuer_name="Meli Honeypot Command Center",
    )
    store = _load_auth_store()
    store["totp_secret"] = secret
    store["totp_enabled"] = False  # not enabled until user confirms first code
    _save_auth_store(store)
    return secret, uri


def confirm_totp_setup(code: str) -> bool:
    """Confirm TOTP setup by verifying the first code."""
    import pyotp
    store = _load_auth_store()
    secret = store.get("totp_secret")
    if not secret:
        return False
    totp = pyotp.TOTP(secret)
    if totp.verify(code, valid_window=1):
        store["totp_enabled"] = True
        _save_auth_store(store)
        cfg = get_config()
        cfg.set("auth", "totp_enabled", True)
        log.info("TOTP 2FA enabled")
        return True
    return False


def verify_totp(code: str) -> bool:
    """Verify a TOTP code."""
    import pyotp
    store = _load_auth_store()
    if not store.get("totp_enabled"):
        return True  # 2FA not required
    secret = store.get("totp_secret")
    if not secret:
        return True
    return pyotp.TOTP(secret).verify(code, valid_window=1)


def disable_totp(password: str) -> bool:
    """Disable TOTP after verifying master password."""
    if not verify_master_password(password):
        return False
    store = _load_auth_store()
    store["totp_enabled"] = False
    store.pop("totp_secret", None)
    _save_auth_store(store)
    cfg = get_config()
    cfg.set("auth", "totp_enabled", False)
    log.info("TOTP 2FA disabled")
    return True


def is_totp_enabled() -> bool:
    store = _load_auth_store()
    return bool(store.get("totp_enabled"))


def reset_auth() -> None:
    """Emergency reset — deletes stored auth data."""
    p = _auth_file()
    if p.exists():
        p.unlink()
    log.warning("Auth store reset — master password cleared")


# ── Session state (singleton) ────────────────────────────────────────────────

_session: AuthState = AuthState()


def get_session() -> AuthState:
    return _session


def attempt_login(password: str, totp_code: str = "") -> tuple[bool, str]:
    """
    Try to log in. Returns (success, message).
    Enforces progressive lockouts.
    """
    now = time.time()

    if _session.locked_until > now:
        remaining = int(_session.locked_until - now)
        return False, f"Too many failed attempts. Try again in {remaining}s."

    if _session.failed_attempts >= _MAX_ATTEMPTS:
        log.warning("Max auth attempts reached — session locked")
        return False, "Maximum authentication attempts exceeded. Restart Meli."

    if not verify_master_password(password):
        _session.failed_attempts += 1
        fa = _session.failed_attempts
        log.warning("Failed login attempt", attempts=fa)

        if fa >= 6:
            _session.locked_until = now + _LOCKOUT_2
            return False, f"Too many failures. Locked for {_LOCKOUT_2 // 60} minutes."
        elif fa >= 3:
            _session.locked_until = now + _LOCKOUT_1
            return False, f"Too many failures. Locked for {_LOCKOUT_1}s."

        remaining = _MAX_ATTEMPTS - fa
        return False, f"Incorrect password. {remaining} attempts remaining."

    # Password OK — check 2FA
    if is_totp_enabled():
        if not totp_code:
            return False, "2FA code required."
        if not verify_totp(totp_code):
            _session.failed_attempts += 1
            return False, "Invalid 2FA code."

    # Success
    _session.authenticated = True
    _session.failed_attempts = 0
    _session.locked_until = 0.0
    _session.last_login = now
    _session.master_key_cache = password
    log.info("Login successful")
    return True, "Authenticated."


def lock_session() -> None:
    """Lock the current session (Ctrl+L or idle timeout)."""
    _session.authenticated = False
    _session.master_key_cache = None
    log.info("Session locked")


def is_authenticated() -> bool:
    return _session.authenticated

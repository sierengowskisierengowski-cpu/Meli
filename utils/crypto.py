"""
Encryption utilities for Meli.
API keys and sensitive data are encrypted at rest using Fernet (AES-128-CBC + HMAC-SHA256).
The encryption key is derived from the master password via Argon2id.
"""
from __future__ import annotations

import os
import base64
import struct
import hashlib
from pathlib import Path

from argon2.low_level import hash_secret_raw, Type
from cryptography.fernet import Fernet


_SALT_SIZE = 16
_KEY_SIZE = 32
_ARGON2_TIME_COST = 3
_ARGON2_MEMORY_COST = 65536  # 64 MB
_ARGON2_PARALLELISM = 2


def derive_key(password: str, salt: bytes) -> bytes:
    """Derive a 32-byte key from password + salt using Argon2id."""
    raw = hash_secret_raw(
        secret=password.encode(),
        salt=salt,
        time_cost=_ARGON2_TIME_COST,
        memory_cost=_ARGON2_MEMORY_COST,
        parallelism=_ARGON2_PARALLELISM,
        hash_len=_KEY_SIZE,
        type=Type.ID,
    )
    # Fernet requires a URL-safe base64-encoded 32-byte key
    return base64.urlsafe_b64encode(raw)


def encrypt(plaintext: str, password: str, salt: bytes | None = None) -> bytes:
    """Encrypt plaintext string. Returns salt + ciphertext (binary)."""
    if salt is None:
        salt = os.urandom(_SALT_SIZE)
    key = derive_key(password, salt)
    f = Fernet(key)
    ct = f.encrypt(plaintext.encode())
    return salt + ct


def decrypt(blob: bytes, password: str) -> str:
    """Decrypt blob produced by encrypt(). Returns plaintext string."""
    salt = blob[:_SALT_SIZE]
    ct = blob[_SALT_SIZE:]
    key = derive_key(password, salt)
    f = Fernet(key)
    return f.decrypt(ct).decode()


def encrypt_to_file(path: Path, plaintext: str, password: str) -> None:
    """Encrypt and write to file with 0600 permissions."""
    blob = encrypt(plaintext, password)
    path.write_bytes(blob)
    path.chmod(0o600)


def decrypt_from_file(path: Path, password: str) -> str:
    """Read encrypted file and decrypt."""
    blob = path.read_bytes()
    return decrypt(blob, password)


def hash_password(password: str) -> str:
    """Hash password using bcrypt for storage."""
    import bcrypt
    return bcrypt.hashpw(password.encode(), bcrypt.gensalt(rounds=12)).decode()


def verify_password(password: str, hashed: str) -> bool:
    """Verify password against bcrypt hash."""
    import bcrypt
    try:
        return bcrypt.checkpw(password.encode(), hashed.encode())
    except Exception:
        return False

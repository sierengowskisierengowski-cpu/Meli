"""
EULA / Authorization acknowledgment tracking.

Persists the operator's acknowledgment of DISCLAIMER.md to
~/.config/meli/eula.json so the setup wizard's Authorization step
only has to be completed once per install.
"""
from __future__ import annotations

import json
import os
from datetime import datetime, timezone
from pathlib import Path


def _eula_path() -> Path:
    base = Path(os.environ.get(
        "MELI_CONFIG_DIR",
        Path.home() / ".config" / "meli",
    ))
    base.mkdir(parents=True, exist_ok=True)
    return base / "eula.json"


def is_accepted() -> bool:
    p = _eula_path()
    if not p.is_file():
        return False
    try:
        return bool(json.loads(p.read_text()).get("accepted"))
    except Exception:
        return False


def accept(version: str = "2.3.0") -> dict:
    """Mark the disclaimer as accepted; return the record written."""
    record = {
        "accepted": True,
        "accepted_at": datetime.now(timezone.utc).isoformat(),
        "version": version,
        "user": os.environ.get("USER", "unknown"),
        "host": os.uname().nodename if hasattr(os, "uname") else "unknown",
    }
    p = _eula_path()
    p.write_text(json.dumps(record, indent=2))
    try:
        p.chmod(0o600)
    except Exception:
        pass
    return record


def get_record() -> dict | None:
    p = _eula_path()
    if not p.is_file():
        return None
    try:
        return json.loads(p.read_text())
    except Exception:
        return None

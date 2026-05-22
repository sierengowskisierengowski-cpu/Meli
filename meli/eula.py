"""
EULA / Authorization acknowledgment tracking.

Persists the operator's acknowledgment of DISCLAIMER.md to
~/.config/meli/eula.json so the setup wizard's Authorization step
only has to be completed once per install — until the disclaimer
revision bumps, at which point the operator is re-prompted.

Versioning is intentionally on the *disclaimer revision*, not the
app version: a 2.3.0 → 2.3.1 patch release with no disclaimer
change must NOT re-prompt; a 2.3.0 → 2.4.0 release that materially
changes operator obligations should bump DISCLAIMER_REVISION below.
"""
from __future__ import annotations

import json
import os
from datetime import datetime, timezone
from pathlib import Path

# Bump this when DISCLAIMER.md changes in a way that needs a fresh
# operator acknowledgment. Keep the suffix human-readable so the
# value in eula.json is self-documenting.
DISCLAIMER_REVISION = "2.3.0-initial"


def _eula_path() -> Path:
    base = Path(os.environ.get(
        "MELI_CONFIG_DIR",
        Path.home() / ".config" / "meli",
    ))
    base.mkdir(parents=True, exist_ok=True)
    return base / "eula.json"


def _read() -> dict | None:
    p = _eula_path()
    if not p.is_file():
        return None
    try:
        return json.loads(p.read_text())
    except Exception:
        return None


def get_record() -> dict | None:
    return _read()


def is_accepted(revision: str | None = None) -> bool:
    """True iff a prior acceptance exists AND its disclaimer revision
    matches the current one (or the caller-supplied `revision`).

    Passing `revision=None` checks against the current
    `DISCLAIMER_REVISION`. Passing an explicit value is mostly for
    tests / migration tooling.
    """
    rec = _read()
    if not rec or not rec.get("accepted"):
        return False
    want = revision if revision is not None else DISCLAIMER_REVISION
    return rec.get("disclaimer_revision") == want


def accept(app_version: str | None = None,
           disclaimer_revision: str | None = None) -> dict:
    """Mark the disclaimer as accepted; return the record written.

    `app_version` and `disclaimer_revision` default to the runtime
    values so callers can usually just `accept()`. Both are stored
    verbatim so future audits can answer "which release was running
    when this operator agreed?".
    """
    if app_version is None:
        try:
            from meli import __version__ as app_version  # local import to avoid cycles at module load
        except Exception:
            app_version = "unknown"
    if disclaimer_revision is None:
        disclaimer_revision = DISCLAIMER_REVISION

    record = {
        "accepted": True,
        "accepted_at": datetime.now(timezone.utc).isoformat(),
        "app_version": app_version,
        "disclaimer_revision": disclaimer_revision,
        # Kept for backwards-compatibility with the v2.3.0 schema
        # that used a single "version" key.
        "version": app_version,
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

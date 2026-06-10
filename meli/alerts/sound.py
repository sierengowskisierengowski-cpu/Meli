"""Sound alerts for Meli using GStreamer (via PyGObject) or aplay fallback."""
from __future__ import annotations

import subprocess
import structlog
from pathlib import Path

from meli.config import get_config

log = structlog.get_logger()

_SOUND_DIR = Path(__file__).parent.parent.parent / "assets" / "sounds"

_SEVERITY_SOUNDS = {
    "INFO": None,
    "LOW": "alert-low.ogg",
    "MEDIUM": "alert-medium.ogg",
    "HIGH": "alert-high.ogg",
    "CRITICAL": "alert-critical.ogg",
}


def play_alert_sound(severity: str) -> None:
    cfg = get_config()
    if not cfg.get("alerts", "sound_enabled", default=True):
        return

    per_severity = cfg.get("alerts", "per_severity_sounds", default={})
    filename = per_severity.get(severity.upper()) or _SEVERITY_SOUNDS.get(severity.upper())
    if not filename:
        return

    sound_file = _SOUND_DIR / filename
    if not sound_file.exists():
        log.debug("Sound file not found", path=str(sound_file))
        return

    # Try GStreamer first, then fall back to aplay/paplay
    _play_file(str(sound_file))


def _play_file(path: str) -> None:
    for cmd in [
        ["paplay", path],
        ["aplay", path],
        ["ffplay", "-nodisp", "-autoexit", "-loglevel", "quiet", path],
    ]:
        try:
            subprocess.Popen(cmd, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
            return
        except FileNotFoundError:
            continue
    log.debug("No audio player available for alert sounds")

"""
LABYRINTH ATRIUM — full-screen kiosk display for Meli.

Designed to live on a wall-mounted monitor attached to a Raspberry Pi
(or any always-on machine) running the honeypot. It turns the boring
"daemon is happily running headless" state into a cinema-grade live
intel display you can leave up 24/7. Three big purposes:

  1. Situational awareness at a glance — anyone walking past can see
     whether the trap is empty, busy, or under siege, and roughly
     where the attacks are coming from.
  2. A pleasant, alive ambience — slow gradient aurora, soft tick on
     each session open, rare amber pulse on the pot. Boring is good
     when nothing is happening; nothing is more alarming than the
     room going red when something does.
  3. A demo / conversation piece. It looks badass on purpose.

Layout (fullscreen, 1920x1080 target — scales gracefully to any size):

  ┌──────────────────────────────────────────────────────────────┐
  │ ▓ MELI · LABYRINTH ATRIUM    14:03:17 UTC    ● LIVE  N=4823  │   <- ClockBar
  ├──────────────┬────────────────────────┬──────────────────────┤
  │              │                        │  >>> SESSION 0x7f3a  │
  │   RADAR      │   HONEY POT (3× scale) │      [203.0.113.42]  │
  │   SCOPE      │   (centerpiece)        │  AUTH root:admin →   │
  │              │                        │      DENIED          │
  │  ◯ ◯ ◯ ◯    │   pulses + drips on    │  EXEC "cat passwd"   │   <- TerminalStream
  │   ╲ │ ╱      │   each new event       │  !!! CANARY [HIGH]   │
  │   sweep      │                        │  <<< CLOSED 45s 23c  │
  │              │                        │                      │
  ├──────────────┴────────────────────────┴──────────────────────┤
  │ ▂▃▄▅▆▇█  24-HOUR ATTACK INTENSITY (15-min bins)  █▇▆▅▄▃▂    │   <- HeatmapBar
  └──────────────────────────────────────────────────────────────┘

The whole thing is one Adw.ApplicationWindow with no decorations,
content set to an AtriumScene (Gtk.Overlay) that stacks:
  - aurora gradient background (drawing area, 5fps)
  - main grid (radar + pot + terminal + heatmap)
  - canary-trip flash overlay (red full-screen pulse on CANARY events)
  - CRT scanline overlay (subtle horizontal lines, static)

Exits via Esc / F11 / Ctrl+W / clicking any corner. The mouse cursor
auto-hides after 3s of idle so the display looks clean from across
the room.

Subscribes to `event_bus.event.ingested` (plus polls the Labyrinth
sticky roster + the events DB for session lifecycle data) and
re-dispatches to GTK via GLib.idle_add — the main loop is never
blocked by ingest pipeline activity.
"""
from __future__ import annotations

import gi
gi.require_version("Gtk", "4.0")
gi.require_version("Adw", "1")
from gi.repository import Gtk, Adw, GLib, Gdk, Gio  # noqa: E402

import cairo  # noqa: E402

import hashlib
import math
import os
import random
import struct
import subprocess
import threading
import time
import wave
from collections import deque
from datetime import datetime, timezone, timedelta
from pathlib import Path

import structlog

from meli import event_bus
from meli.config import get_config
from meli.ui.widgets import HoneyPotWidget

log = structlog.get_logger()

# ── Palette (kept in sync with style.css honey theme) ────────────────
HIVE_BLACK     = (0x05/255, 0x03/255, 0x02/255)
DEEP_AMBER     = (0x1a/255, 0x0d/255, 0x04/255)
RAW_HONEY      = (0xd4/255, 0xa0/255, 0x17/255)
AMBER_GLOW     = (0xf5/255, 0x9e/255, 0x0b/255)
PALE_COMB      = (0xfe/255, 0xf3/255, 0xc7/255)
STING_RED      = (0xdc/255, 0x26/255, 0x26/255)
PHOSPHOR_GREEN = (0x6a/255, 0xe2/255, 0x7a/255)
SCAN_BLUE      = (0x4f/255, 0xa3/255, 0xff/255)
ALERT_ORANGE   = (0xff/255, 0x8a/255, 0x3a/255)
DIM_WHITE      = (0xc8/255, 0xc0/255, 0xb0/255)

# Frame rates — Pi5 is plenty for 30 fps everywhere, but the aurora
# and heatmap don't need it. Lower FPS = less CPU = quieter fan.
FPS_RADAR    = 30
FPS_TERMINAL = 30
FPS_AURORA   = 5
FPS_HEATMAP  = 1
FPS_CLOCK    = 4

CURSOR_HIDE_SECONDS = 3.0


# ─────────────────────────────────────────────────────────────────────
# AUDIO
# ─────────────────────────────────────────────────────────────────────
# We synthesize the four cue WAVs from sine waves at first use so the
# repo doesn't have to ship binary audio assets. They live under the
# user data dir (~/.local/share/meli/sounds/atrium/) and are regenerated
# only if missing — users can drop in their own .wav files with the
# same name to override.

_ATRIUM_SOUND_DIR_CACHE: Path | None = None


def _atrium_sound_dir() -> Path:
    """Where the synthesized atrium cue WAVs live."""
    global _ATRIUM_SOUND_DIR_CACHE
    if _ATRIUM_SOUND_DIR_CACHE is not None:
        return _ATRIUM_SOUND_DIR_CACHE
    base = Path(os.environ.get("MELI_DATA_DIR",
                Path.home() / ".local" / "share" / "meli"))
    d = base / "sounds" / "atrium"
    d.mkdir(parents=True, exist_ok=True)
    _ATRIUM_SOUND_DIR_CACHE = d
    return d


def _synth_wav(path: Path, *, freqs: list[tuple[float, float]],
               duration: float, sample_rate: int = 44100,
               envelope: str = "ad", peak: float = 0.35) -> None:
    """Write a mono 16-bit PCM WAV that mixes the given (freq_hz, weight)
    pairs over `duration` seconds. `envelope` is "ad" (attack/decay,
    plucked feel), "pad" (slow rise + slow fall), or "flat".

    Kept stdlib-only (wave + math + struct) so the kiosk works on
    minimal installs without pulling pydub or numpy."""
    n_samples = int(sample_rate * duration)
    total_w = sum(w for _, w in freqs) or 1.0
    out = bytearray()
    for i in range(n_samples):
        t = i / sample_rate
        if envelope == "ad":
            # 3ms attack, exponential decay across the rest
            atk = min(1.0, t / 0.003)
            dec = math.exp(-3.5 * t / duration)
            env = atk * dec
        elif envelope == "pad":
            # Quarter-second rise, hold, quarter-second fall
            rise = min(1.0, t / 0.25)
            fall = min(1.0, (duration - t) / 0.25)
            env = rise * fall
        else:
            env = 1.0
        val = 0.0
        for f, w in freqs:
            val += w * math.sin(2 * math.pi * f * t)
        val = (val / total_w) * env * peak
        # Clip & convert to int16
        val = max(-1.0, min(1.0, val))
        out += struct.pack("<h", int(val * 32767))
    with wave.open(str(path), "wb") as w:
        w.setnchannels(1)
        w.setsampwidth(2)
        w.setframerate(sample_rate)
        w.writeframes(bytes(out))


# Cue catalog: (filename, synth args). We rebuild only the missing ones.
_CUE_SPECS: dict[str, dict] = {
    # Soft warm tick when a new attacker engages — barely audible.
    "session_open": dict(
        freqs=[(620.0, 1.0), (940.0, 0.4)],
        duration=0.18, envelope="ad", peak=0.22,
    ),
    # Quieter tick when an attacker hangs up.
    "session_close": dict(
        freqs=[(380.0, 1.0), (220.0, 0.5)],
        duration=0.16, envelope="ad", peak=0.18,
    ),
    # A muted dud for failed login attempts (very brief, dry).
    "login_fail": dict(
        freqs=[(180.0, 1.0)],
        duration=0.07, envelope="ad", peak=0.14,
    ),
    # The big one — a dramatic two-tone alarm for canary trips.
    "canary_trip": dict(
        freqs=[(880.0, 1.0), (587.0, 0.8), (1320.0, 0.4)],
        duration=0.85, envelope="pad", peak=0.55,
    ),
}


def _ensure_cues() -> dict[str, Path]:
    """Create any missing cue WAVs, return name → path mapping."""
    out = {}
    d = _atrium_sound_dir()
    for name, spec in _CUE_SPECS.items():
        p = d / f"{name}.wav"
        if not p.is_file():
            try:
                _synth_wav(p, **spec)
                log.info("atrium cue synthesized", name=name, path=str(p))
            except Exception as e:
                log.warning("atrium cue synth failed", name=name, error=str(e))
                continue
        out[name] = p
    return out


_PLAYER_CMDS = [
    ["paplay"],
    ["pw-play"],
    ["aplay", "-q"],
    ["ffplay", "-nodisp", "-autoexit", "-loglevel", "quiet"],
]


def _play_async(path: Path, volume: float = 1.0) -> None:
    """Fire-and-forget audio playback. Volume is best-effort —
    paplay supports --volume, others don't (we just don't play
    those that don't support volume when volume is very low)."""
    if not path.is_file():
        return
    vol = max(0.0, min(1.0, volume))
    if vol < 0.02:
        return
    for cmd in _PLAYER_CMDS:
        try:
            args = list(cmd)
            if cmd[0] == "paplay":
                # paplay --volume range is 0..65536
                args += ["--volume", str(int(vol * 65536))]
            args.append(str(path))
            subprocess.Popen(args,
                             stdout=subprocess.DEVNULL,
                             stderr=subprocess.DEVNULL,
                             stdin=subprocess.DEVNULL)
            return
        except FileNotFoundError:
            continue
        except Exception as e:
            log.debug("atrium audio launch failed", cmd=cmd[0], error=str(e))
            continue


class AtriumAudio:
    """Cached cue lookup + per-cue cooldown so a flood of events can't
    machine-gun the speakers."""

    def __init__(self):
        self._cues = _ensure_cues()
        self._last_played: dict[str, float] = {}
        # Min seconds between successive plays of the same cue.
        self._cooldown = {
            "session_open":  0.6,
            "session_close": 0.6,
            "login_fail":    0.25,
            "canary_trip":   0.4,
        }

    def play(self, name: str, volume: float = 1.0) -> None:
        path = self._cues.get(name)
        if path is None:
            return
        now = time.monotonic()
        last = self._last_played.get(name, 0.0)
        if now - last < self._cooldown.get(name, 0.3):
            return
        self._last_played[name] = now
        _play_async(path, volume)


# ─────────────────────────────────────────────────────────────────────
# AURORA BACKGROUND
# ─────────────────────────────────────────────────────────────────────
# Slow drifting radial gradients on a near-black base. 5 fps is plenty
# — anything faster is wasted because the eye can't see it.

class AuroraBackground(Gtk.DrawingArea):
    def __init__(self):
        super().__init__()
        self._phase = random.random() * math.tau
        self._closing = False
        self._timeouts: list[int] = []
        self.set_draw_func(self._draw)
        self._timeouts.append(
            GLib.timeout_add(int(1000 / FPS_AURORA), self._tick))

    def shutdown(self) -> None:
        self._closing = True
        for t in self._timeouts:
            try: GLib.source_remove(t)
            except Exception: pass
        self._timeouts.clear()

    def _tick(self) -> bool:
        if self._closing:
            return False
        # ~28-second cycle, matches the GodsApp aurora cadence
        self._phase = (self._phase + (math.tau / (FPS_AURORA * 28))) % math.tau
        self.queue_draw()
        return True

    def _draw(self, area, cr: cairo.Context, w: int, h: int) -> None:
        # Solid hive-black base
        cr.set_source_rgb(*HIVE_BLACK)
        cr.paint()
        # Three slow blooms drifting along Lissajous-ish paths
        blooms = [
            (RAW_HONEY,   0.04, 0.30 + 0.18 * math.sin(self._phase),
                                 0.45 + 0.22 * math.cos(self._phase * 0.7)),
            (AMBER_GLOW,  0.035, 0.70 + 0.22 * math.cos(self._phase * 1.1),
                                 0.55 + 0.18 * math.sin(self._phase * 1.3)),
            (STING_RED,   0.025, 0.50 + 0.28 * math.sin(self._phase * 0.5 + 1.2),
                                 0.20 + 0.15 * math.cos(self._phase * 0.9)),
        ]
        for color, alpha, fx, fy in blooms:
            cx, cy = fx * w, fy * h
            r = max(w, h) * 0.55
            grad = cairo.RadialGradient(cx, cy, 0, cx, cy, r)
            grad.add_color_stop_rgba(0.0, *color, alpha)
            grad.add_color_stop_rgba(1.0, *color, 0)
            cr.set_source(grad)
            cr.paint()


# ─────────────────────────────────────────────────────────────────────
# RADAR SCOPE
# ─────────────────────────────────────────────────────────────────────
# A circular polar display with range rings, bearing tickmarks, a
# rotating sweep line (3s per rev), and persistent attacker blips that
# fade over ~12s. New events placed at polar coords derived from a
# stable hash of the source IP — so the same attacker always lands in
# the same spot, and the display has spatial memory.
#
# Center icon: small amphora silhouette ("us"). Color of the blip
# encodes severity: INFO=phosphor green, HIGH=amber, CRITICAL=red.

class _Blip:
    __slots__ = ("angle", "radius_frac", "color", "born", "lifetime", "label")

    def __init__(self, angle, radius_frac, color, lifetime, label):
        self.angle = angle
        self.radius_frac = radius_frac
        self.color = color
        self.born = time.monotonic()
        self.lifetime = lifetime
        self.label = label

    def age(self) -> float:
        return (time.monotonic() - self.born) / self.lifetime

    def alive(self) -> bool:
        return self.age() < 1.0


class RadarScope(Gtk.DrawingArea):
    def __init__(self):
        super().__init__()
        self.set_hexpand(True)
        self.set_vexpand(True)
        self._sweep_angle = 0.0
        self._blips: deque[_Blip] = deque(maxlen=120)
        self._last_frame = time.monotonic()
        self._closing = False
        self._timeouts: list[int] = []
        self.set_draw_func(self._draw)
        self._timeouts.append(
            GLib.timeout_add(int(1000 / FPS_RADAR), self._tick))

    def shutdown(self) -> None:
        self._closing = True
        for t in self._timeouts:
            try: GLib.source_remove(t)
            except Exception: pass
        self._timeouts.clear()

    def add_event(self, source_ip: str, severity: str = "INFO",
                  label: str = "") -> None:
        """Place a new blip on the scope. Stable polar coords from
        the IP hash so repeat offenders land in the same spot."""
        h = hashlib.sha256(source_ip.encode("utf-8", errors="ignore")).digest()
        # 16-bit angle, 8-bit radius
        ang16 = (h[0] << 8) | h[1]
        rad8 = h[2]
        angle = (ang16 / 65535.0) * math.tau
        # Radius 0.25..0.95 of scope — never dead center, never edge
        radius_frac = 0.25 + (rad8 / 255.0) * 0.70
        sev = (severity or "INFO").upper()
        if sev == "CRITICAL":
            color, lifetime = STING_RED, 18.0
        elif sev == "HIGH":
            color, lifetime = ALERT_ORANGE, 14.0
        elif sev == "MEDIUM":
            color, lifetime = AMBER_GLOW, 12.0
        else:
            color, lifetime = PHOSPHOR_GREEN, 10.0
        self._blips.append(_Blip(angle, radius_frac, color, lifetime,
                                 label or source_ip))

    def _tick(self) -> bool:
        if self._closing:
            return False
        now = time.monotonic()
        dt = now - self._last_frame
        self._last_frame = now
        # ~3 seconds per revolution
        self._sweep_angle = (self._sweep_angle + dt * (math.tau / 3.0)) % math.tau
        # Drop dead blips
        while self._blips and not self._blips[0].alive():
            self._blips.popleft()
        self.queue_draw()
        return True

    def _draw(self, area, cr: cairo.Context, w: int, h: int) -> None:
        cx, cy = w / 2, h / 2
        R = min(w, h) * 0.46

        # Background disk
        cr.set_source_rgba(0.03, 0.05, 0.03, 0.55)
        cr.arc(cx, cy, R + 8, 0, math.tau)
        cr.fill()

        # Range rings (4 concentric)
        cr.set_source_rgba(*PHOSPHOR_GREEN, 0.22)
        cr.set_line_width(1.0)
        for i in range(1, 5):
            cr.arc(cx, cy, R * i / 4, 0, math.tau)
            cr.stroke()

        # Bearing tickmarks every 15°, longer at cardinal points
        for deg in range(0, 360, 15):
            a = math.radians(deg - 90)
            is_cardinal = (deg % 90 == 0)
            inner = R * (0.93 if is_cardinal else 0.96)
            cr.set_source_rgba(*PHOSPHOR_GREEN,
                               0.45 if is_cardinal else 0.20)
            cr.set_line_width(1.5 if is_cardinal else 0.8)
            cr.move_to(cx + math.cos(a) * inner, cy + math.sin(a) * inner)
            cr.line_to(cx + math.cos(a) * R,     cy + math.sin(a) * R)
            cr.stroke()

        # Cardinal labels
        cr.set_source_rgba(*PHOSPHOR_GREEN, 0.85)
        cr.select_font_face("Monospace", cairo.FONT_SLANT_NORMAL,
                            cairo.FONT_WEIGHT_BOLD)
        cr.set_font_size(13)
        labels = [("N", 0), ("E", 90), ("S", 180), ("W", 270)]
        for letter, deg in labels:
            a = math.radians(deg - 90)
            x = cx + math.cos(a) * (R + 14)
            y = cy + math.sin(a) * (R + 14)
            ex = cr.text_extents(letter)
            cr.move_to(x - ex.width / 2, y + ex.height / 2)
            cr.show_text(letter)

        # Sweep wedge (10° wide, fading trail behind)
        wedge_width = math.radians(28)
        for i in range(14):
            frac = i / 14
            a_end = self._sweep_angle - frac * wedge_width
            a_start = a_end - (math.tau / 360)  # 1° slice
            alpha = 0.40 * (1.0 - frac) ** 1.4
            cr.set_source_rgba(*PHOSPHOR_GREEN, alpha)
            cr.move_to(cx, cy)
            cr.arc(cx, cy, R, a_start - math.pi / 2, a_end - math.pi / 2)
            cr.close_path()
            cr.fill()

        # Leading sweep line (bright)
        cr.set_source_rgba(*PHOSPHOR_GREEN, 0.95)
        cr.set_line_width(1.6)
        a = self._sweep_angle - math.pi / 2
        cr.move_to(cx, cy)
        cr.line_to(cx + math.cos(a) * R, cy + math.sin(a) * R)
        cr.stroke()

        # Blips — fade from full → dim, glow halo around fresh ones
        now_blips = list(self._blips)
        for b in now_blips:
            age = b.age()
            if age >= 1.0:
                continue
            bx = cx + math.cos(b.angle) * R * b.radius_frac
            by = cy + math.sin(b.angle) * R * b.radius_frac
            alpha = (1.0 - age) ** 0.6
            # Glow
            if age < 0.3:
                glow_a = (1.0 - age / 0.3) * 0.6
                grad = cairo.RadialGradient(bx, by, 0, bx, by, 22)
                grad.add_color_stop_rgba(0, *b.color, glow_a)
                grad.add_color_stop_rgba(1, *b.color, 0)
                cr.set_source(grad)
                cr.arc(bx, by, 22, 0, math.tau)
                cr.fill()
            # Core dot
            cr.set_source_rgba(*b.color, alpha)
            cr.arc(bx, by, 3.5 + (1.0 - age) * 1.5, 0, math.tau)
            cr.fill()

        # Center "us" mark — small amphora silhouette
        cr.set_source_rgb(*RAW_HONEY)
        cr.arc(cx, cy, 4.5, 0, math.tau)
        cr.fill()
        cr.set_source_rgba(*RAW_HONEY, 0.45)
        cr.arc(cx, cy, 9, 0, math.tau)
        cr.stroke()

        # Scope frame
        cr.set_source_rgba(*RAW_HONEY, 0.7)
        cr.set_line_width(2.0)
        cr.arc(cx, cy, R + 8, 0, math.tau)
        cr.stroke()

        # Footer label
        cr.set_source_rgba(*PHOSPHOR_GREEN, 0.85)
        cr.select_font_face("Monospace", cairo.FONT_SLANT_NORMAL,
                            cairo.FONT_WEIGHT_BOLD)
        cr.set_font_size(12)
        label = f"SCOPE   {len(now_blips):3d} active"
        ex = cr.text_extents(label)
        cr.move_to(cx - ex.width / 2, cy + R + 36)
        cr.show_text(label)


# ─────────────────────────────────────────────────────────────────────
# TERMINAL STREAM
# ─────────────────────────────────────────────────────────────────────
# A scrolling colored log on a near-black background. Phosphor glow on
# text. CRT scanline overlay on top. New lines push from the bottom;
# old lines fade out as they reach the top.

# Line "kind" → color
_TERM_COLORS = {
    "session_open":  PHOSPHOR_GREEN,
    "session_close": DIM_WHITE,
    "auth_fail":     AMBER_GLOW,
    "auth_ok":       ALERT_ORANGE,
    "command":       PALE_COMB,
    "canary":        STING_RED,
    "system":        SCAN_BLUE,
    "info":          DIM_WHITE,
}


class _TermLine:
    __slots__ = ("text", "color", "born", "kind")

    def __init__(self, text: str, color: tuple, kind: str):
        self.text = text
        self.color = color
        self.born = time.monotonic()
        self.kind = kind


class TerminalStream(Gtk.DrawingArea):
    MAX_LINES = 60
    FONT_SIZE = 14
    LINE_HEIGHT = 20

    def __init__(self):
        super().__init__()
        self.set_hexpand(True)
        self.set_vexpand(True)
        self._lines: deque[_TermLine] = deque(maxlen=self.MAX_LINES)
        self._scanline_phase = 0.0
        self._closing = False
        self._timeouts: list[int] = []
        self.set_draw_func(self._draw)
        self._timeouts.append(
            GLib.timeout_add(int(1000 / FPS_TERMINAL), self._tick))
        # Banner on launch
        self.push("LABYRINTH ATRIUM v1.0   READY", kind="system")
        self.push("subscribing to event stream...", kind="info")

    def shutdown(self) -> None:
        self._closing = True
        for t in self._timeouts:
            try: GLib.source_remove(t)
            except Exception: pass
        self._timeouts.clear()

    def push(self, text: str, kind: str = "info") -> None:
        color = _TERM_COLORS.get(kind, DIM_WHITE)
        # Timestamp prefix
        ts = datetime.now(timezone.utc).strftime("%H:%M:%S")
        self._lines.append(_TermLine(f"{ts}  {text}", color, kind))

    def _tick(self) -> bool:
        self._scanline_phase += 0.015
        self.queue_draw()
        return True

    def _draw(self, area, cr: cairo.Context, w: int, h: int) -> None:
        # Background — slightly translucent so the aurora bleeds through
        cr.set_source_rgba(0.02, 0.025, 0.02, 0.78)
        cr.rectangle(0, 0, w, h)
        cr.fill()

        # Phosphor border
        cr.set_source_rgba(*PHOSPHOR_GREEN, 0.35)
        cr.set_line_width(1.2)
        cr.rectangle(0.5, 0.5, w - 1, h - 1)
        cr.stroke()

        # Caption strip
        cr.set_source_rgba(*PHOSPHOR_GREEN, 0.85)
        cr.select_font_face("Monospace", cairo.FONT_SLANT_NORMAL,
                            cairo.FONT_WEIGHT_BOLD)
        cr.set_font_size(12)
        cap = "EVENT STREAM"
        cr.move_to(12, 18)
        cr.show_text(cap)
        cr.set_source_rgba(*PHOSPHOR_GREEN, 0.4)
        cr.move_to(12, 22)
        cr.line_to(w - 12, 22)
        cr.set_line_width(0.8)
        cr.stroke()

        # Render lines bottom-up. Newer = closer to bottom.
        cr.select_font_face("Monospace", cairo.FONT_SLANT_NORMAL,
                            cairo.FONT_WEIGHT_NORMAL)
        cr.set_font_size(self.FONT_SIZE)
        max_visible = max(1, int((h - 40) / self.LINE_HEIGHT))
        visible = list(self._lines)[-max_visible:]
        n = len(visible)
        for idx, line in enumerate(visible):
            # Top line (oldest visible) at row 0, newest at row n-1
            y = h - 14 - (n - 1 - idx) * self.LINE_HEIGHT
            # Fade older lines toward the top of the visible window
            depth = (n - 1 - idx) / max(1, n - 1)
            alpha = 1.0 - depth * 0.55
            # Glow underlay for "fresh" lines (< 1.5s old)
            age = time.monotonic() - line.born
            if age < 1.2:
                glow = (1.0 - age / 1.2) * 0.55
                cr.set_source_rgba(*line.color, glow * 0.25)
                cr.set_font_size(self.FONT_SIZE + 1)
                cr.move_to(12 - 0.5, y + 0.5)
                cr.show_text(line.text)
                cr.set_font_size(self.FONT_SIZE)
            cr.set_source_rgba(*line.color, alpha)
            cr.move_to(12, y)
            cr.show_text(line.text)

        # CRT scanlines (subtle horizontal striping)
        cr.set_source_rgba(0, 0, 0, 0.16)
        for y in range(0, h, 3):
            cr.rectangle(0, y, w, 1)
        cr.fill()

        # Vignette
        grad = cairo.RadialGradient(w / 2, h / 2, min(w, h) * 0.3,
                                    w / 2, h / 2, max(w, h) * 0.75)
        grad.add_color_stop_rgba(0, 0, 0, 0, 0)
        grad.add_color_stop_rgba(1, 0, 0, 0, 0.35)
        cr.set_source(grad)
        cr.rectangle(0, 0, w, h)
        cr.fill()


# ─────────────────────────────────────────────────────────────────────
# HEATMAP BAR
# ─────────────────────────────────────────────────────────────────────
# 96 bars across the bottom = last 24 hours in 15-minute bins. Height
# log-scaled so a quiet stretch is still readable next to a noisy one.
# Refreshed every minute from a background DB query.

class HeatmapBar(Gtk.DrawingArea):
    BINS = 96  # 24h × 4 bins/h

    def __init__(self):
        super().__init__()
        self.set_hexpand(True)
        self.set_content_height(90)
        self._counts = [0] * self.BINS
        self._max = 1
        self._inflight = False
        self._closing = False
        self._timeouts: list[int] = []
        self.set_draw_func(self._draw)
        # Refresh now, then every 60s
        GLib.idle_add(self._refresh_async)
        self._timeouts.append(
            GLib.timeout_add(60_000, lambda: (self._refresh_async() or True)))
        self._timeouts.append(
            GLib.timeout_add(int(1000 / FPS_HEATMAP), self._tick))

    def shutdown(self) -> None:
        self._closing = True
        for t in self._timeouts:
            try: GLib.source_remove(t)
            except Exception: pass
        self._timeouts.clear()

    def _tick(self) -> bool:
        if self._closing:
            return False
        self.queue_draw()
        return True

    def _refresh_async(self) -> bool:
        if self._inflight or self._closing:
            return False
        self._inflight = True

        def _work():
            counts = self._fetch_counts()
            GLib.idle_add(self._apply, counts)

        threading.Thread(target=_work, name="atrium-heatmap-fetch",
                         daemon=True).start()
        return False

    def _fetch_counts(self) -> list[int]:
        """Query the events DB for the last 24h, binned 15min."""
        try:
            from meli.database import get_session
            from meli.database.models import Event
            from sqlalchemy import select, func
        except Exception:
            return [0] * self.BINS
        bins = [0] * self.BINS
        cutoff = datetime.now(timezone.utc) - timedelta(hours=24)
        try:
            with get_session() as s:
                stmt = select(Event.timestamp).where(Event.timestamp >= cutoff)
                for (ts,) in s.execute(stmt):
                    if ts is None:
                        continue
                    # Make ts UTC-aware
                    if ts.tzinfo is None:
                        ts = ts.replace(tzinfo=timezone.utc)
                    delta = datetime.now(timezone.utc) - ts
                    minutes_ago = int(delta.total_seconds() // 60)
                    if 0 <= minutes_ago < 1440:
                        # Newest bin is rightmost (index BINS-1)
                        bin_idx = self.BINS - 1 - (minutes_ago // 15)
                        if 0 <= bin_idx < self.BINS:
                            bins[bin_idx] += 1
        except Exception as e:
            log.debug("atrium heatmap fetch failed", error=str(e))
        return bins

    def _apply(self, counts) -> bool:
        self._inflight = False
        if self._closing:
            return False
        self._counts = counts
        self._max = max(1, max(counts) if counts else 1)
        return False

    def _draw(self, area, cr: cairo.Context, w: int, h: int) -> None:
        cr.set_source_rgba(0.02, 0.02, 0.02, 0.65)
        cr.rectangle(0, 0, w, h)
        cr.fill()

        # Border
        cr.set_source_rgba(*RAW_HONEY, 0.6)
        cr.set_line_width(1.2)
        cr.rectangle(0.5, 0.5, w - 1, h - 1)
        cr.stroke()

        # Caption
        cr.set_source_rgba(*PALE_COMB, 0.9)
        cr.select_font_face("Monospace", cairo.FONT_SLANT_NORMAL,
                            cairo.FONT_WEIGHT_BOLD)
        cr.set_font_size(11)
        total = sum(self._counts)
        peak = max(self._counts) if self._counts else 0
        caption = f"24H ATTACK INTENSITY · {total:,} events · peak {peak}/15min"
        cr.move_to(12, 16)
        cr.show_text(caption)

        # Bars
        bar_top = 24
        bar_zone_h = h - bar_top - 14
        gap = 1.0
        bar_w = (w - 16 - (self.BINS - 1) * gap) / self.BINS
        for i, c in enumerate(self._counts):
            # Log-scaled so a single event still shows
            if c <= 0:
                bh = 1.0
                alpha = 0.18
            else:
                norm = math.log10(1 + c) / math.log10(1 + self._max)
                bh = max(2.0, norm * bar_zone_h)
                alpha = 0.6 + 0.4 * norm
            x = 8 + i * (bar_w + gap)
            y = bar_top + (bar_zone_h - bh)
            # Color gradient: low=honey, high=sting
            if c >= self._max * 0.7:
                col = STING_RED
            elif c >= self._max * 0.35:
                col = ALERT_ORANGE
            else:
                col = RAW_HONEY
            cr.set_source_rgba(*col, alpha)
            cr.rectangle(x, y, bar_w, bh)
            cr.fill()

        # Time ticks at -24h, -18h, -12h, -6h, now
        cr.set_source_rgba(*PALE_COMB, 0.55)
        cr.set_font_size(10)
        for hours_ago, label in [(24, "-24h"), (18, "-18h"),
                                 (12, "-12h"), (6, "-6h"), (0, "now")]:
            bin_idx = self.BINS - 1 - (hours_ago * 4)
            if bin_idx < 0:
                bin_idx = 0
            x = 8 + bin_idx * (bar_w + gap) + bar_w / 2
            ex = cr.text_extents(label)
            cr.move_to(x - ex.width / 2, h - 3)
            cr.show_text(label)


# ─────────────────────────────────────────────────────────────────────
# CLOCK BAR
# ─────────────────────────────────────────────────────────────────────

class ClockBar(Gtk.DrawingArea):
    def __init__(self):
        super().__init__()
        # v2.3.0: bar grew from 48→66 to fit the persistent authorization
        # notice line (drawn below the title). Required disclosure for
        # always-on kiosk operation.
        self.set_content_height(66)
        self.set_hexpand(True)
        self._pulse_phase = 0.0
        self._total_events = 0
        self._active_sessions = 0
        self._closing = False
        self._timeouts: list[int] = []
        self.set_draw_func(self._draw)
        self._timeouts.append(
            GLib.timeout_add(int(1000 / FPS_CLOCK), self._tick))
        self._timeouts.append(
            GLib.timeout_add(10_000, self._refresh_stats))
        self._refresh_stats()

    def shutdown(self) -> None:
        self._closing = True
        for t in self._timeouts:
            try: GLib.source_remove(t)
            except Exception: pass
        self._timeouts.clear()

    def set_active_sessions(self, n: int) -> None:
        self._active_sessions = int(n)

    def _refresh_stats(self) -> bool:
        if self._closing:
            return False
        def _work():
            try:
                from meli.database import get_session
                from meli.database.models import Event
                from sqlalchemy import select, func
                with get_session() as s:
                    total = s.execute(
                        select(func.count(Event.id))).scalar() or 0
            except Exception:
                total = 0
            GLib.idle_add(self._apply_stats, int(total))
        threading.Thread(target=_work, name="atrium-clock-stats",
                         daemon=True).start()
        return True

    def _apply_stats(self, total: int) -> bool:
        if self._closing:
            return False
        self._total_events = total
        return False

    def _tick(self) -> bool:
        if self._closing:
            return False
        self._pulse_phase = (self._pulse_phase + 0.08) % math.tau
        self.queue_draw()
        return True

    def _draw(self, area, cr: cairo.Context, w: int, h: int) -> None:
        # Translucent dark bar
        cr.set_source_rgba(0.03, 0.02, 0.01, 0.7)
        cr.rectangle(0, 0, w, h)
        cr.fill()
        # Bottom edge accent
        cr.set_source_rgba(*RAW_HONEY, 0.7)
        cr.set_line_width(1.5)
        cr.move_to(0, h - 0.5)
        cr.line_to(w, h - 0.5)
        cr.stroke()

        # Left: title
        cr.set_source_rgb(*RAW_HONEY)
        cr.select_font_face("Sans", cairo.FONT_SLANT_NORMAL,
                            cairo.FONT_WEIGHT_BOLD)
        cr.set_font_size(20)
        cr.move_to(20, 26)
        cr.show_text("MELI · LABYRINTH ATRIUM")

        # v2.3.0: persistent authorization notice below the title.
        # Always visible so anyone walking past the kiosk knows this
        # display is monitoring authorized infrastructure only.
        cr.set_source_rgba(*DIM_WHITE, 0.72)
        cr.select_font_face("Sans", cairo.FONT_SLANT_NORMAL,
                            cairo.FONT_WEIGHT_NORMAL)
        cr.set_font_size(11)
        cr.move_to(20, 52)
        cr.show_text("\u26a0  Monitoring authorized infrastructure only "
                     "\u2014 see DISCLAIMER.md")

        # Center: clock (vertically centered between title and auth line)
        cr.set_source_rgb(*PALE_COMB)
        cr.select_font_face("Monospace", cairo.FONT_SLANT_NORMAL,
                            cairo.FONT_WEIGHT_BOLD)
        cr.set_font_size(22)
        ts = datetime.now(timezone.utc).strftime("%Y-%m-%d  %H:%M:%S UTC")
        ex = cr.text_extents(ts)
        cr.move_to(w / 2 - ex.width / 2, 36)
        cr.show_text(ts)

        # Right: LIVE indicator + counters
        pulse_a = 0.55 + 0.45 * (0.5 + 0.5 * math.sin(self._pulse_phase))
        cr.set_source_rgba(*STING_RED, pulse_a)
        cr.arc(w - 200, 24, 7, 0, math.tau)
        cr.fill()
        cr.set_source_rgba(*STING_RED, pulse_a * 0.5)
        cr.arc(w - 200, 24, 12, 0, math.tau)
        cr.stroke()

        cr.set_source_rgb(*PALE_COMB)
        cr.select_font_face("Monospace", cairo.FONT_SLANT_NORMAL,
                            cairo.FONT_WEIGHT_BOLD)
        cr.set_font_size(14)
        cr.move_to(w - 180, 22)
        cr.show_text("LIVE")
        cr.set_font_size(11)
        cr.set_source_rgba(*PALE_COMB, 0.85)
        cr.move_to(w - 180, 38)
        cr.show_text(f"N={self._total_events:,}   trapped={self._active_sessions}")


# ─────────────────────────────────────────────────────────────────────
# ATRIUM SCENE — composes everything
# ─────────────────────────────────────────────────────────────────────

class AtriumScene(Gtk.Overlay):
    def __init__(self, audio: AtriumAudio):
        super().__init__()
        self._audio = audio
        self._volume = 1.0
        self._audio_enabled = True

        # Layer 0: aurora
        self._bg = AuroraBackground()
        self.set_child(self._bg)

        # Layer 1: main grid
        root = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=0)
        root.set_hexpand(True)
        root.set_vexpand(True)

        self._clock = ClockBar()
        root.append(self._clock)

        # Center row: radar | pot | terminal
        center = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=14)
        center.set_vexpand(True)
        center.set_hexpand(True)
        center.set_margin_top(14)
        center.set_margin_bottom(14)
        center.set_margin_start(14)
        center.set_margin_end(14)

        self._radar = RadarScope()
        radar_frame = self._frame_widget(self._radar, hexpand_basis=0.30)
        center.append(radar_frame)

        # Pot wrapped + scaled up — the existing widget is fixed-size
        # (220x300). We center it vertically and let it sit large.
        pot_col = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=8)
        pot_col.set_hexpand(True)
        pot_col.set_vexpand(True)
        pot_col.set_valign(Gtk.Align.CENTER)
        pot_col.set_halign(Gtk.Align.CENTER)
        self._pot = HoneyPotWidget(window_label="all time")
        # Use a transform so the pot renders at 2.4× on big screens.
        # GTK4 supports widget scaling via Gtk.AspectFrame, but easiest
        # is just to ask for a larger preferred size.
        self._pot.set_size_request(int(220 * 2.2), int(300 * 2.2))
        self._pot.set_content_width(int(220 * 2.2))
        self._pot.set_content_height(int(300 * 2.2))
        pot_col.append(self._pot)
        pot_caption = Gtk.Label()
        pot_caption.set_markup(
            "<span foreground='#fef3c7' font='Sans Bold 13'>"
            "ALL HONEY COLLECTED · Pulses on every new event</span>")
        pot_col.append(pot_caption)
        center.append(pot_col)

        self._terminal = TerminalStream()
        term_frame = self._frame_widget(self._terminal, hexpand_basis=0.30)
        center.append(term_frame)

        root.append(center)

        self._heatmap = HeatmapBar()
        heat_wrap = Gtk.Box()
        heat_wrap.set_margin_start(14)
        heat_wrap.set_margin_end(14)
        heat_wrap.set_margin_bottom(14)
        heat_wrap.append(self._heatmap)
        self._heatmap.set_hexpand(True)
        root.append(heat_wrap)

        self.add_overlay(root)

        # Layer 2: full-screen flash overlay for canary trips
        self._flash = _FlashOverlay()
        self.add_overlay(self._flash)

        # Lifecycle tracking
        self._closing = False
        self._timeouts: list[int] = []

        # Wire event bus
        event_bus.subscribe("event.ingested", self._on_ingested)

        # Periodic refresh of stats that don't come over the bus
        self._poll_stats()
        self._timeouts.append(GLib.timeout_add(5_000, self._poll_stats))

        # Periodic synthetic seed so the display has movement even on
        # a fresh install with zero traffic. ONE blip every 12s, very
        # dim, just so the radar doesn't look broken. Disabled if any
        # real event has arrived in the last 5 min.
        self._last_real_event = 0.0
        self._timeouts.append(GLib.timeout_add(12_000, self._idle_seed))

    def _frame_widget(self, child: Gtk.Widget, hexpand_basis: float) -> Gtk.Widget:
        f = Gtk.Box(orientation=Gtk.Orientation.VERTICAL)
        f.set_hexpand(True)
        f.set_vexpand(True)
        child.set_hexpand(True)
        child.set_vexpand(True)
        f.append(child)
        return f

    # ── live data plumbing ────────────────────────────────────────

    def set_audio_enabled(self, enabled: bool) -> None:
        self._audio_enabled = bool(enabled)

    def set_audio_volume(self, vol: float) -> None:
        self._volume = max(0.0, min(1.0, float(vol)))

    def _audio_play(self, cue: str) -> None:
        if not self._audio_enabled:
            return
        self._audio.play(cue, self._volume)

    def _on_ingested(self, topic, payload):
        # Comes from any thread — re-dispatch onto GTK main loop
        GLib.idle_add(self._handle_ingested, dict(payload or {}))

    def _handle_ingested(self, payload):
        if self._closing:
            return False
        self._last_real_event = time.monotonic()
        sev = (payload.get("severity") or "INFO").upper()
        ip = payload.get("source_ip") or "?"
        service = payload.get("honeypot_service") or "?"
        # Pot pulse
        self._pot.pulse(sev)
        # Radar
        self._radar.add_event(ip, sev, label=ip)
        # Terminal line
        kind = "session_open"
        prefix = ">>>"
        if sev == "CRITICAL":
            kind = "canary"
            prefix = "!!!"
        elif sev == "HIGH":
            kind = "auth_ok"
            prefix = " ! "
        elif sev == "MEDIUM":
            kind = "auth_fail"
            prefix = " > "
        self._terminal.push(f"{prefix} {ip:<15}  {service:<10}  [{sev}]", kind=kind)
        # Audio + flash
        if sev == "CRITICAL":
            self._flash.flash(STING_RED, intensity=0.45)
            self._audio_play("canary_trip")
        elif sev == "HIGH":
            self._flash.flash(ALERT_ORANGE, intensity=0.22)
            self._audio_play("session_open")
        else:
            self._audio_play("session_open")
        return False

    def _poll_stats(self) -> bool:
        """Refresh pot fill + active-session count from DB + Labyrinth
        sticky roster. Runs on the main loop but the queries are cheap
        (just a count) — if they ever get expensive we'll move to a
        thread."""
        if self._closing:
            return False
        def _work():
            total = 0
            trapped = 0
            try:
                from meli.database import get_session
                from meli.database.models import Event
                from sqlalchemy import select, func
                with get_session() as s:
                    total = int(s.execute(
                        select(func.count(Event.id))).scalar() or 0)
            except Exception:
                pass
            try:
                from meli.labyrinth import sink
                trapped = int(getattr(sink, "current_session_count",
                                      lambda: 0)())
            except Exception:
                pass
            GLib.idle_add(self._apply_stats, total, trapped)
        threading.Thread(target=_work, name="atrium-poll-stats",
                         daemon=True).start()
        return True

    def _apply_stats(self, total: int, trapped: int) -> bool:
        if self._closing:
            return False
        self._pot.set_event_count(total)
        self._clock.set_active_sessions(trapped)
        return False

    def _idle_seed(self) -> bool:
        """If no real events in the last 5 min, drop one very-dim blip
        so the radar always has at least *something* to look at. Doesn't
        play audio, doesn't pulse the pot."""
        if self._closing:
            return False
        if time.monotonic() - self._last_real_event < 300:
            return True
        # Random ghost IP — clearly not real (uses TEST-NET-1 range)
        ghost_ip = f"192.0.2.{random.randint(1, 254)}"
        self._radar.add_event(ghost_ip, "INFO", label="(idle)")
        return True

    def shutdown(self) -> None:
        if self._closing:
            return
        self._closing = True
        # Stop our own scene-level timers
        for t in self._timeouts:
            try: GLib.source_remove(t)
            except Exception: pass
        self._timeouts.clear()
        # Unsubscribe from the event bus
        try:
            event_bus.unsubscribe("event.ingested", self._on_ingested)
        except Exception:
            pass
        # Chain shutdown to every child widget that owns timers
        for child in (self._bg, self._radar, self._terminal,
                      self._heatmap, self._clock, self._flash):
            try:
                fn = getattr(child, "shutdown", None)
                if callable(fn):
                    fn()
            except Exception:
                pass


class _FlashOverlay(Gtk.DrawingArea):
    """Full-screen colored flash on canary trips. Transparent when
    idle so it doesn't intercept mouse events."""
    def __init__(self):
        super().__init__()
        self.set_can_target(False)
        self.set_hexpand(True)
        self.set_vexpand(True)
        self._color = STING_RED
        self._started = 0.0
        self._duration = 0.0
        self._intensity = 0.0
        self._closing = False
        self._timeouts: list[int] = []
        self.set_draw_func(self._draw)
        self._timeouts.append(GLib.timeout_add(33, self._tick))

    def shutdown(self) -> None:
        self._closing = True
        for t in self._timeouts:
            try: GLib.source_remove(t)
            except Exception: pass
        self._timeouts.clear()

    def flash(self, color: tuple, intensity: float = 0.4,
              duration: float = 0.85) -> None:
        self._color = color
        self._intensity = intensity
        self._duration = duration
        self._started = time.monotonic()

    def _tick(self) -> bool:
        if self._duration > 0 and (time.monotonic() - self._started) < self._duration:
            self.queue_draw()
        elif self._duration > 0:
            self._duration = 0.0
            self.queue_draw()
        return True

    def _draw(self, area, cr: cairo.Context, w: int, h: int) -> None:
        if self._duration <= 0:
            return
        t = (time.monotonic() - self._started) / self._duration
        if t >= 1.0:
            return
        # Sharp attack, exponential decay
        env = (1.0 - t) ** 1.8
        alpha = self._intensity * env
        cr.set_source_rgba(*self._color, alpha)
        cr.rectangle(0, 0, w, h)
        cr.fill()


# ─────────────────────────────────────────────────────────────────────
# ATRIUM WINDOW
# ─────────────────────────────────────────────────────────────────────

class AtriumWindow(Adw.ApplicationWindow):
    def __init__(self, *, application: Adw.Application,
                 fullscreen: bool = True):
        super().__init__(application=application)
        self.set_title("Meli — Labyrinth Atrium")
        self.set_default_size(1600, 900)

        cfg = get_config()
        audio_enabled = bool(cfg.get("atrium", "audio_enabled", default=True))
        audio_volume  = float(cfg.get("atrium", "audio_volume",  default=0.7))

        self._audio = AtriumAudio()
        self._scene = AtriumScene(self._audio)
        self._scene.set_audio_enabled(audio_enabled)
        self._scene.set_audio_volume(audio_volume)
        self.set_content(self._scene)

        # No decorations, no titlebar — pure scene.
        # Adw.ApplicationWindow already has no traditional titlebar; this
        # also strips the resize/close chrome on tiling/floating WMs.
        try:
            self.set_decorated(False)
        except Exception:
            pass

        # Keyboard: Esc / Ctrl+W / F11 toggle
        controller = Gtk.EventControllerKey()
        controller.connect("key-pressed", self._on_key)
        self.add_controller(controller)

        # Cursor auto-hide
        self._cursor_last_move = time.monotonic()
        self._closing = False
        self._cursor_timeout: int | None = None
        motion = Gtk.EventControllerMotion()
        motion.connect("motion", self._on_motion)
        self.add_controller(motion)
        self._cursor_timeout = GLib.timeout_add(500, self._cursor_check)

        # Close cleanup
        self.connect("close-request", self._on_close)

        if fullscreen:
            self.fullscreen()

    # ── input handlers ────────────────────────────────────────────

    def _on_key(self, controller, keyval, keycode, state):
        if keyval in (Gdk.KEY_Escape,):
            self.close()
            return True
        if keyval == Gdk.KEY_F11:
            if self.is_fullscreen():
                self.unfullscreen()
            else:
                self.fullscreen()
            return True
        # Ctrl+W close
        if keyval == Gdk.KEY_w and (state & Gdk.ModifierType.CONTROL_MASK):
            self.close()
            return True
        # Ctrl+M mute toggle
        if keyval == Gdk.KEY_m and (state & Gdk.ModifierType.CONTROL_MASK):
            cur = bool(get_config().get("atrium", "audio_enabled", default=True))
            new = not cur
            get_config().set("atrium", "audio_enabled", new)
            self._scene.set_audio_enabled(new)
            return True
        return False

    def _on_motion(self, controller, x, y):
        self._cursor_last_move = time.monotonic()
        # Restore default cursor
        try:
            self.set_cursor(None)
        except Exception:
            pass

    def _cursor_check(self) -> bool:
        if self._closing:
            return False
        if time.monotonic() - self._cursor_last_move > CURSOR_HIDE_SECONDS:
            try:
                blank = Gdk.Cursor.new_from_name("none", None)
                if blank is not None:
                    self.set_cursor(blank)
            except Exception:
                pass
        return True

    def _on_close(self, *_):
        self._closing = True
        if self._cursor_timeout is not None:
            try: GLib.source_remove(self._cursor_timeout)
            except Exception: pass
            self._cursor_timeout = None
        try:
            self._scene.shutdown()
        except Exception:
            pass
        return False


# ─────────────────────────────────────────────────────────────────────
# LAUNCH HELPERS
# ─────────────────────────────────────────────────────────────────────

def launch_atrium(app: Adw.Application, *, fullscreen: bool = True) -> AtriumWindow:
    """Open the atrium window. Safe to call from a menu action."""
    win = AtriumWindow(application=app, fullscreen=fullscreen)
    win.present()
    return win

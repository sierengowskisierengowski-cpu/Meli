"""
Honey-pot (amphora) centerpiece widget.

A Cairo-drawn Greek amphora that fills with honey as events accumulate,
pulses when new events arrive, and emits drips down the side
(continuously when the pot is overflowing).

The shape — long flowing neck, two curved handles, bulbous belly, small
flared foot — leans into the "meli" etymology (μέλι = Greek for honey).

The same geometry is exposed as a standalone paint function so we can
render preview PNGs offline without a GTK display.
"""
from __future__ import annotations

import math
import random
import time

import gi
gi.require_version("Gtk", "4.0")
from gi.repository import Gtk, GLib  # noqa: E402

import cairo  # noqa: E402

# Palette — keep in sync with resources/css/style.css
HIVE_BLACK   = (0x10/255, 0x0a/255, 0x04/255)
COMB_PANEL   = (0x22/255, 0x1a/255, 0x12/255)
RAW_HONEY    = (0xd4/255, 0xa0/255, 0x17/255)
AMBER_GLOW   = (0xf5/255, 0x9e/255, 0x0b/255)
DARK_HONEY   = (0x8a/255, 0x5d/255, 0x05/255)
PALE_COMB    = (0xfe/255, 0xf3/255, 0xc7/255)
WARM_BORDER  = (0x3a/255, 0x28/255, 0x18/255)
STING_RED    = (0xdc/255, 0x26/255, 0x26/255)

FRAME_MS = 33  # ~30 fps

# Canonical canvas size for the amphora (widget + preview share this).
CANVAS_W = 220
CANVAS_H = 300

# Amphora geometry, all relative to cx = CANVAS_W / 2.
# Tuned so the silhouette reads as "Greek vase" at any size from 64px up.
_LIP_OUTER_W  = 24
_LIP_TOP_Y    = 32
_LIP_BOT_Y    = 46
_NECK_TOP_W   = 19
_NECK_BOT_W   = 22
_NECK_TOP_Y   = 46
_NECK_BOT_Y   = 110
_SHOULDER_Y   = 130
_SHOULDER_W   = 60
_BELLY_Y      = 184
_BELLY_W      = 84
_TAPER_Y      = 244
_TAPER_W      = 36
_FOOT_TOP_Y   = 252
_FOOT_BOT_Y   = 268
_FOOT_W       = 38


class Drip:
    """A single honey drip running down the outside of the amphora."""
    __slots__ = ("x", "y", "vy", "born", "lifetime", "size")

    def __init__(self, x: float, y: float, size: float = 4.0, lifetime: float = 1.6):
        self.x = x
        self.y = y
        self.vy = 16.0
        self.born = time.monotonic()
        self.lifetime = lifetime
        self.size = size

    def alive(self) -> bool:
        return (time.monotonic() - self.born) < self.lifetime

    def advance(self, dt: float) -> None:
        self.vy += 32.0 * dt
        self.y += self.vy * dt


# ── Path construction ────────────────────────────────────────────────────

def _amphora_path(cr: cairo.Context, cx: float) -> None:
    """Trace the closed amphora outline on the current path."""
    cr.new_path()
    # Top of lip (flat, slightly flared)
    cr.move_to(cx - _LIP_OUTER_W, _LIP_TOP_Y)
    cr.line_to(cx + _LIP_OUTER_W, _LIP_TOP_Y)
    # Right lip — outer down + curve into the neck
    cr.line_to(cx + _LIP_OUTER_W, _LIP_BOT_Y - 6)
    cr.curve_to(
        cx + _LIP_OUTER_W, _LIP_BOT_Y,
        cx + _NECK_TOP_W + 1, _LIP_BOT_Y,
        cx + _NECK_TOP_W, _NECK_TOP_Y,
    )
    # Right neck (long, slight widening at base)
    cr.curve_to(
        cx + _NECK_TOP_W, _NECK_TOP_Y + 35,
        cx + _NECK_BOT_W, _NECK_BOT_Y - 30,
        cx + _NECK_BOT_W, _NECK_BOT_Y,
    )
    # Shoulder out to belly
    cr.curve_to(
        cx + _NECK_BOT_W + 8, _SHOULDER_Y - 4,
        cx + _SHOULDER_W,    _SHOULDER_Y,
        cx + _BELLY_W * 0.78, _SHOULDER_Y + 22,
    )
    cr.curve_to(
        cx + _BELLY_W + 2, _BELLY_Y - 24,
        cx + _BELLY_W + 2, _BELLY_Y + 8,
        cx + _BELLY_W,     _BELLY_Y,
    )
    # Belly down to taper
    cr.curve_to(
        cx + _BELLY_W,     _BELLY_Y + 30,
        cx + _TAPER_W + 10, _TAPER_Y - 6,
        cx + _TAPER_W,     _TAPER_Y,
    )
    # Right side of foot
    cr.line_to(cx + _FOOT_W, _FOOT_TOP_Y)
    cr.line_to(cx + _FOOT_W, _FOOT_BOT_Y)
    # Foot bottom
    cr.line_to(cx - _FOOT_W, _FOOT_BOT_Y)
    cr.line_to(cx - _FOOT_W, _FOOT_TOP_Y)
    # Mirror back up
    cr.line_to(cx - _TAPER_W, _TAPER_Y)
    cr.curve_to(
        cx - _TAPER_W - 10, _TAPER_Y - 6,
        cx - _BELLY_W,     _BELLY_Y + 30,
        cx - _BELLY_W,     _BELLY_Y,
    )
    cr.curve_to(
        cx - _BELLY_W - 2, _BELLY_Y + 8,
        cx - _BELLY_W - 2, _BELLY_Y - 24,
        cx - _BELLY_W * 0.78, _SHOULDER_Y + 22,
    )
    cr.curve_to(
        cx - _SHOULDER_W,    _SHOULDER_Y,
        cx - _NECK_BOT_W - 8, _SHOULDER_Y - 4,
        cx - _NECK_BOT_W,    _NECK_BOT_Y,
    )
    cr.curve_to(
        cx - _NECK_BOT_W, _NECK_BOT_Y - 30,
        cx - _NECK_TOP_W, _NECK_TOP_Y + 35,
        cx - _NECK_TOP_W, _NECK_TOP_Y,
    )
    cr.curve_to(
        cx - _NECK_TOP_W - 1, _LIP_BOT_Y,
        cx - _LIP_OUTER_W,    _LIP_BOT_Y,
        cx - _LIP_OUTER_W,    _LIP_BOT_Y - 6,
    )
    cr.close_path()


def _draw_handles(cr: cairo.Context, cx: float) -> None:
    """Two curved amphora handles — neck to shoulder, S-curve outward."""
    cr.set_line_width(5.0)
    cr.set_line_cap(cairo.LINE_CAP_ROUND)
    cr.set_source_rgb(*RAW_HONEY)
    # Left handle
    cr.move_to(cx - _NECK_TOP_W - 1, 64)
    cr.curve_to(cx - 60, 70, cx - 72, 110, cx - 56, 134)
    cr.stroke()
    # Right handle
    cr.move_to(cx + _NECK_TOP_W + 1, 64)
    cr.curve_to(cx + 60, 70, cx + 72, 110, cx + 56, 134)
    cr.stroke()
    # Subtle inner shadow on handles for depth
    cr.set_source_rgba(*WARM_BORDER, 0.6)
    cr.set_line_width(1.4)
    cr.move_to(cx - _NECK_TOP_W - 1, 64)
    cr.curve_to(cx - 60, 70, cx - 72, 110, cx - 56, 134)
    cr.stroke()
    cr.move_to(cx + _NECK_TOP_W + 1, 64)
    cr.curve_to(cx + 60, 70, cx + 72, 110, cx + 56, 134)
    cr.stroke()


# ── Standalone paint (used by widget + offline preview) ──────────────────

def paint_pot(cr: cairo.Context, width: int, height: int, *,
              fill: float,
              event_count: int,
              drips=(),
              pulse_color=None,
              pulse_alpha: float = 0.0,
              wobble_phase: float = 0.0,
              show_label: bool = True,
              window_label: str = "last 7 days") -> None:
    """Paint the amphora into the given Cairo context.

    fill: 0.0–1.0 honey level
    drips: iterable of Drip objects (or None) to render on the outside
    pulse_color: (r,g,b) tuple or None
    pulse_alpha: 0.0–1.0 strength of the halo glow this frame
    wobble_phase: radians, drives the liquid-surface ripple
    """
    cx = width / 2

    # ── Pulse halo ─────────────────────────────────────────────────
    if pulse_color is not None and pulse_alpha > 0.001:
        for i in range(4, 0, -1):
            radius = _BELLY_W + 20 + i * 10
            a = 0.16 * pulse_alpha / i
            grad = cairo.RadialGradient(cx, _BELLY_Y, _BELLY_W * 0.4,
                                        cx, _BELLY_Y, radius)
            grad.add_color_stop_rgba(0, *pulse_color, a)
            grad.add_color_stop_rgba(1, *pulse_color, 0)
            cr.set_source(grad)
            cr.arc(cx, _BELLY_Y, radius, 0, math.tau)
            cr.fill()

    # ── Handles (behind the body so they look attached) ───────────
    _draw_handles(cr, cx)

    # ── Amphora body fill (ceramic) ───────────────────────────────
    _amphora_path(cr, cx)
    body_grad = cairo.LinearGradient(0, _LIP_TOP_Y, 0, _FOOT_BOT_Y)
    body_grad.add_color_stop_rgb(0.0, *COMB_PANEL)
    body_grad.add_color_stop_rgb(0.5, 0x2c/255, 0x1f/255, 0x14/255)
    body_grad.add_color_stop_rgb(1.0, *WARM_BORDER)
    cr.set_source(body_grad)
    cr.fill_preserve()
    # Cross-body highlight on the left shoulder
    hl = cairo.LinearGradient(cx - _BELLY_W, 0, cx + _BELLY_W, 0)
    hl.add_color_stop_rgba(0, *PALE_COMB, 0.07)
    hl.add_color_stop_rgba(0.4, *PALE_COMB, 0)
    cr.set_source(hl)
    cr.fill()

    # ── Honey fill (clipped to body silhouette) ───────────────────
    cr.save()
    _amphora_path(cr, cx)
    cr.clip()

    fill = max(0.0, min(1.0, fill))
    # Honey rises from foot to neck base. Below ~20% it sits in the
    # belly taper; at 100% it reaches the neck base.
    empty_y = _FOOT_TOP_Y - 4
    full_y  = _NECK_BOT_Y - 6
    surface_y = empty_y + (full_y - empty_y) * fill

    wob_amp = 1.8 if fill > 0.04 else 0
    steps = 36
    cr.new_path()
    cr.move_to(cx - _BELLY_W - 6, _FOOT_BOT_Y + 4)
    for i in range(steps + 1):
        t = i / steps
        x = (cx - _BELLY_W - 6) + t * (_BELLY_W * 2 + 12)
        y = surface_y + math.sin(wobble_phase + t * math.tau * 1.5) * wob_amp
        cr.line_to(x, y)
    cr.line_to(cx + _BELLY_W + 6, _FOOT_BOT_Y + 4)
    cr.close_path()

    honey_grad = cairo.LinearGradient(0, surface_y, 0, _FOOT_BOT_Y)
    honey_grad.add_color_stop_rgba(0.0, *AMBER_GLOW, 0.95)
    honey_grad.add_color_stop_rgba(0.5, *RAW_HONEY, 1.0)
    honey_grad.add_color_stop_rgba(1.0, *DARK_HONEY, 1.0)
    cr.set_source(honey_grad)
    cr.fill()

    if fill > 0.04:
        cr.set_source_rgba(*PALE_COMB, 0.20)
        cr.set_line_width(2)
        cr.move_to(cx - _BELLY_W * 0.5, surface_y + 7)
        cr.line_to(cx - _BELLY_W * 0.1, surface_y + 4)
        cr.stroke()

    cr.restore()

    # ── Body outline ──────────────────────────────────────────────
    _amphora_path(cr, cx)
    cr.set_source_rgb(*RAW_HONEY)
    cr.set_line_width(2.4)
    cr.stroke()

    # Lip detail
    cr.set_source_rgba(*RAW_HONEY, 0.75)
    cr.set_line_width(1.6)
    cr.move_to(cx - _LIP_OUTER_W + 1, _LIP_BOT_Y - 6)
    cr.line_to(cx + _LIP_OUTER_W - 1, _LIP_BOT_Y - 6)
    cr.stroke()

    # Foot top ridge
    cr.set_source_rgba(*RAW_HONEY, 0.7)
    cr.set_line_width(1.4)
    cr.move_to(cx - _FOOT_W + 2, _FOOT_TOP_Y)
    cr.line_to(cx + _FOOT_W - 2, _FOOT_TOP_Y)
    cr.stroke()

    # ── Drips on the outside ──────────────────────────────────────
    for d in drips or ():
        age = (time.monotonic() - d.born) / d.lifetime
        alpha = 1.0 - age * 0.35
        cr.set_source_rgba(*RAW_HONEY, alpha)
        cr.new_path()
        cr.move_to(d.x - d.size * 0.3, d.y - d.size * 1.8)
        cr.line_to(d.x + d.size * 0.3, d.y - d.size * 1.8)
        cr.line_to(d.x + d.size * 0.6, d.y - d.size * 0.5)
        cr.arc(d.x, d.y, d.size * 0.9, 0, math.tau)
        cr.line_to(d.x - d.size * 0.6, d.y - d.size * 0.5)
        cr.close_path()
        cr.fill()
        cr.set_source_rgba(*PALE_COMB, alpha * 0.55)
        cr.arc(d.x - d.size * 0.25, d.y - d.size * 0.25, d.size * 0.25, 0, math.tau)
        cr.fill()

    # ── Label below ───────────────────────────────────────────────
    if show_label:
        cr.set_source_rgb(*PALE_COMB)
        cr.select_font_face("Sans", cairo.FONT_SLANT_NORMAL, cairo.FONT_WEIGHT_BOLD)
        cr.set_font_size(13)
        label = f"{event_count:,} caught"
        ex = cr.text_extents(label)
        cr.move_to(cx - ex.width / 2, _FOOT_BOT_Y + 18)
        cr.show_text(label)

        cr.set_source_rgba(*PALE_COMB, 0.6)
        cr.set_font_size(10)
        pct = f"{window_label} · {int(round(fill * 100))}% full"
        ex2 = cr.text_extents(pct)
        cr.move_to(cx - ex2.width / 2, _FOOT_BOT_Y + 32)
        cr.show_text(pct)


# ── GTK widget ───────────────────────────────────────────────────────────

class HoneyPotWidget(Gtk.DrawingArea):
    """Centerpiece amphora widget. Public API:

        set_event_count(n)   — animates fill toward log-scaled target
        pulse(severity)      — one-shot glow + drip from the rim
        set_max_events(n)    — change the "100% full" threshold
    """

    def __init__(self, max_events: int = 5000, window_label: str = "last 7 days"):
        super().__init__()
        self.set_size_request(CANVAS_W, CANVAS_H)
        self.set_content_width(CANVAS_W)
        self.set_content_height(CANVAS_H)
        self.set_draw_func(self._draw)

        self._window_label = window_label
        self._max_events = max(1, max_events)
        self._target_fill = 0.0
        self._current_fill = 0.0
        self._event_count = 0

        self._drips: list[Drip] = []
        self._pulse_until = 0.0
        self._pulse_started = 0.0
        self._pulse_duration = 0.5
        self._pulse_color = AMBER_GLOW
        self._wobble_phase = random.random() * math.tau
        self._overflow_accumulator = 0.0
        self._last_frame = time.monotonic()

        GLib.timeout_add(FRAME_MS, self._tick)

    # ── Public ─────────────────────────────────────────────────────

    def set_event_count(self, n: int) -> None:
        self._event_count = max(0, int(n))
        if self._event_count == 0:
            self._target_fill = 0.0
        else:
            self._target_fill = min(
                1.0,
                math.log10(self._event_count + 1) / math.log10(self._max_events + 1),
            )

    def set_max_events(self, n: int) -> None:
        self._max_events = max(1, int(n))
        self.set_event_count(self._event_count)

    def pulse(self, severity: str = "INFO") -> None:
        sev = (severity or "INFO").upper()
        if sev == "CRITICAL":
            self._pulse_color = STING_RED
            duration = 1.0
        elif sev == "HIGH":
            self._pulse_color = AMBER_GLOW
            duration = 0.7
        else:
            self._pulse_color = RAW_HONEY
            duration = 0.5
        now = time.monotonic()
        self._pulse_started = now
        self._pulse_until = now + duration
        self._pulse_duration = duration
        self._spawn_drip_at_rim()

    # ── Animation loop ────────────────────────────────────────────

    def _tick(self) -> bool:
        now = time.monotonic()
        dt = now - self._last_frame
        self._last_frame = now

        delta = self._target_fill - self._current_fill
        if abs(delta) > 0.001:
            self._current_fill += delta * min(1.0, dt * 2.2)

        self._wobble_phase = (self._wobble_phase + dt * 1.6) % math.tau

        if self._current_fill >= 0.98:
            self._overflow_accumulator += dt
            if self._overflow_accumulator > 0.4:
                self._overflow_accumulator = 0.0
                self._spawn_drip_at_rim()

        for d in self._drips:
            d.advance(dt)
        self._drips = [d for d in self._drips if d.alive() and d.y < CANVAS_H]

        self.queue_draw()
        return True

    def _spawn_drip_at_rim(self) -> None:
        side = random.choice((-1, 1))
        x_center = CANVAS_W / 2
        x = x_center + side * (_LIP_OUTER_W - random.uniform(2, 6))
        y = _LIP_BOT_Y + random.uniform(0, 4)
        self._drips.append(Drip(x, y, size=random.uniform(3.0, 5.5)))

    # ── Draw delegate ─────────────────────────────────────────────

    def _draw(self, area, cr: cairo.Context, width: int, height: int) -> None:
        now = time.monotonic()
        pulse_alpha = 0.0
        pulse_color = None
        if now < self._pulse_until and self._pulse_duration > 0:
            elapsed = now - self._pulse_started
            pulse_alpha = max(0.0, 1.0 - elapsed / self._pulse_duration)
            pulse_color = self._pulse_color

        paint_pot(
            cr, width, height,
            fill=self._current_fill,
            event_count=self._event_count,
            drips=self._drips,
            pulse_color=pulse_color,
            pulse_alpha=pulse_alpha,
            wobble_phase=self._wobble_phase,
            window_label=self._window_label,
        )


# ── Static SVG export (used for headerbar / app icon) ────────────────────

def logo_svg(size: int = 64) -> str:
    """Return a small static SVG of the amphora — for headerbar / app
    icon use. Half-full, no drips, no animation."""
    return f"""<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 220 300" width="{size}" height="{int(size * 300 / 220)}">
  <defs>
    <linearGradient id="amb" x1="0" y1="32" x2="0" y2="268" gradientUnits="userSpaceOnUse">
      <stop offset="0" stop-color="#221a12"/>
      <stop offset="0.5" stop-color="#2c1f14"/>
      <stop offset="1" stop-color="#3a2818"/>
    </linearGradient>
    <linearGradient id="amh" x1="0" y1="180" x2="0" y2="270" gradientUnits="userSpaceOnUse">
      <stop offset="0" stop-color="#f59e0b"/>
      <stop offset="0.5" stop-color="#d4a017"/>
      <stop offset="1" stop-color="#8a5d05"/>
    </linearGradient>
    <clipPath id="ampclip">
      <path d="M 86 32 L 134 32 L 134 40 C 134 46 129 46 129 46 C 132 60 134 90 132 110 C 138 116 168 130 170 184 C 168 220 156 244 146 244 L 148 252 L 148 268 L 72 268 L 72 252 L 74 244 C 64 244 52 220 50 184 C 52 130 82 116 88 110 C 86 90 88 60 91 46 C 91 46 86 46 86 40 Z"/>
    </clipPath>
  </defs>
  <!-- Handles -->
  <path d="M 91 64 C 60 70 48 110 64 134" stroke="#d4a017" stroke-width="5" fill="none" stroke-linecap="round"/>
  <path d="M 129 64 C 160 70 172 110 156 134" stroke="#d4a017" stroke-width="5" fill="none" stroke-linecap="round"/>
  <!-- Body -->
  <path d="M 86 32 L 134 32 L 134 40 C 134 46 129 46 129 46 C 132 60 134 90 132 110 C 138 116 168 130 170 184 C 168 220 156 244 146 244 L 148 252 L 148 268 L 72 268 L 72 252 L 74 244 C 64 244 52 220 50 184 C 52 130 82 116 88 110 C 86 90 88 60 91 46 C 91 46 86 46 86 40 Z"
        fill="url(#amb)" stroke="#d4a017" stroke-width="2.4"/>
  <!-- Honey (half) -->
  <rect x="40" y="180" width="140" height="100" fill="url(#amh)" clip-path="url(#ampclip)"/>
  <!-- Surface highlight -->
  <path d="M 60 182 Q 110 178 160 182" stroke="#fde68a" stroke-width="1.6" fill="none" opacity="0.5" clip-path="url(#ampclip)"/>
  <!-- Lip + foot ridges -->
  <line x1="86" y1="40" x2="134" y2="40" stroke="#d4a017" stroke-width="1.6" opacity="0.75"/>
  <line x1="74" y1="252" x2="146" y2="252" stroke="#d4a017" stroke-width="1.4" opacity="0.7"/>
  <!-- Drip from rim -->
  <path d="M 128 32 Q 127 44 129 50 Q 131 44 130 32 Z" fill="#d4a017"/>
  <circle cx="129" cy="50" r="3" fill="#d4a017"/>
</svg>"""


# ── Offline preview entrypoint ───────────────────────────────────────────
# Renders three PNG snapshots (empty / half / overflowing) so we can
# show the user how the live widget will look without needing a display.
#
#     python -m meli.ui.widgets.honey_pot /tmp/preview
#
if __name__ == "__main__":
    import sys
    from pathlib import Path

    out_dir = Path(sys.argv[1] if len(sys.argv) > 1 else "/tmp/honey_pot_preview")
    out_dir.mkdir(parents=True, exist_ok=True)

    def render(name: str, fill: float, count: int, drips: list[Drip],
               pulse_color=None, pulse_alpha=0.0) -> Path:
        surface = cairo.ImageSurface(cairo.FORMAT_ARGB32, CANVAS_W, CANVAS_H)
        cr = cairo.Context(surface)
        # Hive-black background
        cr.set_source_rgb(*HIVE_BLACK)
        cr.paint()
        paint_pot(
            cr, CANVAS_W, CANVAS_H,
            fill=fill, event_count=count,
            drips=drips,
            pulse_color=pulse_color, pulse_alpha=pulse_alpha,
            wobble_phase=0.6,
        )
        path = out_dir / f"{name}.png"
        surface.write_to_png(str(path))
        return path

    # 1. Fresh install, no events
    render("01_empty", fill=0.0, count=0, drips=[])

    # 2. Active hive — half full, one fresh pulse with a drip
    drips_half = [Drip(_LIP_OUTER_W + 88, _LIP_BOT_Y + 18, size=4.5)]
    render("02_half", fill=0.55, count=187, drips=drips_half,
           pulse_color=AMBER_GLOW, pulse_alpha=0.7)

    # 3. Overflowing — full pot, multiple drips cascading down
    drips_full = [
        Drip(_LIP_OUTER_W + 88, _LIP_BOT_Y + 6,  size=4.5),
        Drip(110 - _LIP_OUTER_W + 2, _LIP_BOT_Y + 28, size=5.0),
        Drip(110 + _LIP_OUTER_W - 2, _LIP_BOT_Y + 62, size=3.8),
        Drip(110 - _LIP_OUTER_W + 4, _LIP_BOT_Y + 110, size=4.2),
    ]
    render("03_overflow", fill=1.0, count=12453, drips=drips_full,
           pulse_color=STING_RED, pulse_alpha=0.85)

    print(f"Wrote 3 previews to {out_dir}")

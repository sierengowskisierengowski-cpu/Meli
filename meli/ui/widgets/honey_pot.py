"""Mockup-style honey jar — cylindrical with honeycomb hex texture.

Visual contract: matches the React mockup at
``artifacts/mockup-sandbox/src/components/mockups/meli/HoneyPot.tsx``.

Replaces the prior amphora silhouette with a clean cylindrical jar:
small neck inset, wide rim, cylindrical body with subtle bulge, soft
amber radial glow halo behind the jar, honeycomb hexagon texture
visible in the lower half of the liquid.

Public API is preserved so callers don't need updating:
- HoneyPotWidget()
- .set_event_count(n) / .set_max_events(n) / .pulse(severity)
- paint_pot(cr, w, h, *, fill, event_count, ...)
- logo_svg(size)
"""
from __future__ import annotations

import math
import random
import time

import gi
gi.require_version("Gtk", "4.0")
from gi.repository import Gtk, GLib  # noqa: E402

import cairo  # noqa: E402

from meli.ui.widgets.charts import (
    HIVE_BLACK, COMB_PANEL, RAW_HONEY, AMBER_GLOW, PALE_COMB,
    BEESWAX, BURNT_ORANGE, STING_RED, WARM_BORDER,
)


DARK_HONEY = (0.54, 0.36, 0.02)
FRAME_MS = 33  # ~30 fps

# Canonical canvas size (widget + preview share this). The widget is set
# to a much larger size; cairo scales the entire scene up linearly.
CANVAS_W = 220
CANVAS_H = 300

# Cylindrical jar geometry (all integers, all relative to cx = W/2).
_RIM_HALF_W   = 64
_RIM_TOP_Y    = 36
_RIM_BOT_Y    = 56
_NECK_HALF_W  = 60          # slight inset under the rim
_NECK_BOT_Y   = 70
_BODY_HALF_W  = 80          # widest point of the cylinder
_BODY_TOP_Y   = 78
_BODY_MID_Y   = 180
_BODY_BOT_Y   = 270
_BASE_HALF_W  = 78
_BASE_BOT_Y   = 278

_HEX_R        = 18          # honeycomb cell radius
_HEX_ROW_H    = _HEX_R * 1.5
_HEX_COL_W    = _HEX_R * math.sqrt(3)


class Drip:
    """A single honey drip running down the outside of the jar."""
    __slots__ = ("x", "y", "vy", "born", "lifetime", "size")

    def __init__(self, x: float, y: float, size: float = 4.0,
                 lifetime: float = 1.6):
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

def _jar_path(cr: cairo.Context, cx: float) -> None:
    """Trace the closed cylindrical-jar outline. Wide rim, slight neck
    inset, cylindrical body that bulges very slightly mid-height, gentle
    rounded base. Read as a clean modern honey jar (not amphora)."""
    cr.new_path()
    # Top of the rim (flat across the top)
    cr.move_to(cx - _RIM_HALF_W, _RIM_TOP_Y)
    cr.line_to(cx + _RIM_HALF_W, _RIM_TOP_Y)
    # Right side of rim down, then curve in to the neck
    cr.line_to(cx + _RIM_HALF_W, _RIM_BOT_Y - 4)
    cr.curve_to(cx + _RIM_HALF_W, _RIM_BOT_Y,
                cx + _NECK_HALF_W, _RIM_BOT_Y,
                cx + _NECK_HALF_W, _NECK_BOT_Y)
    # Curve out from neck to the cylindrical body
    cr.curve_to(cx + _NECK_HALF_W, _BODY_TOP_Y - 2,
                cx + _BODY_HALF_W, _BODY_TOP_Y,
                cx + _BODY_HALF_W, _BODY_TOP_Y + 8)
    # Down the right side of the cylinder (very slight bulge mid-body)
    cr.curve_to(cx + _BODY_HALF_W + 2, _BODY_MID_Y - 30,
                cx + _BODY_HALF_W + 2, _BODY_MID_Y + 30,
                cx + _BODY_HALF_W, _BODY_BOT_Y - 8)
    # Round into the base
    cr.curve_to(cx + _BODY_HALF_W, _BODY_BOT_Y,
                cx + _BASE_HALF_W, _BODY_BOT_Y + 2,
                cx + _BASE_HALF_W, _BASE_BOT_Y)
    # Across the bottom
    cr.line_to(cx - _BASE_HALF_W, _BASE_BOT_Y)
    # Mirror back up the left side
    cr.curve_to(cx - _BASE_HALF_W, _BODY_BOT_Y + 2,
                cx - _BODY_HALF_W, _BODY_BOT_Y,
                cx - _BODY_HALF_W, _BODY_BOT_Y - 8)
    cr.curve_to(cx - _BODY_HALF_W - 2, _BODY_MID_Y + 30,
                cx - _BODY_HALF_W - 2, _BODY_MID_Y - 30,
                cx - _BODY_HALF_W, _BODY_TOP_Y + 8)
    cr.curve_to(cx - _BODY_HALF_W, _BODY_TOP_Y,
                cx - _NECK_HALF_W, _BODY_TOP_Y - 2,
                cx - _NECK_HALF_W, _NECK_BOT_Y)
    cr.curve_to(cx - _NECK_HALF_W, _RIM_BOT_Y,
                cx - _RIM_HALF_W, _RIM_BOT_Y,
                cx - _RIM_HALF_W, _RIM_BOT_Y - 4)
    cr.close_path()


def _hexagon_path(cr: cairo.Context, cx: float, cy: float, r: float) -> None:
    """Trace a flat-top hexagon centred at (cx,cy) with circumradius r."""
    cr.new_sub_path()
    for i in range(6):
        a = math.pi / 3 * i + math.pi / 6  # pointy-top hex
        x = cx + r * math.cos(a)
        y = cy + r * math.sin(a)
        if i == 0:
            cr.move_to(x, y)
        else:
            cr.line_to(x, y)
    cr.close_path()


def _draw_honeycomb_texture(cr: cairo.Context, cx: float,
                            surface_y: float) -> None:
    """Tile honeycomb hexagons across the lower body of the jar.

    Drawn *inside* the jar's clipped region — caller must clip first.
    Each cell is a thin amber-line hex with a very faint amber fill, so
    the liquid still reads as liquid but with a visible cell structure
    like real honeycomb.
    """
    # Tile rows from just below the surface down to the base
    top    = max(_BODY_TOP_Y + 20, surface_y - 4)
    bottom = _BODY_BOT_Y - 6
    if top >= bottom - 8:
        return

    row = 0
    y = top
    while y < bottom + _HEX_R:
        # Offset every other row so cells tessellate (pointy-top hex grid)
        x_offset = (_HEX_COL_W / 2) if (row % 2 == 1) else 0
        x = cx - _BODY_HALF_W - _HEX_COL_W + x_offset
        while x < cx + _BODY_HALF_W + _HEX_COL_W:
            # Fade cells near the surface so the texture eases in
            depth = (y - top) / max(1.0, bottom - top)
            alpha_fill   = 0.10 + 0.18 * min(1.0, depth * 1.4)
            alpha_stroke = 0.35 + 0.40 * min(1.0, depth * 1.4)

            _hexagon_path(cr, x, y, _HEX_R - 1.5)
            cr.set_source_rgba(*PALE_COMB, alpha_fill * 0.4)
            cr.fill_preserve()
            cr.set_source_rgba(*BEESWAX, alpha_stroke)
            cr.set_line_width(1.4)
            cr.stroke()

            x += _HEX_COL_W
        row += 1
        y += _HEX_ROW_H


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
    """Paint the cylindrical honey jar (mockup-matching)."""
    cx = width / 2

    # ── 1. Soft amber radial glow halo (always on, intensifies on pulse) ─
    base_glow_alpha = 0.18 + 0.45 * (pulse_alpha if pulse_color else 0)
    glow_color = pulse_color if pulse_color else AMBER_GLOW
    for i in range(6, 0, -1):
        radius = _BODY_HALF_W + 20 + i * 14
        a = (base_glow_alpha / i) * 0.6
        grad = cairo.RadialGradient(cx, _BODY_MID_Y, _BODY_HALF_W * 0.4,
                                    cx, _BODY_MID_Y, radius)
        grad.add_color_stop_rgba(0, *glow_color, a)
        grad.add_color_stop_rgba(1, *glow_color, 0)
        cr.set_source(grad)
        cr.arc(cx, _BODY_MID_Y, radius, 0, math.tau)
        cr.fill()

    # ── 2. Jar body fill (warm-dark glass) ───────────────────────────
    _jar_path(cr, cx)
    body_grad = cairo.LinearGradient(0, _RIM_TOP_Y, 0, _BASE_BOT_Y)
    body_grad.add_color_stop_rgb(0.0, *COMB_PANEL)
    body_grad.add_color_stop_rgb(0.4, 0x2c / 255, 0x1f / 255, 0x14 / 255)
    body_grad.add_color_stop_rgb(1.0, *WARM_BORDER)
    cr.set_source(body_grad)
    cr.fill_preserve()
    # Soft left-side highlight for ceramic curvature
    hl = cairo.LinearGradient(cx - _BODY_HALF_W, 0, cx + _BODY_HALF_W, 0)
    hl.add_color_stop_rgba(0.0, *PALE_COMB, 0.10)
    hl.add_color_stop_rgba(0.5, *PALE_COMB, 0.00)
    cr.set_source(hl)
    cr.fill()

    # ── 3. Honey fill — clipped to the jar silhouette ────────────────
    cr.save()
    _jar_path(cr, cx)
    cr.clip()

    fill = max(0.0, min(1.0, fill))
    empty_y = _BODY_BOT_Y - 4
    full_y  = _BODY_TOP_Y + 6
    surface_y = empty_y + (full_y - empty_y) * fill

    if fill > 0.01:
        # Wobbling surface line
        wob_amp = 1.8 if fill > 0.04 else 0
        steps = 32
        cr.new_path()
        cr.move_to(cx - _BODY_HALF_W - 6, _BASE_BOT_Y + 4)
        for i in range(steps + 1):
            t = i / steps
            x = (cx - _BODY_HALF_W - 6) + t * (_BODY_HALF_W * 2 + 12)
            y = surface_y + math.sin(wobble_phase + t * math.tau * 1.5) * wob_amp
            cr.line_to(x, y)
        cr.line_to(cx + _BODY_HALF_W + 6, _BASE_BOT_Y + 4)
        cr.close_path()

        honey_grad = cairo.LinearGradient(0, surface_y, 0, _BASE_BOT_Y)
        honey_grad.add_color_stop_rgba(0.0, *AMBER_GLOW, 0.97)
        honey_grad.add_color_stop_rgba(0.4, *RAW_HONEY, 1.0)
        honey_grad.add_color_stop_rgba(1.0, *DARK_HONEY, 1.0)
        cr.set_source(honey_grad)
        cr.fill()

        # Honeycomb hex texture inside the liquid
        _draw_honeycomb_texture(cr, cx, surface_y)

        # Surface highlight ripple
        cr.set_source_rgba(*PALE_COMB, 0.30)
        cr.set_line_width(1.8)
        cr.move_to(cx - _BODY_HALF_W * 0.55, surface_y + 4)
        cr.line_to(cx - _BODY_HALF_W * 0.10, surface_y + 2)
        cr.stroke()

    cr.restore()

    # ── 4. Jar outline (warm amber, thick) ───────────────────────────
    _jar_path(cr, cx)
    cr.set_source_rgb(*RAW_HONEY)
    cr.set_line_width(2.6)
    cr.stroke()

    # ── 5. Inner glass highlight (top of body, left side) ────────────
    cr.save()
    _jar_path(cr, cx)
    cr.clip()
    sheen = cairo.LinearGradient(cx - _BODY_HALF_W * 0.7, _BODY_TOP_Y,
                                 cx - _BODY_HALF_W * 0.4, _BODY_MID_Y)
    sheen.add_color_stop_rgba(0.0, *PALE_COMB, 0.18)
    sheen.add_color_stop_rgba(1.0, *PALE_COMB, 0.0)
    cr.set_source(sheen)
    cr.rectangle(cx - _BODY_HALF_W, _BODY_TOP_Y,
                 _BODY_HALF_W * 0.4, _BODY_MID_Y - _BODY_TOP_Y)
    cr.fill()
    cr.restore()

    # ── 6. Rim + lid detail ──────────────────────────────────────────
    # Lid stripe across the rim top
    cr.set_source_rgba(*AMBER_GLOW, 0.85)
    cr.rectangle(cx - _RIM_HALF_W + 3, _RIM_TOP_Y - 1,
                 _RIM_HALF_W * 2 - 6, 6)
    cr.fill()
    # Rim bottom ridge
    cr.set_source_rgba(*RAW_HONEY, 0.85)
    cr.set_line_width(1.6)
    cr.move_to(cx - _RIM_HALF_W + 2, _RIM_BOT_Y - 4)
    cr.line_to(cx + _RIM_HALF_W - 2, _RIM_BOT_Y - 4)
    cr.stroke()

    # ── 7. Drips on the outside ──────────────────────────────────────
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
        cr.arc(d.x - d.size * 0.25, d.y - d.size * 0.25,
               d.size * 0.25, 0, math.tau)
        cr.fill()

    # ── 8. Label below ───────────────────────────────────────────────
    if show_label:
        cr.set_source_rgb(*PALE_COMB)
        cr.select_font_face("Sans", cairo.FONT_SLANT_NORMAL,
                            cairo.FONT_WEIGHT_BOLD)
        cr.set_font_size(13)
        label = f"{event_count:,} caught"
        ex = cr.text_extents(label)
        cr.move_to(cx - ex.width / 2, _BASE_BOT_Y + 18)
        cr.show_text(label)

        cr.set_source_rgba(*PALE_COMB, 0.6)
        cr.set_font_size(10)
        pct = f"{window_label} · {int(round(fill * 100))}% full"
        ex2 = cr.text_extents(pct)
        cr.move_to(cx - ex2.width / 2, _BASE_BOT_Y + 32)
        cr.show_text(pct)


# ── GTK widget ───────────────────────────────────────────────────────────

class HoneyPotWidget(Gtk.DrawingArea):
    """Centerpiece honey-jar widget (mockup-matching cylindrical jar)."""

    def __init__(self, max_events: int = 5000,
                 window_label: str = "last 7 days"):
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
        self._last_frame = time.monotonic()

        GLib.timeout_add(FRAME_MS, self._tick)

    # ── Public API (unchanged) ─────────────────────────────────────────

    def set_event_count(self, n: int) -> None:
        self._event_count = max(0, int(n))
        if self._event_count == 0:
            self._target_fill = 0.0
        else:
            self._target_fill = min(
                1.0,
                math.log10(self._event_count + 1) /
                math.log10(self._max_events + 1),
            )

    def set_max_events(self, n: int) -> None:
        self._max_events = max(1, int(n))
        self.set_event_count(self._event_count)

    def pulse(self, severity: str = "INFO") -> None:
        sev = (severity or "INFO").upper()
        if sev == "CRITICAL":
            self._pulse_color = STING_RED
            duration = 0.9
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

    # ── Internals ──────────────────────────────────────────────────────

    def _tick(self) -> bool:
        now = time.monotonic()
        dt = now - self._last_frame
        self._last_frame = now

        delta = self._target_fill - self._current_fill
        if abs(delta) > 0.001:
            self._current_fill += delta * min(1.0, dt * 2.2)

        self._wobble_phase = (self._wobble_phase + dt * 1.6) % math.tau

        for d in list(self._drips):
            d.advance(dt)
            if not d.alive() or d.y > CANVAS_H + 8:
                try:
                    self._drips.remove(d)
                except ValueError:
                    pass

        self.queue_draw()
        return True

    def _spawn_drip_at_rim(self) -> None:
        cx = CANVAS_W / 2
        side = random.choice([-1, 1])
        x = cx + side * (_RIM_HALF_W - 6 + random.uniform(-2, 2))
        self._drips.append(Drip(x, _RIM_BOT_Y + 2,
                                size=random.uniform(3.5, 5.0)))

    def _draw(self, _a, cr: cairo.Context, w: int, h: int) -> None:
        # Scale canvas so the jar fills the allocated widget area
        sx = w / CANVAS_W
        sy = h / CANVAS_H
        s = min(sx, sy)
        cr.translate((w - CANVAS_W * s) / 2, (h - CANVAS_H * s) / 2)
        cr.scale(s, s)

        now = time.monotonic()
        if now < self._pulse_until and self._pulse_duration > 0:
            t = (now - self._pulse_started) / self._pulse_duration
            pulse_alpha = max(0.0, 1.0 - t)
            pulse_color = self._pulse_color
        else:
            pulse_alpha = 0.0
            pulse_color = None

        paint_pot(
            cr, CANVAS_W, CANVAS_H,
            fill=self._current_fill,
            event_count=self._event_count,
            drips=self._drips,
            pulse_color=pulse_color,
            pulse_alpha=pulse_alpha,
            wobble_phase=self._wobble_phase,
            window_label=self._window_label,
            show_label=False,  # corner overlays in dashboard own the labels
        )


# ── Static SVG export (used for headerbar / app icon) ────────────────────

def logo_svg(size: int = 64) -> str:
    """Return a small static SVG of the honey jar — for headerbar / app
    icon use. Cylindrical, half-full, with a honeycomb cell visible."""
    return f"""<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 220 300" width="{size}" height="{int(size * 300 / 220)}">
  <defs>
    <linearGradient id="jbody" x1="0" y1="36" x2="0" y2="278" gradientUnits="userSpaceOnUse">
      <stop offset="0" stop-color="#221a12"/>
      <stop offset="0.5" stop-color="#2c1f14"/>
      <stop offset="1" stop-color="#3a2818"/>
    </linearGradient>
    <linearGradient id="jhoney" x1="0" y1="160" x2="0" y2="270" gradientUnits="userSpaceOnUse">
      <stop offset="0" stop-color="#f59e0b"/>
      <stop offset="0.4" stop-color="#d4a017"/>
      <stop offset="1" stop-color="#8a5d05"/>
    </linearGradient>
    <radialGradient id="jglow" cx="110" cy="180" r="130" gradientUnits="userSpaceOnUse">
      <stop offset="0" stop-color="#f59e0b" stop-opacity="0.35"/>
      <stop offset="1" stop-color="#f59e0b" stop-opacity="0"/>
    </radialGradient>
    <clipPath id="jclip">
      <path d="M 46 36 L 174 36 L 174 52 C 174 56 170 56 170 56 C 170 60 170 64 170 70 C 170 76 190 78 190 86 L 190 270 C 190 276 184 278 178 278 L 42 278 C 36 278 30 276 30 270 L 30 86 C 30 78 50 76 50 70 C 50 64 50 60 50 56 C 50 56 46 56 46 52 Z"/>
    </clipPath>
  </defs>
  <ellipse cx="110" cy="180" rx="130" ry="120" fill="url(#jglow)"/>
  <path d="M 46 36 L 174 36 L 174 52 C 174 56 170 56 170 56 C 170 60 170 64 170 70 C 170 76 190 78 190 86 L 190 270 C 190 276 184 278 178 278 L 42 278 C 36 278 30 276 30 270 L 30 86 C 30 78 50 76 50 70 C 50 64 50 60 50 56 C 50 56 46 56 46 52 Z"
        fill="url(#jbody)" stroke="#d4a017" stroke-width="2.6"/>
  <rect x="30" y="160" width="160" height="118" fill="url(#jhoney)" clip-path="url(#jclip)"/>
  <g fill="none" stroke="#fde68a" stroke-width="1.4" stroke-opacity="0.55" clip-path="url(#jclip)">
    <polygon points="80,200 95,191 110,200 110,218 95,227 80,218"/>
    <polygon points="110,200 125,191 140,200 140,218 125,227 110,218"/>
    <polygon points="95,227 110,218 125,227 125,245 110,254 95,245"/>
  </g>
  <rect x="49" y="35" width="122" height="6" fill="#f59e0b"/>
  <line x1="48" y1="52" x2="172" y2="52" stroke="#d4a017" stroke-width="1.6" opacity="0.8"/>
</svg>"""


# ── Offline preview entrypoint ───────────────────────────────────────────
if __name__ == "__main__":
    import sys
    from pathlib import Path

    out_dir = Path(sys.argv[1] if len(sys.argv) > 1
                   else "/tmp/honey_pot_preview")
    out_dir.mkdir(parents=True, exist_ok=True)

    def render(name: str, fill: float, count: int,
               pulse_color=None, pulse_alpha=0.0) -> Path:
        surface = cairo.ImageSurface(cairo.FORMAT_ARGB32, CANVAS_W, CANVAS_H)
        cr = cairo.Context(surface)
        cr.set_source_rgb(*HIVE_BLACK)
        cr.paint()
        paint_pot(cr, CANVAS_W, CANVAS_H,
                  fill=fill, event_count=count,
                  pulse_color=pulse_color, pulse_alpha=pulse_alpha,
                  wobble_phase=0.6)
        path = out_dir / f"{name}.png"
        surface.write_to_png(str(path))
        return path

    render("01_empty", fill=0.0, count=0)
    render("02_half", fill=0.55, count=187,
           pulse_color=AMBER_GLOW, pulse_alpha=0.7)
    render("03_overflow", fill=0.95, count=12453,
           pulse_color=STING_RED, pulse_alpha=0.85)
    print(f"Wrote 3 previews to {out_dir}")

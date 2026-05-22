"""
Meli startup splash screen.

A ~9-second Cairo-animated intro that scales to fill the entire main
window. Plays once per launch.

Sequence:
  0.0 – 0.8s   Black hold. Anticipation.
  0.6 – 1.4s   SPLAT: a huge irregular honey blob slams onto the top of
               the screen with violent splatter droplets radiating
               outward. (Audible "splat" comes from splash.wav.)
  1.0 – 4.5s   The splat sags. Four thick honey ropes drip down from
               the underside, lengthening with gravity, accumulating
               heavy teardrops at their tips.
  4.0 – 6.0s   The four drips have come to rest at the M / E / L / I
               anchor positions; the wordmark MELI fades in directly
               beneath the drip tips, as though the honey itself wrote
               the name.
  6.0 – 7.0s   Subtitle ("honey trap command center") fades in below.
  7.0 – 8.2s   Hold so the user can read it.
  8.2 – 9.0s   Fade to black, signal splash-finished.

Design rules (per Joseph's preferences):
  * Always plays through — no skip button, no click-to-dismiss.
  * Sound is best-effort: missing audio backend or missing WAV does
    not block the splash. The visual always completes.
  * Honors `splash.enabled` and `splash.sound_enabled` config knobs
    so power users can mute or disable after the novelty wears off.
  * Emits the GObject signal `splash-finished` exactly once when the
    full duration elapses; the application waits on that signal before
    showing the lock screen / setup wizard.
"""
from __future__ import annotations

import math
import random
import subprocess
import time
from pathlib import Path

import gi
gi.require_version("Gtk", "4.0")
gi.require_version("Adw", "1")
from gi.repository import Gtk, Adw, GLib, GObject  # noqa: E402

import cairo  # noqa: E402
import structlog

from meli.config import get_config
from meli.ui.widgets.honey_pot import (
    RAW_HONEY, AMBER_GLOW, DARK_HONEY, PALE_COMB, HIVE_BLACK, COMB_PANEL,
)

log = structlog.get_logger()

# Animation tuning — all milliseconds.
FRAME_MS         = 33          # ~30 fps
TOTAL_MS         = 9000

# Phase boundaries.
HOLD_END_MS      = 600         # dark anticipation before the splat
SPLAT_HIT_MS     = 700         # impact moment — sound + max impact size
SPLAT_FULL_MS    = 1400        # splatter expansion settles by here
DRIPS_START_MS   = 1000        # drips begin to elongate from splat underside
DRIPS_FULL_MS    = 4500        # drips reach their resting length
LETTERS_START_MS = 4000        # MELI wordmark begins to fade in
LETTERS_FULL_MS  = 6000
SUBTITLE_START_MS= 6000
SUBTITLE_FULL_MS = 7000
FADE_START_MS    = 8200
FADE_END_MS      = TOTAL_MS

# Layout fractions (proportions of the window).
SPLAT_CENTER_FY  = 0.18        # vertical center of splat as fraction of h
SPLAT_RADIUS_FW  = 0.28        # base splat radius as fraction of w
LETTERS_BASELINE_FY = 0.74     # where MELI letters sit
SUBTITLE_FY      = 0.83

# Number of main drip ropes (one per letter of MELI).
DRIP_COUNT       = 4
SPLATTER_COUNT   = 22          # secondary splatter droplets flying out

SOUND_PATH = Path(__file__).resolve().parent.parent.parent / "assets" / "sounds" / "splash.wav"


# ── easing helpers ────────────────────────────────────────────────────────
def _clamp01(t: float) -> float:
    return 0.0 if t < 0.0 else (1.0 if t > 1.0 else t)


def _ease_out_cubic(t: float) -> float:
    t = _clamp01(t)
    return 1.0 - (1.0 - t) ** 3


def _ease_out_quint(t: float) -> float:
    t = _clamp01(t)
    return 1.0 - (1.0 - t) ** 5


def _ease_in_out(t: float) -> float:
    t = _clamp01(t)
    return 0.5 - 0.5 * math.cos(math.pi * t)


def _ease_in_quad(t: float) -> float:
    t = _clamp01(t)
    return t * t


# ── sound playback ────────────────────────────────────────────────────────
def _try_play_sound() -> subprocess.Popen | None:
    """Best-effort, non-blocking playback of the splash WAV."""
    cfg = get_config()
    if not cfg.get("splash", "sound_enabled", default=True):
        return None
    if not SOUND_PATH.is_file():
        log.debug("Splash sound file missing", path=str(SOUND_PATH))
        return None
    for cmd in (
        ["paplay", str(SOUND_PATH)],
        ["pw-play", str(SOUND_PATH)],
        ["aplay", "-q", str(SOUND_PATH)],
        ["ffplay", "-nodisp", "-autoexit", "-loglevel", "quiet", str(SOUND_PATH)],
        ["mpv", "--really-quiet", "--no-video", str(SOUND_PATH)],
    ):
        try:
            return subprocess.Popen(
                cmd, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
            )
        except FileNotFoundError:
            continue
    log.debug("No audio player available for splash sound")
    return None


# ── splatter droplet (flies away from impact) ────────────────────────────
class _Splatter:
    """One radial droplet flung outward by the splat impact."""

    __slots__ = ("angle", "distance", "size", "wobble", "spin_phase")

    def __init__(self, angle: float, distance: float, size: float,
                 wobble: float, spin_phase: float) -> None:
        self.angle = angle
        self.distance = distance
        self.size = size
        self.wobble = wobble
        self.spin_phase = spin_phase


# ── splash overlay widget ────────────────────────────────────────────────
class SplashOverlay(Gtk.Box):
    """Splash animation as a Gtk.Overlay child on the main window.

    Fills the entire main window with an opaque background; the
    animation scales to whatever size the parent gives us. The
    signal `splash-finished` fires exactly once at the end.
    """

    __gsignals__ = {
        "splash-finished": (GObject.SignalFlags.RUN_FIRST, None, ()),
    }

    def __init__(self) -> None:
        super().__init__(orientation=Gtk.Orientation.VERTICAL)
        try:
            self.add_css_class("meli-splash")
        except Exception:
            pass
        self.set_hexpand(True)
        self.set_vexpand(True)
        self.set_halign(Gtk.Align.FILL)
        self.set_valign(Gtk.Align.FILL)
        self.set_can_target(True)
        self.set_focusable(True)

        self._start_ms: int | None = None
        self._finished = False
        self._tick_source: int | None = None
        self._sound_proc: subprocess.Popen | None = None

        # Deterministic random for splatter — reproducible across launches.
        rng = random.Random(0xBEE1234)
        self._splatters: list[_Splatter] = []
        for _ in range(SPLATTER_COUNT):
            angle = rng.uniform(-math.pi, 0.0)  # upper hemisphere only
            # bias towards horizontal so the splatter spreads sideways
            angle = angle * 0.85 - math.pi * 0.075
            self._splatters.append(_Splatter(
                angle=angle,
                distance=rng.uniform(0.18, 0.55),  # as frac of w
                size=rng.uniform(0.006, 0.018),    # as frac of min(w,h)
                wobble=rng.uniform(0.0, 2 * math.pi),
                spin_phase=rng.uniform(0.0, 2 * math.pi),
            ))

        # Pre-roll the splat blob outline so it's irregular but stable.
        self._splat_lobes: list[tuple[float, float]] = []
        for i in range(14):
            a = (i / 14.0) * 2 * math.pi
            # Mild radial jitter — keeps the splat ugly-organic.
            r = 1.0 + rng.uniform(-0.18, 0.28)
            # Make the bottom edge fall further (gravity already pulling).
            if math.sin(a) > 0.3:
                r += rng.uniform(0.05, 0.25)
            self._splat_lobes.append((a, r))

        # Drip rope side-tendrils for organic edge sag.
        self._drip_jitter = [rng.uniform(-0.04, 0.04) for _ in range(DRIP_COUNT)]
        self._drip_phase = [rng.uniform(0.0, 2 * math.pi) for _ in range(DRIP_COUNT)]

        # Single drawing area — fills the whole window and we scale to it.
        self._area = Gtk.DrawingArea()
        self._area.set_hexpand(True)
        self._area.set_vexpand(True)
        self._area.set_draw_func(self._on_draw)
        self.append(self._area)

        self.connect("map", self._on_mapped)
        self.connect("unmap", self._cleanup)
        self.connect("destroy", self._cleanup)

    # ── lifecycle ─────────────────────────────────────────────────────
    def _on_mapped(self, *_args) -> None:
        if self._start_ms is not None:
            return
        self._start_ms = int(time.monotonic() * 1000)
        # Delay the sound a touch so it lands on the splat impact frame.
        GLib.timeout_add(max(0, SPLAT_HIT_MS - 60),
                         lambda: (self._fire_sound(), False)[1])
        self._tick_source = GLib.timeout_add(FRAME_MS, self._on_tick)

    def _fire_sound(self) -> None:
        if self._finished:
            return
        self._sound_proc = _try_play_sound()

    def _on_tick(self) -> bool:
        if self._start_ms is None:
            return True
        elapsed = int(time.monotonic() * 1000) - self._start_ms
        self._area.queue_draw()
        if elapsed >= TOTAL_MS:
            self._finish()
            return False
        return True

    def _finish(self) -> None:
        if self._finished:
            return
        self._finished = True
        self._stop_tick()
        try:
            self.emit("splash-finished")
        except Exception as e:
            log.debug("splash-finished emit failed", error=str(e))

    def _stop_tick(self) -> None:
        if self._tick_source is not None:
            try:
                GLib.source_remove(self._tick_source)
            except Exception:
                pass
            self._tick_source = None

    def _cleanup(self, *_args) -> None:
        self._stop_tick()
        proc = self._sound_proc
        self._sound_proc = None
        if proc is not None and proc.poll() is None:
            try:
                proc.terminate()
            except Exception:
                pass

    # ── drawing ───────────────────────────────────────────────────────
    def _on_draw(self, _area: Gtk.DrawingArea, ctx: cairo.Context,
                 w: int, h: int) -> None:
        if self._start_ms is None:
            elapsed = 0
        else:
            elapsed = int(time.monotonic() * 1000) - self._start_ms
        elapsed = max(0, min(TOTAL_MS, elapsed))

        # 1. Opaque background — vertical gradient hive-black → comb-panel.
        bg = cairo.LinearGradient(0, 0, 0, h)
        bg.add_color_stop_rgb(0.0, *HIVE_BLACK)
        bg.add_color_stop_rgb(1.0, *COMB_PANEL)
        ctx.set_source(bg)
        ctx.rectangle(0, 0, w, h)
        ctx.fill()

        # Vignette to focus the eye on the center action.
        vignette = cairo.RadialGradient(
            w / 2, h * 0.35, max(w, h) * 0.18,
            w / 2, h * 0.35, max(w, h) * 0.85,
        )
        vignette.add_color_stop_rgba(0.0, 0, 0, 0, 0.0)
        vignette.add_color_stop_rgba(1.0, 0, 0, 0, 0.55)
        ctx.set_source(vignette)
        ctx.rectangle(0, 0, w, h)
        ctx.fill()

        if elapsed < HOLD_END_MS:
            # Just the dark hold.
            return

        # 2. The splat blob — anchored at the top, ballooning into place.
        splat_t = (elapsed - HOLD_END_MS) / max(1, SPLAT_FULL_MS - HOLD_END_MS)
        splat_t = _clamp01(splat_t)
        # Overshoot then settle for an impact feel.
        splat_size = _ease_out_quint(splat_t)
        if splat_t < 0.45:
            splat_size *= 1.0 + 0.18 * math.sin(splat_t / 0.45 * math.pi)
        cx = w * 0.5
        cy = h * SPLAT_CENTER_FY
        base_r = min(w, h) * SPLAT_RADIUS_FW

        # 3. Splatter droplets fly outward as the splat hits.
        if elapsed >= SPLAT_HIT_MS - 200:
            self._draw_splatter(ctx, w, h, cx, cy, base_r, elapsed)

        # 4. The splat itself (drawn after splatter so it sits on top).
        if splat_size > 0.02:
            self._draw_splat(ctx, cx, cy, base_r * splat_size, w, h, elapsed)

        # 5. Drip ropes hanging from the splat to the letter positions.
        if elapsed >= DRIPS_START_MS:
            self._draw_drips(ctx, w, h, cx, cy, base_r, elapsed)

        # 6. MELI wordmark + subtitle fading in.
        if elapsed >= LETTERS_START_MS:
            letters_t = (elapsed - LETTERS_START_MS) / max(
                1, LETTERS_FULL_MS - LETTERS_START_MS,
            )
            self._draw_wordmark(ctx, w, h, _ease_out_cubic(letters_t))

        if elapsed >= SUBTITLE_START_MS:
            sub_t = (elapsed - SUBTITLE_START_MS) / max(
                1, SUBTITLE_FULL_MS - SUBTITLE_START_MS,
            )
            self._draw_subtitle(ctx, w, h, _ease_out_cubic(sub_t))

        # 7. Final fade-to-black.
        if elapsed >= FADE_START_MS:
            fade_t = (elapsed - FADE_START_MS) / max(
                1, FADE_END_MS - FADE_START_MS,
            )
            ctx.set_source_rgba(*HIVE_BLACK, _ease_in_out(fade_t))
            ctx.rectangle(0, 0, w, h)
            ctx.fill()

    # ── splat (the big blob) ──────────────────────────────────────────
    def _draw_splat(self, ctx: cairo.Context, cx: float, cy: float,
                    radius: float, w: int, h: int, elapsed: int) -> None:
        # Halo glow first so the blob sits inside a warm aura.
        halo = cairo.RadialGradient(cx, cy, radius * 0.4,
                                    cx, cy, radius * 1.9)
        halo.add_color_stop_rgba(0.0, *AMBER_GLOW, 0.55)
        halo.add_color_stop_rgba(1.0, *AMBER_GLOW, 0.0)
        ctx.set_source(halo)
        ctx.arc(cx, cy, radius * 1.9, 0, 2 * math.pi)
        ctx.fill()

        # The blob: closed Bezier ring of the pre-rolled lobes, with a
        # slow wobble so the splat looks gooey-alive, not frozen.
        wobble = math.sin(elapsed / 700.0) * 0.04
        # Anchor the splat hard against the top so it looks adhered.
        top_pull = 0.55
        points: list[tuple[float, float]] = []
        for (a, r) in self._splat_lobes:
            rr = (r + wobble) * radius
            # Squash slightly vertically so it ovals across the top.
            x = cx + math.cos(a) * rr
            y = cy + math.sin(a) * rr * 1.05
            # Pull the upper half flatly against the top edge.
            if math.sin(a) < 0:
                y = cy + math.sin(a) * rr * top_pull - radius * 0.05
            points.append((x, y))

        ctx.move_to(*points[0])
        n = len(points)
        for i in range(n):
            p0 = points[i]
            p1 = points[(i + 1) % n]
            # Catmull-Rom-ish smoothing: midpoint with curve_to.
            mx, my = (p0[0] + p1[0]) / 2, (p0[1] + p1[1]) / 2
            ctx.curve_to(p0[0], p0[1], p0[0], p0[1], mx, my)
        ctx.close_path()
        # Fill — radial honey gradient.
        fill = cairo.RadialGradient(cx, cy - radius * 0.3, radius * 0.1,
                                    cx, cy, radius * 1.1)
        fill.add_color_stop_rgb(0.0, *AMBER_GLOW)
        fill.add_color_stop_rgb(0.55, *RAW_HONEY)
        fill.add_color_stop_rgb(1.0, *DARK_HONEY)
        ctx.set_source(fill)
        ctx.fill_preserve()
        # Rim highlight.
        ctx.set_source_rgba(*PALE_COMB, 0.35)
        ctx.set_line_width(max(1.0, radius * 0.015))
        ctx.stroke()

        # Specular reflection on the upper-left.
        ctx.save()
        ctx.translate(cx, cy)
        ctx.scale(1.0, 0.55)
        spec = cairo.RadialGradient(-radius * 0.25, -radius * 0.45, 0,
                                    -radius * 0.25, -radius * 0.45, radius * 0.45)
        spec.add_color_stop_rgba(0.0, *PALE_COMB, 0.55)
        spec.add_color_stop_rgba(1.0, *PALE_COMB, 0.0)
        ctx.set_source(spec)
        ctx.arc(-radius * 0.25, -radius * 0.45, radius * 0.45, 0, 2 * math.pi)
        ctx.fill()
        ctx.restore()

    # ── splatter droplets (flying away from impact) ───────────────────
    def _draw_splatter(self, ctx: cairo.Context, w: int, h: int,
                       cx: float, cy: float, base_r: float,
                       elapsed: int) -> None:
        # Splatter has two phases:
        #   - shoot outward (0..400ms after hit)
        #   - settle / fade (400..1200ms after hit, then gone)
        for s in self._splatters:
            age = elapsed - SPLAT_HIT_MS + 200
            if age < 0:
                continue
            travel_t = _clamp01(age / 700.0)
            # Distance travelled and arc-droop (gravity).
            dist = s.distance * w * _ease_out_quint(travel_t)
            x = cx + math.cos(s.angle) * dist
            y = cy + math.sin(s.angle) * dist + (
                _ease_in_quad(travel_t) * h * 0.12
            )
            # Fade after they stop.
            fade = _clamp01((age - 700) / 800.0)
            alpha = (1.0 - fade) * 0.95
            if alpha <= 0.02:
                continue
            r = s.size * min(w, h)
            # Glow.
            halo = cairo.RadialGradient(x, y, 0, x, y, r * 3.0)
            halo.add_color_stop_rgba(0.0, *AMBER_GLOW, alpha * 0.5)
            halo.add_color_stop_rgba(1.0, *AMBER_GLOW, 0.0)
            ctx.set_source(halo)
            ctx.arc(x, y, r * 3.0, 0, 2 * math.pi)
            ctx.fill()
            # Body.
            ctx.set_source_rgba(*RAW_HONEY, alpha)
            ctx.arc(x, y, r, 0, 2 * math.pi)
            ctx.fill()
            # Highlight.
            ctx.set_source_rgba(*PALE_COMB, alpha * 0.6)
            ctx.arc(x - r * 0.3, y - r * 0.3, r * 0.3, 0, 2 * math.pi)
            ctx.fill()

    # ── drip ropes (M E L I anchors) ──────────────────────────────────
    def _drip_anchor_x(self, w: int, idx: int) -> float:
        """X position for drip idx ∈ [0, DRIP_COUNT). Spaced like MELI."""
        # Evenly spread across the central 56% of the screen width.
        span = w * 0.56
        start = (w - span) / 2.0
        gap = span / (DRIP_COUNT - 1)
        return start + idx * gap

    def _draw_drips(self, ctx: cairo.Context, w: int, h: int,
                    splat_cx: float, splat_cy: float, base_r: float,
                    elapsed: int) -> None:
        drip_t = _clamp01(
            (elapsed - DRIPS_START_MS) / max(1, DRIPS_FULL_MS - DRIPS_START_MS)
        )
        # Each drip eases out at its own rate so they don't move in lockstep.
        for i in range(DRIP_COUNT):
            stagger = i * 0.08
            local_t = _clamp01((drip_t - stagger) / max(0.01, 1.0 - stagger))
            length_t = _ease_out_cubic(local_t)

            ax = self._drip_anchor_x(w, i)
            ay = h * LETTERS_BASELINE_FY - h * 0.04  # tip rests just above letters
            # Start: a point on the underside of the splat near x=ax.
            sx = splat_cx + (ax - splat_cx) * 0.45 + self._drip_jitter[i] * w
            sy = splat_cy + base_r * 0.82

            tip_y = sy + (ay - sy) * length_t
            # Subtle horizontal sway for goo realism.
            sway = math.sin(elapsed / 600.0 + self._drip_phase[i]) * w * 0.004
            tip_x = ax + sway

            self._draw_drip_rope(ctx, sx, sy, tip_x, tip_y, w, h, length_t)

    def _draw_drip_rope(self, ctx: cairo.Context, sx: float, sy: float,
                        tx: float, ty: float, w: int, h: int,
                        length_t: float) -> None:
        # Rope width tapers from thick at the splat to thin in the middle,
        # then bulges at the teardrop tip.
        thick_top = max(3.0, min(w, h) * 0.018)
        thick_mid = thick_top * 0.55
        # Vertical Bezier control points for a slight S-curve.
        mid_y = (sy + ty) / 2.0
        cp1 = (sx + (tx - sx) * 0.25, sy + (mid_y - sy) * 0.6)
        cp2 = (tx + (sx - tx) * 0.25, ty - (ty - mid_y) * 0.6)

        # Approximate the rope by stroking the curve in two passes:
        # a wide pass with the thick gradient, then a narrower highlight.
        ctx.save()
        # Outer halo so the rope reads even on dark bg.
        ctx.set_source_rgba(*AMBER_GLOW, 0.35)
        ctx.set_line_width(thick_top * 2.2)
        ctx.set_line_cap(cairo.LINE_CAP_ROUND)
        ctx.move_to(sx, sy)
        ctx.curve_to(*cp1, *cp2, tx, ty)
        ctx.stroke()

        # Main rope body.
        body = cairo.LinearGradient(sx, sy, tx, ty)
        body.add_color_stop_rgb(0.0, *RAW_HONEY)
        body.add_color_stop_rgb(0.6, *AMBER_GLOW)
        body.add_color_stop_rgb(1.0, *DARK_HONEY)
        ctx.set_source(body)
        ctx.set_line_width(max(thick_mid, thick_top * (1.0 - 0.4 * length_t)))
        ctx.set_line_cap(cairo.LINE_CAP_ROUND)
        ctx.move_to(sx, sy)
        ctx.curve_to(*cp1, *cp2, tx, ty)
        ctx.stroke()

        # Highlight stripe along the rope.
        ctx.set_source_rgba(*PALE_COMB, 0.32)
        ctx.set_line_width(max(1.0, thick_mid * 0.32))
        ctx.move_to(sx - thick_top * 0.18, sy + 2)
        ctx.curve_to(
            cp1[0] - thick_top * 0.10, cp1[1],
            cp2[0] - thick_top * 0.10, cp2[1],
            tx - thick_top * 0.10, ty - 4,
        )
        ctx.stroke()
        ctx.restore()

        # Teardrop bulb at the tip (grows as drip nears full length).
        bulb_r = max(2.5, thick_top * (0.8 + 1.4 * length_t))
        # Glow.
        halo = cairo.RadialGradient(tx, ty, 0, tx, ty, bulb_r * 2.4)
        halo.add_color_stop_rgba(0.0, *AMBER_GLOW, 0.55)
        halo.add_color_stop_rgba(1.0, *AMBER_GLOW, 0.0)
        ctx.set_source(halo)
        ctx.arc(tx, ty, bulb_r * 2.4, 0, 2 * math.pi)
        ctx.fill()
        # Pear-shaped body.
        ctx.move_to(tx, ty - bulb_r * 1.4)
        ctx.curve_to(
            tx + bulb_r * 0.95, ty - bulb_r * 0.5,
            tx + bulb_r * 1.05, ty + bulb_r * 0.7,
            tx,                  ty + bulb_r * 1.05,
        )
        ctx.curve_to(
            tx - bulb_r * 1.05, ty + bulb_r * 0.7,
            tx - bulb_r * 0.95, ty - bulb_r * 0.5,
            tx,                  ty - bulb_r * 1.4,
        )
        ctx.close_path()
        grad = cairo.LinearGradient(tx, ty - bulb_r, tx, ty + bulb_r)
        grad.add_color_stop_rgb(0.0, *AMBER_GLOW)
        grad.add_color_stop_rgb(1.0, *DARK_HONEY)
        ctx.set_source(grad)
        ctx.fill()
        # Specular.
        ctx.set_source_rgba(*PALE_COMB, 0.6)
        ctx.arc(tx - bulb_r * 0.4, ty - bulb_r * 0.45,
                bulb_r * 0.28, 0, 2 * math.pi)
        ctx.fill()

    # ── wordmark + subtitle ───────────────────────────────────────────
    def _draw_wordmark(self, ctx: cairo.Context, w: int, h: int,
                       alpha: float) -> None:
        if alpha <= 0.01:
            return
        ctx.save()
        # Scale font with window — feel big and proud.
        font_px = max(48.0, min(w, h) * 0.13)
        ctx.select_font_face(
            "Sans", cairo.FONT_SLANT_NORMAL, cairo.FONT_WEIGHT_BOLD,
        )
        ctx.set_font_size(font_px)
        title = "M E L I"
        extents = ctx.text_extents(title)
        tx = (w - extents.width) / 2.0 - extents.x_bearing
        ty = h * LETTERS_BASELINE_FY + font_px * 0.05

        # Soft amber glow halo behind the text.
        ctx.set_source_rgba(*AMBER_GLOW, alpha * 0.65)
        for ox, oy in ((-3, 0), (3, 0), (0, -3), (0, 3),
                       (-2, -2), (2, -2), (-2, 2), (2, 2)):
            ctx.move_to(tx + ox, ty + oy)
            ctx.show_text(title)
        # Main fill — warm amber, not pale, so it reads as molten honey.
        ctx.set_source_rgba(*AMBER_GLOW, alpha)
        ctx.move_to(tx, ty)
        ctx.show_text(title)
        # Pale highlight on top edge for sheen.
        ctx.set_source_rgba(*PALE_COMB, alpha * 0.7)
        ctx.move_to(tx, ty - font_px * 0.04)
        ctx.show_text(title)
        ctx.restore()

    def _draw_subtitle(self, ctx: cairo.Context, w: int, h: int,
                       alpha: float) -> None:
        if alpha <= 0.01:
            return
        ctx.save()
        font_px = max(13.0, min(w, h) * 0.024)
        ctx.select_font_face(
            "Sans", cairo.FONT_SLANT_NORMAL, cairo.FONT_WEIGHT_NORMAL,
        )
        ctx.set_font_size(font_px)
        sub = "honey trap command center"
        extents = ctx.text_extents(sub)
        tx = (w - extents.width) / 2.0 - extents.x_bearing
        ty = h * SUBTITLE_FY
        # Slight glow.
        ctx.set_source_rgba(*AMBER_GLOW, alpha * 0.4)
        for ox, oy in ((-1, 0), (1, 0), (0, -1), (0, 1)):
            ctx.move_to(tx + ox, ty + oy)
            ctx.show_text(sub)
        ctx.set_source_rgba(*RAW_HONEY, alpha * 0.95)
        ctx.move_to(tx, ty)
        ctx.show_text(sub)
        ctx.restore()

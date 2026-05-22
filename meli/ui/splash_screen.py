"""
Meli startup splash screen.

~9 seconds. Honey hits the top of the screen, holds, then slowly oozes
downward in real gooey vertical drips, and the MELI wordmark fades in
centered below once the drips are flowing.

Sequence:
  0.0 – 0.6s   Dark hold (anticipation).
  0.4 – 1.6s   SPLAT: a wide irregular honey blob slams into the top of
               the screen and spreads across roughly the top third.
               (Audible "splat" lands on impact.)
  1.4 – 5.8s   The underside of the splat starts to sag. Six gooey
               vertical strands ooze straight down, narrowing in the
               middle, bulging into heavy teardrop tips. Each drip
               eases out on its own clock so they don't move in lockstep.
  5.0 – 6.8s   MELI wordmark fades in centered below the drip field.
  6.5 – 7.4s   Subtitle fades in.
  7.4 – 8.4s   Hold so the user can read it.
  8.4 – 9.0s   Fade to black, emit splash-finished.

Design rules (per Joseph's preferences):
  * Always plays through — no skip button, no click-to-dismiss.
  * Sound is best-effort: missing audio backend or missing WAV does
    not block the splash. The visual always completes.
  * Honors `splash.enabled` and `splash.sound_enabled` config knobs.
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
HOLD_END_MS      = 600
SPLAT_HIT_MS     = 750
SPLAT_FULL_MS    = 1600
DRIPS_START_MS   = 1400
DRIPS_FULL_MS    = 5800
LETTERS_START_MS = 5000
LETTERS_FULL_MS  = 6800
SUBTITLE_START_MS= 6500
SUBTITLE_FULL_MS = 7400
FADE_START_MS    = 8400
FADE_END_MS      = TOTAL_MS

# Splat geometry (fractions of window size).
SPLAT_TOP_PAD_FY   = -0.10     # negative — pull the top off-screen so blob hugs top edge
SPLAT_BOTTOM_FY    = 0.34      # underside sits ~1/3 down the window
SPLAT_WIDTH_FW     = 0.72      # span ~72% of window width
SPLATTER_COUNT     = 26

# Drip layout.
DRIP_COUNT          = 6
DRIP_TOP_Y_FY       = 0.30     # where strands attach (just inside splat underside)
DRIP_REST_BOTTOM_FY = 0.66     # how far down the longest drip reaches
DRIP_FIELD_WIDTH_FW = 0.66     # drips spread across central 66% of width

# Wordmark / subtitle layout.
LETTERS_BASELINE_FY = 0.84
SUBTITLE_FY         = 0.91

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


def _ease_in_cubic(t: float) -> float:
    t = _clamp01(t)
    return t * t * t


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
    __slots__ = ("angle", "distance", "size", "wobble")

    def __init__(self, angle: float, distance: float, size: float, wobble: float) -> None:
        self.angle = angle
        self.distance = distance
        self.size = size
        self.wobble = wobble


# ── one gooey vertical drip strand ───────────────────────────────────────
class _Drip:
    """A vertical honey strand: anchored to the splat underside, oozing down."""

    __slots__ = (
        "x_frac",         # horizontal anchor on the splat underside (0..1 of field)
        "x_offset_fw",    # tiny horizontal jitter so they don't line up
        "max_length_fh",  # final length as fraction of window height
        "width_top_fw",   # thickness at attachment (frac of window width)
        "width_mid_fw",   # thinnest point in the middle
        "bulb_factor",    # multiplier for the teardrop bulb at the tip
        "start_t",        # phase offset (fraction of drip phase) before it starts moving
        "sway_phase",     # phase offset for the slight horizontal sway
        "sway_amp",       # sway amplitude (frac of window width)
    )

    def __init__(self, x_frac, x_offset_fw, max_length_fh, width_top_fw,
                 width_mid_fw, bulb_factor, start_t, sway_phase, sway_amp):
        self.x_frac = x_frac
        self.x_offset_fw = x_offset_fw
        self.max_length_fh = max_length_fh
        self.width_top_fw = width_top_fw
        self.width_mid_fw = width_mid_fw
        self.bulb_factor = bulb_factor
        self.start_t = start_t
        self.sway_phase = sway_phase
        self.sway_amp = sway_amp


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

        rng = random.Random(0xBEE5EED)

        # Splat outline: 18 lobes around a squashed top-anchored oval.
        self._splat_lobes: list[tuple[float, float]] = []
        for i in range(18):
            a = (i / 18.0) * 2 * math.pi
            r = 1.0 + rng.uniform(-0.18, 0.32)
            # Make the bottom lobes hang heavier (gravity).
            if math.sin(a) > 0.2:
                r += rng.uniform(0.05, 0.30)
            self._splat_lobes.append((a, r))

        # Splatter droplets.
        self._splatters: list[_Splatter] = []
        for _ in range(SPLATTER_COUNT):
            # Upper hemisphere only, biased downward-sideways so they
            # spray realistically off the impact.
            angle = rng.uniform(0.15 * math.pi, 0.85 * math.pi) + math.pi  # 180..360 = down-half
            # Convert back to standard math angle: top hemisphere is
            # negative-sin space, but we want sideways spray, so:
            angle = rng.uniform(-0.95 * math.pi, -0.05 * math.pi)
            self._splatters.append(_Splatter(
                angle=angle,
                distance=rng.uniform(0.22, 0.58),
                size=rng.uniform(0.005, 0.016),
                wobble=rng.uniform(0.0, 2 * math.pi),
            ))

        # Drips: 6 strands across the splat underside.
        # Slight randomness in length, thickness, start time gives a
        # natural drip cascade — none of the drips look identical.
        self._drips: list[_Drip] = []
        for i in range(DRIP_COUNT):
            x_frac = (i + 0.5) / DRIP_COUNT
            self._drips.append(_Drip(
                x_frac=x_frac,
                x_offset_fw=rng.uniform(-0.015, 0.015),
                max_length_fh=rng.uniform(0.26, 0.36),
                width_top_fw=rng.uniform(0.022, 0.034),
                width_mid_fw=rng.uniform(0.009, 0.014),
                bulb_factor=rng.uniform(1.5, 2.2),
                start_t=rng.uniform(0.0, 0.18),
                sway_phase=rng.uniform(0.0, 2 * math.pi),
                sway_amp=rng.uniform(0.001, 0.004),
            ))

        # Single drawing area — fills the whole window.
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
        # Delay the sound to land on the splat impact frame.
        GLib.timeout_add(max(0, SPLAT_HIT_MS - 80),
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

        # Opaque background — vertical gradient hive-black → comb-panel.
        bg = cairo.LinearGradient(0, 0, 0, h)
        bg.add_color_stop_rgb(0.0, *HIVE_BLACK)
        bg.add_color_stop_rgb(1.0, *COMB_PANEL)
        ctx.set_source(bg)
        ctx.rectangle(0, 0, w, h)
        ctx.fill()

        # Soft vignette to focus the eye on the action.
        vignette = cairo.RadialGradient(
            w / 2, h * 0.35, max(w, h) * 0.22,
            w / 2, h * 0.35, max(w, h) * 0.95,
        )
        vignette.add_color_stop_rgba(0.0, 0, 0, 0, 0.0)
        vignette.add_color_stop_rgba(1.0, 0, 0, 0, 0.55)
        ctx.set_source(vignette)
        ctx.rectangle(0, 0, w, h)
        ctx.fill()

        if elapsed < HOLD_END_MS:
            return

        # 1. Splatter droplets fly outward from the impact point.
        if elapsed >= SPLAT_HIT_MS - 200:
            self._draw_splatter(ctx, w, h, elapsed)

        # 2. The splat itself: huge irregular blob hugging the top edge.
        splat_t = _clamp01(
            (elapsed - HOLD_END_MS) / max(1, SPLAT_FULL_MS - HOLD_END_MS)
        )
        splat_size = _ease_out_quint(splat_t)
        # A subtle wobble after impact (settling honey).
        if splat_t > 0.6:
            settle = _ease_out_cubic((splat_t - 0.6) / 0.4)
            splat_size *= 1.0 + 0.04 * math.sin(settle * math.pi * 3.0)
        if splat_size > 0.02:
            self._draw_splat(ctx, w, h, splat_size, elapsed)

        # 3. Drip strands oozing down from the splat underside.
        if elapsed >= DRIPS_START_MS:
            drip_t = _clamp01(
                (elapsed - DRIPS_START_MS) / max(1, DRIPS_FULL_MS - DRIPS_START_MS)
            )
            self._draw_drips(ctx, w, h, drip_t, elapsed)

        # 4. MELI wordmark fading in.
        if elapsed >= LETTERS_START_MS:
            letters_t = _clamp01(
                (elapsed - LETTERS_START_MS) / max(1, LETTERS_FULL_MS - LETTERS_START_MS)
            )
            self._draw_wordmark(ctx, w, h, _ease_out_cubic(letters_t))

        if elapsed >= SUBTITLE_START_MS:
            sub_t = _clamp01(
                (elapsed - SUBTITLE_START_MS) / max(1, SUBTITLE_FULL_MS - SUBTITLE_START_MS)
            )
            self._draw_subtitle(ctx, w, h, _ease_out_cubic(sub_t))

        # 5. Final fade-to-black.
        if elapsed >= FADE_START_MS:
            fade_t = (elapsed - FADE_START_MS) / max(1, FADE_END_MS - FADE_START_MS)
            ctx.set_source_rgba(*HIVE_BLACK, _ease_in_out(fade_t))
            ctx.rectangle(0, 0, w, h)
            ctx.fill()

    # ── splat blob ────────────────────────────────────────────────────
    def _draw_splat(self, ctx: cairo.Context, w: int, h: int,
                    size_factor: float, elapsed: int) -> None:
        cx = w * 0.5
        # Top is pulled slightly above the window so the splat looks
        # adhered to the top edge — it "hit the screen and stuck".
        top_y = h * SPLAT_TOP_PAD_FY
        bot_y = h * SPLAT_BOTTOM_FY * size_factor + h * (SPLAT_TOP_PAD_FY * (1 - size_factor))
        # Half-extents of the splat oval.
        rx = (w * SPLAT_WIDTH_FW * 0.5) * size_factor
        ry = (bot_y - top_y) * 0.5
        cy = (top_y + bot_y) * 0.5
        wobble = math.sin(elapsed / 800.0) * 0.025

        # Halo glow first.
        halo = cairo.RadialGradient(cx, cy, max(rx, ry) * 0.3,
                                    cx, cy, max(rx, ry) * 1.8)
        halo.add_color_stop_rgba(0.0, *AMBER_GLOW, 0.55)
        halo.add_color_stop_rgba(1.0, *AMBER_GLOW, 0.0)
        ctx.set_source(halo)
        ctx.arc(cx, cy, max(rx, ry) * 1.8, 0, 2 * math.pi)
        ctx.fill()

        # Build the lobed outline.
        points: list[tuple[float, float]] = []
        for (a, r) in self._splat_lobes:
            rr = r + wobble
            x = cx + math.cos(a) * rx * rr
            y = cy + math.sin(a) * ry * rr
            # Pin the upper half to the top edge so it looks splatted.
            if math.sin(a) < 0:
                y = top_y + (cy - top_y) * 0.2 * (1.0 + math.cos(a) * 0.1)
            points.append((x, y))

        ctx.move_to(*points[0])
        n = len(points)
        for i in range(n):
            p0 = points[i]
            p1 = points[(i + 1) % n]
            mx, my = (p0[0] + p1[0]) / 2, (p0[1] + p1[1]) / 2
            ctx.curve_to(p0[0], p0[1], p0[0], p0[1], mx, my)
        ctx.close_path()

        fill = cairo.RadialGradient(cx, cy - ry * 0.3, ry * 0.1,
                                    cx, cy, max(rx, ry))
        fill.add_color_stop_rgb(0.0, *AMBER_GLOW)
        fill.add_color_stop_rgb(0.55, *RAW_HONEY)
        fill.add_color_stop_rgb(1.0, *DARK_HONEY)
        ctx.set_source(fill)
        ctx.fill_preserve()
        ctx.set_source_rgba(*PALE_COMB, 0.30)
        ctx.set_line_width(max(1.0, min(rx, ry) * 0.012))
        ctx.stroke()

        # Specular reflection upper-left.
        ctx.save()
        ctx.translate(cx, cy)
        ctx.scale(1.0, ry / max(rx, 1.0))
        spec = cairo.RadialGradient(-rx * 0.25, -rx * 0.45, 0,
                                    -rx * 0.25, -rx * 0.45, rx * 0.5)
        spec.add_color_stop_rgba(0.0, *PALE_COMB, 0.5)
        spec.add_color_stop_rgba(1.0, *PALE_COMB, 0.0)
        ctx.set_source(spec)
        ctx.arc(-rx * 0.25, -rx * 0.45, rx * 0.5, 0, 2 * math.pi)
        ctx.fill()
        ctx.restore()

    # ── splatter droplets ─────────────────────────────────────────────
    def _draw_splatter(self, ctx: cairo.Context, w: int, h: int,
                       elapsed: int) -> None:
        cx = w * 0.5
        cy = h * 0.06  # impact origin near the very top of the screen
        for s in self._splatters:
            age = elapsed - SPLAT_HIT_MS + 200
            if age < 0:
                continue
            travel_t = _clamp01(age / 800.0)
            dist = s.distance * w * _ease_out_quint(travel_t)
            x = cx + math.cos(s.angle) * dist
            y = cy + math.sin(s.angle) * dist + (
                _ease_in_quad(travel_t) * h * 0.18
            )
            fade = _clamp01((age - 800) / 900.0)
            alpha = (1.0 - fade) * 0.9
            if alpha <= 0.02:
                continue
            r = s.size * min(w, h)
            halo = cairo.RadialGradient(x, y, 0, x, y, r * 3.0)
            halo.add_color_stop_rgba(0.0, *AMBER_GLOW, alpha * 0.5)
            halo.add_color_stop_rgba(1.0, *AMBER_GLOW, 0.0)
            ctx.set_source(halo)
            ctx.arc(x, y, r * 3.0, 0, 2 * math.pi)
            ctx.fill()
            ctx.set_source_rgba(*RAW_HONEY, alpha)
            ctx.arc(x, y, r, 0, 2 * math.pi)
            ctx.fill()
            ctx.set_source_rgba(*PALE_COMB, alpha * 0.55)
            ctx.arc(x - r * 0.3, y - r * 0.3, r * 0.3, 0, 2 * math.pi)
            ctx.fill()

    # ── drip strands (the real gooey vertical drips) ──────────────────
    def _draw_drips(self, ctx: cairo.Context, w: int, h: int,
                    drip_t: float, elapsed: int) -> None:
        field_start_x = (w - w * DRIP_FIELD_WIDTH_FW) / 2.0
        field_w = w * DRIP_FIELD_WIDTH_FW
        top_y = h * DRIP_TOP_Y_FY

        for d in self._drips:
            # Per-drip eased timeline (each starts a touch later).
            local_t = _clamp01((drip_t - d.start_t) / max(0.01, 1.0 - d.start_t))
            length_t = _ease_in_out(local_t)

            anchor_x = field_start_x + d.x_frac * field_w + d.x_offset_fw * w
            # Slight sway as it hangs.
            sway = math.sin(elapsed / 900.0 + d.sway_phase) * d.sway_amp * w

            length = d.max_length_fh * h * length_t
            tip_y = top_y + length

            w_top  = d.width_top_fw * w
            w_mid  = d.width_mid_fw * w
            bulb_r = max(2.0, w_mid * d.bulb_factor)

            self._draw_drip_strand(
                ctx, anchor_x + sway, top_y, tip_y,
                w_top, w_mid, bulb_r, length_t,
            )

    def _draw_drip_strand(self, ctx: cairo.Context, cx: float, top_y: float,
                          tip_y: float, w_top: float, w_mid: float,
                          bulb_r: float, length_t: float) -> None:
        """Draw a single vertical gooey drip:
            wide at top → narrowest in the middle → bulges into a teardrop tip.
        Built as a single closed Cairo path filled with a vertical gradient.
        """
        if tip_y - top_y < 1.0:
            return

        mid_y = top_y + (tip_y - top_y) * 0.55
        # Where the bulb starts to swell — about 80% down.
        bulb_top_y = top_y + (tip_y - top_y) * 0.78

        # Edges:
        #   left:  top -> mid (narrows) -> bulb_top (narrows more) -> tip
        #   right: mirror
        # We use Bezier curve_to for organic curvature.

        # Halo / glow behind the strand.
        ctx.save()
        ctx.set_line_join(cairo.LINE_JOIN_ROUND)
        ctx.set_line_cap(cairo.LINE_CAP_ROUND)

        # Outer halo (a fatter, very translucent version of the same shape).
        ctx.move_to(cx - w_top * 0.6, top_y)
        ctx.curve_to(
            cx - w_top * 0.55, top_y + (mid_y - top_y) * 0.4,
            cx - w_mid * 1.3,  top_y + (mid_y - top_y) * 0.8,
            cx - w_mid * 1.0,  mid_y,
        )
        ctx.curve_to(
            cx - w_mid * 1.0,  mid_y + (bulb_top_y - mid_y) * 0.5,
            cx - bulb_r * 0.6, bulb_top_y - bulb_r * 0.2,
            cx - bulb_r * 0.95, bulb_top_y + bulb_r * 0.3,
        )
        # bulb left side -> tip
        ctx.curve_to(
            cx - bulb_r * 1.05, tip_y - bulb_r * 0.2,
            cx - bulb_r * 0.5,  tip_y + bulb_r * 0.7,
            cx,                  tip_y + bulb_r * 0.95,
        )
        # bulb right side, mirror
        ctx.curve_to(
            cx + bulb_r * 0.5,  tip_y + bulb_r * 0.7,
            cx + bulb_r * 1.05, tip_y - bulb_r * 0.2,
            cx + bulb_r * 0.95, bulb_top_y + bulb_r * 0.3,
        )
        ctx.curve_to(
            cx + bulb_r * 0.6, bulb_top_y - bulb_r * 0.2,
            cx + w_mid * 1.0,  mid_y + (bulb_top_y - mid_y) * 0.5,
            cx + w_mid * 1.0,  mid_y,
        )
        ctx.curve_to(
            cx + w_mid * 1.3,  top_y + (mid_y - top_y) * 0.8,
            cx + w_top * 0.55, top_y + (mid_y - top_y) * 0.4,
            cx + w_top * 0.6,  top_y,
        )
        ctx.close_path()
        ctx.set_source_rgba(*AMBER_GLOW, 0.30)
        # Stash the path, save before we fill — we want to reuse it for the body.
        # Cairo doesn't let us reuse a path after fill, so we copy via cairo.Path.
        path_copy = ctx.copy_path()
        ctx.fill()

        # Main strand body — same shape, vertical honey gradient.
        ctx.append_path(path_copy)
        body = cairo.LinearGradient(cx, top_y, cx, tip_y + bulb_r)
        body.add_color_stop_rgb(0.0, *RAW_HONEY)
        body.add_color_stop_rgb(0.5, *AMBER_GLOW)
        body.add_color_stop_rgb(1.0, *DARK_HONEY)
        ctx.set_source(body)
        ctx.fill_preserve()

        # Rim highlight along the body silhouette.
        ctx.set_source_rgba(*PALE_COMB, 0.18)
        ctx.set_line_width(max(0.8, w_mid * 0.20))
        ctx.stroke()
        ctx.restore()

        # Inner specular sheen — a thin pale line down the left side
        # of the strand, brightest just below the attachment.
        ctx.save()
        ctx.set_source_rgba(*PALE_COMB, 0.38)
        ctx.set_line_width(max(1.0, w_mid * 0.32))
        ctx.set_line_cap(cairo.LINE_CAP_ROUND)
        ctx.move_to(cx - w_top * 0.20, top_y + 2)
        ctx.curve_to(
            cx - w_top * 0.18, top_y + (mid_y - top_y) * 0.5,
            cx - w_mid * 0.55, mid_y + (bulb_top_y - mid_y) * 0.4,
            cx - bulb_r * 0.4, bulb_top_y,
        )
        ctx.stroke()
        # Highlight blob on the bulb itself.
        ctx.set_source_rgba(*PALE_COMB, 0.55)
        ctx.arc(cx - bulb_r * 0.35, tip_y + bulb_r * 0.05,
                bulb_r * 0.28, 0, 2 * math.pi)
        ctx.fill()
        ctx.restore()

    # ── wordmark + subtitle ───────────────────────────────────────────
    def _draw_wordmark(self, ctx: cairo.Context, w: int, h: int,
                       alpha: float) -> None:
        if alpha <= 0.01:
            return
        ctx.save()
        font_px = max(56.0, min(w, h) * 0.14)
        ctx.select_font_face(
            "Sans", cairo.FONT_SLANT_NORMAL, cairo.FONT_WEIGHT_BOLD,
        )
        ctx.set_font_size(font_px)
        title = "M E L I"
        extents = ctx.text_extents(title)
        tx = (w - extents.width) / 2.0 - extents.x_bearing
        ty = h * LETTERS_BASELINE_FY

        # Amber glow halo.
        ctx.set_source_rgba(*AMBER_GLOW, alpha * 0.65)
        for ox, oy in ((-3, 0), (3, 0), (0, -3), (0, 3),
                       (-2, -2), (2, -2), (-2, 2), (2, 2)):
            ctx.move_to(tx + ox, ty + oy)
            ctx.show_text(title)
        # Main fill — warm amber.
        ctx.set_source_rgba(*AMBER_GLOW, alpha)
        ctx.move_to(tx, ty)
        ctx.show_text(title)
        # Pale highlight sheen along the top edge.
        ctx.set_source_rgba(*PALE_COMB, alpha * 0.55)
        ctx.move_to(tx, ty - font_px * 0.04)
        ctx.show_text(title)
        ctx.restore()

    def _draw_subtitle(self, ctx: cairo.Context, w: int, h: int,
                       alpha: float) -> None:
        if alpha <= 0.01:
            return
        ctx.save()
        font_px = max(14.0, min(w, h) * 0.026)
        ctx.select_font_face(
            "Sans", cairo.FONT_SLANT_NORMAL, cairo.FONT_WEIGHT_NORMAL,
        )
        ctx.set_font_size(font_px)
        sub = "honey trap command center"
        extents = ctx.text_extents(sub)
        tx = (w - extents.width) / 2.0 - extents.x_bearing
        ty = h * SUBTITLE_FY
        ctx.set_source_rgba(*AMBER_GLOW, alpha * 0.4)
        for ox, oy in ((-1, 0), (1, 0), (0, -1), (0, 1)):
            ctx.move_to(tx + ox, ty + oy)
            ctx.show_text(sub)
        ctx.set_source_rgba(*RAW_HONEY, alpha * 0.95)
        ctx.move_to(tx, ty)
        ctx.show_text(sub)
        ctx.restore()

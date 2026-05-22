"""
Meli startup splash screen.

A short (~3.5s) Cairo-animated intro that plays once on every launch.
Honey drops fall from the top of the canvas, splat into a rising golden
pool, and the Meli wordmark + amphora silhouette emerges as the pool
settles. A procedurally generated WAV (`assets/sounds/splash.wav`)
plays in lockstep with the animation.

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
    RAW_HONEY, AMBER_GLOW, DARK_HONEY, PALE_COMB, HIVE_BLACK, COMB_PANEL, paint_pot,
)

log = structlog.get_logger()

# Canvas + animation tuning.
CANVAS_W       = 640
CANVAS_H       = 420
FRAME_MS       = 33                    # ~30 fps — matches HoneyPotWidget cadence
TOTAL_MS       = 6500                  # full splash duration (give the user time to enjoy it)
DROP_COUNT     = 7                     # honey drops falling from top
DROP_START_MS  = 0                     # drops start immediately
DROP_END_MS    = 2800                  # last drop splats by here
POOL_START_MS  = 1000                  # pool begins rising once first drop lands
POOL_FULL_MS   = 4400                  # pool reaches its final height
LOGO_START_MS  = 3600                  # wordmark begins fading in
LOGO_FULL_MS   = 5200                  # wordmark fully visible
FADE_START_MS  = 5900                  # final fade-out begins
FADE_END_MS    = TOTAL_MS

# Pool baseline (rises to this y-coordinate from the bottom of the canvas)
POOL_FINAL_H   = 150

SOUND_PATH = Path(__file__).resolve().parent.parent.parent / "assets" / "sounds" / "splash.wav"


def _ease_out_cubic(t: float) -> float:
    t = max(0.0, min(1.0, t))
    return 1.0 - (1.0 - t) ** 3


def _ease_in_out(t: float) -> float:
    t = max(0.0, min(1.0, t))
    return 0.5 - 0.5 * math.cos(math.pi * t)


class _Drop:
    """One honey drop falling from the top of the canvas."""

    __slots__ = ("x", "start_ms", "end_ms", "size", "wobble")

    def __init__(self, x: float, start_ms: int, end_ms: int, size: float, wobble: float) -> None:
        self.x        = x
        self.start_ms = start_ms
        self.end_ms   = end_ms
        self.size     = size
        self.wobble   = wobble

    def y_at(self, elapsed_ms: int, target_y: float) -> float | None:
        """Return current y, or None if the drop has not started / has landed."""
        if elapsed_ms < self.start_ms:
            return None
        if elapsed_ms >= self.end_ms:
            return None  # already splatted; pool handles it from here
        t = (elapsed_ms - self.start_ms) / max(1, self.end_ms - self.start_ms)
        return _ease_out_cubic(t) * target_y


def _try_play_sound() -> subprocess.Popen | None:
    """Best-effort, non-blocking playback of the splash WAV.

    Honors `splash.sound_enabled` (default True). Never raises — a
    missing player or missing file just means silent splash. Returns
    the Popen handle so the caller can terminate playback on early
    shutdown (prevents orphaned audio processes).
    """
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
            return subprocess.Popen(cmd, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        except FileNotFoundError:
            continue
    log.debug("No audio player available for splash sound")
    return None


class SplashOverlay(Gtk.Box):
    """Splash animation as a Gtk.Overlay child on the main window.

    Fills the entire main window with a solid opaque background so
    no UI behind it (lock screen, dashboard, etc.) shows through.
    The honey-pot animation is drawn centered at its native CANVAS_W
    x CANVAS_H size; the rest of the window stays the gradient bg.

    Usage:
        splash = SplashOverlay()
        splash.connect("splash-finished", lambda *_: on_done())
        overlay.add_overlay(splash)   # on top of lock screen
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
        # Fill the full main window so we are one cohesive screen.
        self.set_hexpand(True)
        self.set_vexpand(True)
        self.set_halign(Gtk.Align.FILL)
        self.set_valign(Gtk.Align.FILL)
        # Eat all input while the splash is up.
        self.set_can_target(True)
        self.set_focusable(True)

        self._start_ms: int | None = None
        self._finished = False
        self._tick_source: int | None = None
        self._sound_proc: subprocess.Popen | None = None

        # Pre-roll the drops with deterministic-but-varied positions so the
        # animation is reproducible across launches but doesn't look gridded.
        rng = random.Random(0xC0FFEE)
        self._drops: list[_Drop] = []
        for i in range(DROP_COUNT):
            x_frac = (i + 0.5) / DROP_COUNT + rng.uniform(-0.05, 0.05)
            start  = DROP_START_MS + int(i * (DROP_END_MS - DROP_START_MS) / (DROP_COUNT + 1))
            end    = start + rng.randint(750, 950)
            size   = rng.uniform(7.0, 12.0)
            wobble = rng.uniform(0.0, 2 * math.pi)
            self._drops.append(_Drop(x_frac * CANVAS_W, start, min(end, DROP_END_MS), size, wobble))

        # Single drawing area that paints fullscreen — it expands to
        # fill the entire main window and we draw the animation
        # centered inside it on a solid background.
        self._area = Gtk.DrawingArea()
        self._area.set_hexpand(True)
        self._area.set_vexpand(True)
        self._area.set_draw_func(self._on_draw_fullscreen)
        self.append(self._area)

        self.connect("map", self._on_mapped)
        self.connect("unmap", self._cleanup)
        self.connect("destroy", self._cleanup)

    # ---- lifecycle ----------------------------------------------------

    def _on_mapped(self, *_args) -> None:
        if self._start_ms is not None:
            return  # defensive against double-map
        self._start_ms = int(time.monotonic() * 1000)
        self._sound_proc = _try_play_sound()
        self._tick_source = GLib.timeout_add(FRAME_MS, self._on_tick)

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
        # Emit synchronously so the parent removes us from the overlay
        # before we cleanup; cleanup is also idempotent if the overlay
        # remove triggers our unmap/destroy signals.
        try:
            self.emit("splash-finished")
        except Exception as e:
            log.debug("splash-finished emit failed", error=str(e))

    def _on_draw_fullscreen(self, area: Gtk.DrawingArea, ctx: cairo.Context, w: int, h: int) -> None:
        # Paint the whole window opaque first (no peek-through to the
        # lock screen or dashboard behind us).
        ctx.save()
        ctx.set_source_rgb(*HIVE_BLACK)
        ctx.rectangle(0, 0, w, h)
        ctx.fill()
        ctx.restore()
        # Then run the original animation, translated so the CANVAS_W
        # x CANVAS_H scene is centered inside the (likely larger) window.
        off_x = max(0, (w - CANVAS_W) // 2)
        off_y = max(0, (h - CANVAS_H) // 2)
        ctx.save()
        ctx.translate(off_x, off_y)
        self._on_draw(area, ctx, CANVAS_W, CANVAS_H)
        ctx.restore()

    def _stop_tick(self) -> None:
        if self._tick_source is not None:
            try:
                GLib.source_remove(self._tick_source)
            except Exception:
                pass
            self._tick_source = None

    def _cleanup(self, *_args) -> None:
        """Idempotent teardown — safe to call from unmap, destroy, or finish."""
        self._stop_tick()
        proc = self._sound_proc
        self._sound_proc = None
        if proc is not None and proc.poll() is None:
            try:
                proc.terminate()
            except Exception:
                pass

    # ---- drawing ------------------------------------------------------

    def _on_draw(self, _area: Gtk.DrawingArea, ctx: cairo.Context, w: int, h: int) -> None:
        elapsed = 0 if self._start_ms is None else int(time.monotonic() * 1000) - self._start_ms
        elapsed = max(0, min(TOTAL_MS, elapsed))

        # 1. Background — vertical gradient from hive-black at top to a
        #    slightly warmer comb-panel near the pool.
        bg = cairo.LinearGradient(0, 0, 0, h)
        bg.add_color_stop_rgb(0.0, *HIVE_BLACK)
        bg.add_color_stop_rgb(1.0, *COMB_PANEL)
        ctx.set_source(bg)
        ctx.rectangle(0, 0, w, h)
        ctx.fill()

        # Compute pool height for this frame — drops landing make it rise.
        pool_t = (elapsed - POOL_START_MS) / max(1, POOL_FULL_MS - POOL_START_MS)
        pool_h = POOL_FINAL_H * _ease_in_out(pool_t)
        pool_top_y = h - pool_h

        # 2. Pool (drawn before falling drops so drops appear in front).
        if pool_h > 0.5:
            self._draw_pool(ctx, w, h, pool_top_y, elapsed)

        # 3. Falling drops.
        target_y = pool_top_y - 4  # land just at the surface
        for drop in self._drops:
            y = drop.y_at(elapsed, max(0.0, target_y))
            if y is None:
                continue
            self._draw_drop(ctx, drop, y, elapsed)

        # 4. Splash ripples for drops that just landed (within last 200ms).
        for drop in self._drops:
            since_land = elapsed - drop.end_ms
            if 0 <= since_land <= 220 and pool_h > 4:
                self._draw_splash(ctx, drop.x, pool_top_y, since_land, drop.size)

        # 5. Logo: amphora silhouette + wordmark, fading in.
        logo_t = (elapsed - LOGO_START_MS) / max(1, LOGO_FULL_MS - LOGO_START_MS)
        logo_alpha = _ease_out_cubic(logo_t)
        if logo_alpha > 0.01:
            self._draw_logo(ctx, w, h, pool_top_y, logo_alpha)

        # 6. Final fade-to-black overlay.
        if elapsed >= FADE_START_MS:
            fade_t = (elapsed - FADE_START_MS) / max(1, FADE_END_MS - FADE_START_MS)
            ctx.set_source_rgba(*HIVE_BLACK, _ease_in_out(fade_t))
            ctx.rectangle(0, 0, w, h)
            ctx.fill()

    def _draw_drop(self, ctx: cairo.Context, drop: _Drop, y: float, elapsed_ms: int) -> None:
        # Teardrop: ellipse body + tapered top.
        wobble_x = drop.x + math.sin((elapsed_ms / 220.0) + drop.wobble) * 1.6
        r = drop.size

        # Soft amber glow halo around the drop
        halo = cairo.RadialGradient(wobble_x, y, 0, wobble_x, y, r * 2.6)
        halo.add_color_stop_rgba(0.0, *AMBER_GLOW, 0.55)
        halo.add_color_stop_rgba(1.0, *AMBER_GLOW, 0.0)
        ctx.set_source(halo)
        ctx.arc(wobble_x, y, r * 2.6, 0, 2 * math.pi)
        ctx.fill()

        # Drop body — pear shape via path
        ctx.move_to(wobble_x, y - r * 1.6)
        ctx.curve_to(
            wobble_x + r * 0.9, y - r * 0.6,
            wobble_x + r * 1.0, y + r * 0.6,
            wobble_x,           y + r * 1.0,
        )
        ctx.curve_to(
            wobble_x - r * 1.0, y + r * 0.6,
            wobble_x - r * 0.9, y - r * 0.6,
            wobble_x,           y - r * 1.6,
        )
        ctx.close_path()
        body = cairo.LinearGradient(wobble_x, y - r, wobble_x, y + r)
        body.add_color_stop_rgb(0.0, *AMBER_GLOW)
        body.add_color_stop_rgb(1.0, *DARK_HONEY)
        ctx.set_source(body)
        ctx.fill()

        # Specular highlight
        ctx.set_source_rgba(*PALE_COMB, 0.55)
        ctx.arc(wobble_x - r * 0.35, y - r * 0.4, r * 0.25, 0, 2 * math.pi)
        ctx.fill()

    def _draw_pool(self, ctx: cairo.Context, w: int, h: int, top_y: float, elapsed_ms: int) -> None:
        # Surface with a gentle sine wave (frequency + amplitude tuned to
        # read as "liquid" without being cartoonish).
        amp = 2.5 + 1.5 * math.sin(elapsed_ms / 380.0)
        ctx.move_to(0, h)
        ctx.line_to(0, top_y)
        x = 0
        while x <= w:
            wave_y = top_y + math.sin((x / 38.0) + (elapsed_ms / 240.0)) * amp
            ctx.line_to(x, wave_y)
            x += 6
        ctx.line_to(w, h)
        ctx.close_path()
        grad = cairo.LinearGradient(0, top_y, 0, h)
        grad.add_color_stop_rgb(0.0, *AMBER_GLOW)
        grad.add_color_stop_rgb(0.55, *RAW_HONEY)
        grad.add_color_stop_rgb(1.0, *DARK_HONEY)
        ctx.set_source(grad)
        ctx.fill()

        # Surface sheen — thin pale highlight along the top of the pool
        ctx.set_source_rgba(*PALE_COMB, 0.35)
        ctx.set_line_width(1.4)
        ctx.move_to(0, top_y + math.sin(elapsed_ms / 240.0) * amp)
        x = 0
        while x <= w:
            wave_y = top_y + math.sin((x / 38.0) + (elapsed_ms / 240.0)) * amp
            ctx.line_to(x, wave_y)
            x += 6
        ctx.stroke()

    def _draw_splash(self, ctx: cairo.Context, x: float, surface_y: float, age_ms: int, size: float) -> None:
        t = age_ms / 220.0
        radius = size * (1.0 + 3.5 * t)
        alpha = (1.0 - t) * 0.6
        ctx.set_source_rgba(*PALE_COMB, alpha)
        ctx.set_line_width(2.0 * (1.0 - t))
        ctx.arc(x, surface_y, radius, math.pi, 2 * math.pi)
        ctx.stroke()
        # A pair of upward arc-flecks suggesting splashed droplets
        ctx.set_source_rgba(*AMBER_GLOW, alpha)
        for dx in (-radius * 0.7, radius * 0.7):
            fly_y = surface_y - 10 * t + 18 * t * t
            ctx.arc(x + dx, fly_y, 2.4 * (1.0 - t), 0, 2 * math.pi)
            ctx.fill()

    def _draw_logo(self, ctx: cairo.Context, w: int, h: int, pool_top_y: float, alpha: float) -> None:
        # Amphora silhouette emerging from the pool — draw at canvas
        # center, scaled to ~55% of the height above the pool.
        avail_h = pool_top_y - 32
        scale = max(0.4, min(1.0, avail_h / 300.0))
        pot_w = 220 * scale
        pot_h = 300 * scale
        pot_x = (w - pot_w) / 2.0
        pot_y = pool_top_y - pot_h + 30 * scale  # let the foot dip into the pool

        ctx.save()
        ctx.translate(pot_x, pot_y)
        ctx.scale(scale, scale)
        # paint_pot draws into a 220x300 canvas. Render into an isolated
        # group so we can composite at the splash's fade alpha without
        # re-plumbing alpha through every paint_pot internal. push_group
        # must always be matched by pop_group, even on exception, or the
        # Cairo state stack stays unbalanced for the rest of the frame.
        ctx.push_group()
        paint_err: Exception | None = None
        try:
            paint_pot(
                ctx, 220, 300,
                fill=0.62,
                event_count=0,
                drips=(),
                pulse_color=AMBER_GLOW,
                pulse_alpha=0.35,
                wobble_phase=0.0,
                show_label=False,
            )
        except Exception as e:  # defensive: never let drawing crash the splash
            paint_err = e
        pattern = ctx.pop_group()
        if paint_err is None:
            ctx.set_source(pattern)
            ctx.paint_with_alpha(alpha)
        else:
            log.debug("paint_pot failed during splash", error=str(paint_err))
        ctx.restore()

        # Wordmark: "MELI" in a generous spaced uppercase below the pot.
        # Use Cairo's toy text API to avoid adding a font dependency.
        ctx.save()
        ctx.set_source_rgba(*PALE_COMB, alpha)
        ctx.select_font_face("Sans", cairo.FONT_SLANT_NORMAL, cairo.FONT_WEIGHT_BOLD)
        ctx.set_font_size(42)
        title = "M E L I"
        extents = ctx.text_extents(title)
        tx = (w - extents.width) / 2.0 - extents.x_bearing
        ty = h - 26
        # Soft amber glow behind the text
        ctx.set_source_rgba(*AMBER_GLOW, alpha * 0.55)
        for ox, oy in ((-2, 0), (2, 0), (0, -2), (0, 2)):
            ctx.move_to(tx + ox, ty + oy)
            ctx.show_text(title)
        ctx.set_source_rgba(*PALE_COMB, alpha)
        ctx.move_to(tx, ty)
        ctx.show_text(title)

        # Subtitle
        ctx.set_font_size(13)
        ctx.select_font_face("Sans", cairo.FONT_SLANT_NORMAL, cairo.FONT_WEIGHT_NORMAL)
        sub = "honey trap command center"
        ext2 = ctx.text_extents(sub)
        ctx.set_source_rgba(*RAW_HONEY, alpha * 0.85)
        ctx.move_to((w - ext2.width) / 2.0 - ext2.x_bearing, ty + 18)
        ctx.show_text(sub)
        ctx.restore()

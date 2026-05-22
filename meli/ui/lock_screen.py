"""
Meli lock screen — shown on launch and after idle timeout.
Emits 'unlocked' signal on successful authentication.

The background is no longer a flat black veil. A Cairo-drawn
honeycomb backdrop fills the entire window: hexagonal cells in
hive-black with dark-amber outlines, a soft amber radial bloom at
the center, and a subtle pulse on the central comb behind the
auth card. The auth form sits in front of this on a translucent
comb-panel card so it reads cleanly without losing the theme.
"""
from __future__ import annotations

import math
import time

import gi
gi.require_version("Gtk", "4.0")
gi.require_version("Adw", "1")

from gi.repository import Gtk, Adw, GLib, GObject  # noqa: E402
import cairo  # noqa: E402

import structlog
from meli.auth import attempt_login, is_totp_enabled
from meli.ui.widgets.honey_pot import (
    HIVE_BLACK, COMB_PANEL, RAW_HONEY, AMBER_GLOW, DARK_HONEY, PALE_COMB,
)

log = structlog.get_logger()


# ── honeycomb backdrop ────────────────────────────────────────────────────
class _HoneycombBackdrop(Gtk.DrawingArea):
    """Tile of slightly-randomised honeycomb cells covering the whole window.

    A handful of cells near the geometric center are highlighted
    'warm' (filled with a faint amber) and pulse gently so the
    backdrop feels alive — like honeycomb lit from behind.
    """

    CELL_SIZE = 64          # apothem-ish; final hex radius derived below
    PULSE_PERIOD_MS = 4200  # one full slow breath

    def __init__(self) -> None:
        super().__init__()
        self.set_hexpand(True)
        self.set_vexpand(True)
        self.set_draw_func(self._draw)
        self._start_ms = int(time.monotonic() * 1000)
        # Drive a slow redraw so the pulse breathes — 12 fps is plenty
        # for the gentle bloom, doesn't burn CPU on the lock screen.
        GLib.timeout_add(80, self._tick)

    def _tick(self) -> bool:
        self.queue_draw()
        return True

    def _draw(self, _area: Gtk.DrawingArea, ctx: cairo.Context,
              w: int, h: int) -> None:
        # 1. Base wash — vertical gradient hive-black -> comb-panel.
        bg = cairo.LinearGradient(0, 0, 0, h)
        bg.add_color_stop_rgb(0.0, *HIVE_BLACK)
        bg.add_color_stop_rgb(1.0, *COMB_PANEL)
        ctx.set_source(bg)
        ctx.rectangle(0, 0, w, h)
        ctx.fill()

        # 2. Honeycomb tiling.
        # Pointy-top hex geometry: width = sqrt(3) * size, height = 2 * size.
        size = self.CELL_SIZE / 1.732  # so visual width ~= CELL_SIZE
        hex_w = math.sqrt(3) * size
        hex_h = 2 * size
        row_step = hex_h * 0.75

        elapsed = int(time.monotonic() * 1000) - self._start_ms
        pulse_phase = (elapsed % self.PULSE_PERIOD_MS) / self.PULSE_PERIOD_MS
        pulse = 0.5 - 0.5 * math.cos(pulse_phase * 2 * math.pi)

        cx_screen, cy_screen = w / 2.0, h / 2.0
        # The "warm" radius — cells within this distance of center
        # get a faint amber fill that breathes with the pulse.
        warm_r = min(w, h) * 0.32

        rows = int(h / row_step) + 3
        cols = int(w / hex_w) + 3
        for ri in range(-1, rows):
            cy = ri * row_step
            x_off = (hex_w / 2.0) if (ri % 2) else 0.0
            for ci in range(-1, cols):
                cx = ci * hex_w + x_off
                dx = cx - cx_screen
                dy = cy - cy_screen
                dist = math.hypot(dx, dy)

                # Outline alpha falls off slightly toward the edges so
                # the honeycomb looks lit from the center.
                edge_t = min(1.0, dist / (max(w, h) * 0.7))
                outline_alpha = 0.22 * (1.0 - 0.5 * edge_t)

                # Fill ramp: solid warm at center -> nothing past warm_r.
                if dist < warm_r:
                    warmth = (1.0 - dist / warm_r) ** 1.6
                    warmth *= 0.35 + 0.35 * pulse  # breathe
                else:
                    warmth = 0.0

                self._draw_hex(ctx, cx, cy, size, outline_alpha, warmth)

        # 3. Central amber bloom behind where the auth card sits.
        bloom_r = min(w, h) * 0.42
        bloom = cairo.RadialGradient(cx_screen, cy_screen, bloom_r * 0.05,
                                     cx_screen, cy_screen, bloom_r)
        bloom_alpha = 0.18 + 0.10 * pulse
        bloom.add_color_stop_rgba(0.0, *AMBER_GLOW, bloom_alpha)
        bloom.add_color_stop_rgba(1.0, *AMBER_GLOW, 0.0)
        ctx.set_source(bloom)
        ctx.arc(cx_screen, cy_screen, bloom_r, 0, 2 * math.pi)
        ctx.fill()

        # 4. Edge vignette to focus the eye toward the center.
        vignette = cairo.RadialGradient(
            cx_screen, cy_screen, min(w, h) * 0.25,
            cx_screen, cy_screen, max(w, h) * 0.85,
        )
        vignette.add_color_stop_rgba(0.0, 0, 0, 0, 0.0)
        vignette.add_color_stop_rgba(1.0, 0, 0, 0, 0.55)
        ctx.set_source(vignette)
        ctx.rectangle(0, 0, w, h)
        ctx.fill()

    @staticmethod
    def _draw_hex(ctx: cairo.Context, cx: float, cy: float, size: float,
                  outline_alpha: float, warmth: float) -> None:
        # Pointy-top hexagon vertices.
        ctx.new_path()
        for i in range(6):
            a = math.pi / 2 + i * math.pi / 3  # start at top vertex
            x = cx + size * math.cos(a)
            y = cy + size * math.sin(a)
            if i == 0:
                ctx.move_to(x, y)
            else:
                ctx.line_to(x, y)
        ctx.close_path()
        if warmth > 0.001:
            # Faint amber wash inside the cell.
            ctx.set_source_rgba(*RAW_HONEY, warmth * 0.55)
            ctx.fill_preserve()
        ctx.set_source_rgba(*DARK_HONEY, outline_alpha)
        ctx.set_line_width(1.1)
        ctx.stroke()


# ── lock screen widget ───────────────────────────────────────────────────
class LockScreen(Gtk.Overlay):
    __gsignals__ = {
        "unlocked": (GObject.SignalFlags.RUN_FIRST, None, ()),
    }

    _CSS_INSTALLED = False

    def __init__(self) -> None:
        super().__init__()
        self.add_css_class("background")
        self.add_css_class("meli-lock-veil")
        self.set_hexpand(True)
        self.set_vexpand(True)
        self.set_halign(Gtk.Align.FILL)
        self.set_valign(Gtk.Align.FILL)
        self.set_can_target(True)
        self.set_focusable(True)

        if not LockScreen._CSS_INSTALLED:
            provider = Gtk.CssProvider()
            css = (
                # Translucent comb-panel card so the honeycomb shows
                # through subtly behind the form.
                b".meli-lock-card {"
                b"  background: alpha(@meli_comb_panel, 0.78);"
                b"  border: 1px solid alpha(@meli_amber_glow, 0.35);"
                b"  border-radius: 18px;"
                b"  padding: 30px 36px;"
                b"  box-shadow: 0 12px 60px alpha(black, 0.55),"
                b"              0 0 0 1px alpha(@meli_amber_glow, 0.10) inset;"
                b"}"
                # Fallback if the named colors aren't defined yet.
                b".meli-lock-card-fallback {"
                b"  background: rgba(28, 22, 15, 0.78);"
                b"  border: 1px solid rgba(243, 188, 55, 0.35);"
                b"  border-radius: 18px;"
                b"  padding: 30px 36px;"
                b"  box-shadow: 0 12px 60px rgba(0, 0, 0, 0.55);"
                b"}"
                b".meli-lock-title { font-size: 32px; font-weight: 800;"
                b"  letter-spacing: 4px; }"
                b".meli-lock-bolt  { font-size: 28px; }"
            )
            provider.load_from_data(css)
            try:
                from gi.repository import Gdk
                Gtk.StyleContext.add_provider_for_display(
                    Gdk.Display.get_default(),
                    provider,
                    Gtk.STYLE_PROVIDER_PRIORITY_APPLICATION,
                )
                LockScreen._CSS_INSTALLED = True
            except Exception as e:
                log.debug("Could not install lock CSS", error=str(e))

        self._totp_required = is_totp_enabled()
        self._shake_pending = False

        # Honeycomb backdrop fills the overlay; the form sits on top.
        self._backdrop = _HoneycombBackdrop()
        self.set_child(self._backdrop)
        self._build_ui()

    def _build_ui(self) -> None:
        # Center everything in a translucent card.
        center = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=18)
        center.set_halign(Gtk.Align.CENTER)
        center.set_valign(Gtk.Align.CENTER)
        center.set_margin_top(40)
        center.set_margin_bottom(40)
        center.set_margin_start(40)
        center.set_margin_end(40)

        card = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=14)
        card.add_css_class("meli-lock-card")
        card.add_css_class("meli-lock-card-fallback")
        card.set_halign(Gtk.Align.CENTER)

        # Branding header.
        logo_label = Gtk.Label(label="⚡")
        logo_label.add_css_class("meli-lock-bolt")
        logo_label.add_css_class("amber-accent")
        logo_label.set_halign(Gtk.Align.CENTER)

        title = Gtk.Label(label="M E L I")
        title.add_css_class("meli-lock-title")
        title.add_css_class("title-1")
        title.set_halign(Gtk.Align.CENTER)

        subtitle = Gtk.Label(label="Honeypot Command Center")
        subtitle.add_css_class("body")
        subtitle.set_halign(Gtk.Align.CENTER)
        subtitle.set_opacity(0.72)

        card.append(logo_label)
        card.append(title)
        card.append(subtitle)

        # Form section.
        form = Adw.PreferencesGroup()
        form.set_title("Authentication Required")
        form.set_description("Enter your master password to continue")

        self._password_row = Adw.PasswordEntryRow(title="Master Password")
        self._password_row.connect("entry-activated", self._on_unlock_clicked)
        form.add(self._password_row)

        if self._totp_required:
            self._totp_row = Adw.EntryRow(title="2FA Code (TOTP)")
            self._totp_row.connect("entry-activated", self._on_unlock_clicked)
            form.add(self._totp_row)
        else:
            self._totp_row = None

        card.append(form)

        # Error label.
        self._error_label = Gtk.Label(label="")
        self._error_label.add_css_class("error")
        self._error_label.set_visible(False)
        self._error_label.set_halign(Gtk.Align.CENTER)
        card.append(self._error_label)

        # Unlock button.
        unlock_btn = Gtk.Button(label="Unlock")
        unlock_btn.add_css_class("suggested-action")
        unlock_btn.add_css_class("pill")
        unlock_btn.set_halign(Gtk.Align.CENTER)
        unlock_btn.set_size_request(220, -1)
        unlock_btn.connect("clicked", self._on_unlock_clicked)
        card.append(unlock_btn)

        center.append(card)
        self.add_overlay(center)

    def _on_unlock_clicked(self, *_) -> None:
        password = self._password_row.get_text()
        totp = self._totp_row.get_text() if self._totp_row else ""

        success, message = attempt_login(password, totp)

        if success:
            self.emit("unlocked")
        else:
            self._show_error(message)
            self._shake()
            self._password_row.set_text("")
            if self._totp_row:
                self._totp_row.set_text("")

    def _show_error(self, message: str) -> None:
        self._error_label.set_text(message)
        self._error_label.set_visible(True)

    def _shake(self) -> None:
        if self._shake_pending:
            return
        self._shake_pending = True
        original_margin = self._password_row.get_margin_start()

        def step(n: int) -> bool:
            offsets = [10, -10, 8, -8, 5, -5, 0]
            if n < len(offsets):
                self._password_row.set_margin_start(original_margin + offsets[n])
                self._password_row.set_margin_end(original_margin - offsets[n])
                GLib.timeout_add(40, step, n + 1)
                return False
            self._shake_pending = False
            return False

        GLib.timeout_add(40, step, 0)

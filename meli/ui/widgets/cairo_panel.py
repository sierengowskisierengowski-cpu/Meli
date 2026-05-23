"""Cairo-painted panel chrome.

CSS in GTK4 is unreliable for the rich honey-gradient/glow look we want
(linear-gradient stops that reference @-vars via alpha() silently fail on
some builds, multi-value box-shadows get partially dropped, Adwaita's
.card wrapper cascades over our selectors, etc.). So we paint the panel
chrome directly with cairo the same way HoneyPotWidget paints the jar.

Two widgets:
- `CairoPanel`  — luminous warm-brown gradient, gold inner highlight,
                  amber-tinted outer drop shadow, soft warm border.
- `CairoKpiTile` (in charts.py) — same look + bright amber top edge.

Both subclass Gtk.Box and override do_snapshot so children render on top
of the cairo-painted backdrop. No CSS needed for the chrome.
"""
from __future__ import annotations

import math

import cairo
import gi
gi.require_version("Gtk", "4.0")
gi.require_version("Adw", "1")
from gi.repository import Adw, Gdk, Graphene, Gtk  # noqa: E402


# ── Palette (matches @meli_* CSS vars in style.css) ────────────────────
PANEL_TOP    = (0xa1 / 255, 0x6e / 255, 0x18 / 255)
PANEL_MID    = (0x2e / 255, 0x1f / 255, 0x10 / 255)
PANEL_BOTTOM = (0x14 / 255, 0x0c / 255, 0x05 / 255)
PANEL_BORDER = (0x5a / 255, 0x3a / 255, 0x1c / 255)
GOLD_HIGHLIGHT = (0xf5 / 255, 0xc8 / 255, 0x4a / 255)
AMBER_TOP_EDGE = (0xf5 / 255, 0x9e / 255, 0x0b / 255)


def _rounded_rect(ctx: cairo.Context, x: float, y: float,
                  w: float, h: float, r: float) -> None:
    r = min(r, w / 2, h / 2)
    ctx.new_sub_path()
    ctx.arc(x + w - r, y + r,     r, -math.pi / 2, 0)
    ctx.arc(x + w - r, y + h - r, r, 0,             math.pi / 2)
    ctx.arc(x + r,     y + h - r, r, math.pi / 2,   math.pi)
    ctx.arc(x + r,     y + r,     r, math.pi,       3 * math.pi / 2)
    ctx.close_path()


def paint_hive_panel(ctx: cairo.Context, w: float, h: float, *,
                     radius: float = 14.0,
                     top_edge: tuple[float, float, float] | None = None,
                     glow_strength: float = 1.0) -> None:
    """Paint the luminous hive panel chrome onto `ctx`, sized (w,h).

    `top_edge` (r,g,b) paints a 3px bright amber strip across the top —
    used by KPI tiles. `glow_strength` scales the outer amber halo.
    """
    pad = 6.0  # space reserved for the outer drop shadow

    # ── 1. Outer drop shadow (warm amber, soft) ────────────────────────
    for i in range(6):
        a = (0.12 - i * 0.018) * glow_strength
        if a <= 0:
            continue
        ctx.set_source_rgba(
            AMBER_TOP_EDGE[0], AMBER_TOP_EDGE[1], AMBER_TOP_EDGE[2], a)
        _rounded_rect(ctx,
                      pad - i * 0.8, pad - i * 0.4,
                      w - 2 * pad + i * 1.6, h - 2 * pad + i * 1.2,
                      radius + i * 0.6)
        ctx.fill()

    # Solid black drop shadow under the panel for grounding
    ctx.set_source_rgba(0, 0, 0, 0.55)
    _rounded_rect(ctx, pad, pad + 3, w - 2 * pad, h - 2 * pad, radius)
    ctx.fill()

    # ── 2. Body gradient (warm honey top → dark base) ──────────────────
    grad = cairo.LinearGradient(0, pad, 0, h - pad)
    grad.add_color_stop_rgb(0.00, *PANEL_TOP)
    grad.add_color_stop_rgb(0.18, *PANEL_MID)
    grad.add_color_stop_rgb(1.00, *PANEL_BOTTOM)
    ctx.set_source(grad)
    _rounded_rect(ctx, pad, pad, w - 2 * pad, h - 2 * pad, radius)
    ctx.fill_preserve()

    # ── 3. Inner gold halo (faint glow rim inside the border) ──────────
    ctx.save()
    ctx.clip()
    ctx.set_line_width(2.0)
    ctx.set_source_rgba(*GOLD_HIGHLIGHT, 0.10)
    _rounded_rect(ctx, pad + 1, pad + 1,
                  w - 2 * pad - 2, h - 2 * pad - 2, radius - 1)
    ctx.stroke()
    ctx.restore()

    # ── 4. Top inner highlight strip (gold sheen, ~1px) ────────────────
    sheen = cairo.LinearGradient(0, pad, 0, pad + 24)
    sheen.add_color_stop_rgba(0.0, *GOLD_HIGHLIGHT, 0.18)
    sheen.add_color_stop_rgba(1.0, *GOLD_HIGHLIGHT, 0.00)
    ctx.set_source(sheen)
    _rounded_rect(ctx, pad + 1, pad + 1,
                  w - 2 * pad - 2, 24, radius - 1)
    ctx.fill()

    # ── 5. Warm border ─────────────────────────────────────────────────
    ctx.set_line_width(1.0)
    ctx.set_source_rgb(*PANEL_BORDER)
    _rounded_rect(ctx, pad + 0.5, pad + 0.5,
                  w - 2 * pad - 1, h - 2 * pad - 1, radius)
    ctx.stroke()

    # ── 6. Optional bright amber top edge (KPI tile accent) ────────────
    if top_edge is not None:
        ctx.save()
        _rounded_rect(ctx, pad, pad, w - 2 * pad, h - 2 * pad, radius)
        ctx.clip()
        edge_grad = cairo.LinearGradient(0, pad, 0, pad + 4)
        edge_grad.add_color_stop_rgba(0.0, *top_edge, 1.0)
        edge_grad.add_color_stop_rgba(1.0, *top_edge, 0.5)
        ctx.set_source(edge_grad)
        ctx.rectangle(pad, pad, w - 2 * pad, 3)
        ctx.fill()
        # Faint outer glow above the edge
        ctx.set_source_rgba(*top_edge, 0.35)
        ctx.rectangle(pad, pad - 1, w - 2 * pad, 1)
        ctx.fill()
        ctx.restore()


class CairoPanel(Gtk.Box):
    """Gtk.Box that paints a luminous hive-panel backdrop via cairo.

    Drop-in replacement anywhere we used `Gtk.Box(...).add_css_class("hive-panel")`.
    Children render on top of the painted backdrop.

    Internally wraps a content box that carries the *inner* padding (so
    children don't crash into the cairo-painted border). `append()` and
    `prepend()` are proxied to the content box.
    """

    def __init__(self, *,
                 radius: float = 14.0,
                 padding: int = 18,
                 top_edge: tuple[float, float, float] | None = None,
                 glow_strength: float = 1.0,
                 orientation: Gtk.Orientation = Gtk.Orientation.VERTICAL,
                 spacing: int = 10) -> None:
        # Self is vertical and holds a single padded content box. The
        # content box owns the real orientation + spacing requested by
        # the caller.
        super().__init__(orientation=Gtk.Orientation.VERTICAL, spacing=0)
        self._radius = radius
        self._top_edge = top_edge
        self._glow_strength = glow_strength

        self._content = Gtk.Box(orientation=orientation, spacing=spacing)
        self._content.set_hexpand(True)
        self._content.set_vexpand(True)
        for setter in (self._content.set_margin_top,
                       self._content.set_margin_bottom,
                       self._content.set_margin_start,
                       self._content.set_margin_end):
            setter(padding)
        Gtk.Box.append(self, self._content)

        # Keep the CSS class for any future CSS-driven hover/focus rules,
        # but the cairo paint is now authoritative for the chrome.
        self.add_css_class("hive-panel")

    # ── Child-management proxies → content box ─────────────────────────
    def append(self, child: Gtk.Widget) -> None:  # type: ignore[override]
        self._content.append(child)

    def prepend(self, child: Gtk.Widget) -> None:  # type: ignore[override]
        self._content.prepend(child)

    def remove(self, child: Gtk.Widget) -> None:  # type: ignore[override]
        self._content.remove(child)

    def get_content(self) -> Gtk.Box:
        return self._content

    # ── Cairo paint ────────────────────────────────────────────────────
    def do_snapshot(self, snapshot: Gtk.Snapshot) -> None:
        w = float(self.get_width())
        h = float(self.get_height())
        if w > 0 and h > 0:
            rect = Graphene.Rect().init(0, 0, w, h)
            ctx = snapshot.append_cairo(rect)
            paint_hive_panel(ctx, w, h,
                             radius=self._radius,
                             top_edge=self._top_edge,
                             glow_strength=self._glow_strength)
        Gtk.Box.do_snapshot(self, snapshot)


# ── Hive-painted Adw.PreferencesGroup ────────────────────────────────────
class HivePrefsGroup(Adw.PreferencesGroup):
    """Drop-in replacement for Adw.PreferencesGroup that paints the same
    luminous hive-panel chrome behind itself (same cairo path as
    CairoPanel). Use this anywhere a PreferencesGroup is the visual
    container — settings rows, setup-wizard pages, alert-rule cards, etc.

    Children (rows, listboxes) render on top of the cairo backdrop.
    """
    __gtype_name__ = "MeliHivePrefsGroup"

    def __init__(self, **kwargs):
        super().__init__(**kwargs)
        # Pull rows in from the panel edge so they sit inside the chrome
        # padding and don't crash into the glow border.
        for s in (self.set_margin_top, self.set_margin_bottom,
                  self.set_margin_start, self.set_margin_end):
            s(8)

    def do_snapshot(self, snapshot: Gtk.Snapshot) -> None:
        w = float(self.get_width())
        h = float(self.get_height())
        if w > 0 and h > 0:
            rect = Graphene.Rect().init(0, 0, w, h)
            ctx = snapshot.append_cairo(rect)
            paint_hive_panel(ctx, w, h)
        Adw.PreferencesGroup.do_snapshot(self, snapshot)

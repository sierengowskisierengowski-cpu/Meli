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


# ── Palette ────────────────────────────────────────────────────────────
# Per design spec: hive-black core, raw-honey amber radiating to the edges.
HIVE_BLACK     = (0x10 / 255, 0x0a / 255, 0x04 / 255)   # #100a04 — panel core
RAW_HONEY      = (0xd4 / 255, 0xa0 / 255, 0x17 / 255)   # #d4a017 — edge bleed
AMBER_GLOW     = (0xf5 / 255, 0x9e / 255, 0x0b / 255)   # outer halo + KPI top edge
AMBER_TOP_EDGE = AMBER_GLOW                              # back-compat alias
GOLD_HIGHLIGHT = (0xf5 / 255, 0xc8 / 255, 0x4a / 255)
PANEL_BORDER   = RAW_HONEY                              # border uses raw honey @ 40%


def _rounded_rect(ctx: cairo.Context, x: float, y: float,
                  w: float, h: float, r: float) -> None:
    r = min(r, w / 2, h / 2)
    ctx.new_sub_path()
    ctx.arc(x + w - r, y + r,     r, -math.pi / 2, 0)
    ctx.arc(x + w - r, y + h - r, r, 0,             math.pi / 2)
    ctx.arc(x + r,     y + h - r, r, math.pi / 2,   math.pi)
    ctx.arc(x + r,     y + r,     r, math.pi,       3 * math.pi / 2)
    ctx.close_path()


ORANGE_DRIP   = (0xea / 255, 0x7c / 255, 0x1c / 255)   # #ea7c1c — honey drip orange


def paint_hive_panel(ctx: cairo.Context, w: float, h: float, *,
                     radius: float = 14.0,
                     top_edge: tuple[float, float, float] | list | None = None,
                     glow_strength: float = 1.0,
                     state_dot: tuple[float, float, float] | None = None) -> None:
    """Paint the luminous hive panel chrome onto `ctx`, sized (w,h).

    Design spec:
      • Body: radial gradient — hive-black #100a04 at the center radiating
        outward to raw-honey #d4a017 @ 15% alpha at the edges (amber light
        glowing from inside the panel walls).
      • Border: 1.5px raw-honey @ 40% alpha.
      • Outer halo: ~8px soft amber glow @ 20% alpha (multi-pass falloff).
      • Optional `top_edge` (r,g,b) paints a 3px bright amber strip across
        the top — used by KPI tiles.
      • `glow_strength` scales the outer halo intensity.
    """
    pad = 8.0  # reserve for the 8px outer halo

    inner_x = pad
    inner_y = pad
    inner_w = max(1.0, w - 2 * pad)
    inner_h = max(1.0, h - 2 * pad)

    # ── 1. Outer amber halo (8px spread, 20% alpha falloff) ────────────
    halo_steps = 9
    for i in range(halo_steps, 0, -1):
        # Linear falloff from 0.28 at i=1 to ~0.03 at i=halo_steps
        a = (0.28 * (1.0 - (i - 1) / halo_steps)) * glow_strength
        if a <= 0.005:
            continue
        ctx.set_source_rgba(*AMBER_GLOW, a)
        _rounded_rect(ctx,
                      inner_x - i, inner_y - i,
                      inner_w + 2 * i, inner_h + 2 * i,
                      radius + i)
        ctx.fill()

    # Solid black grounding shadow directly under the panel
    ctx.set_source_rgba(0, 0, 0, 0.55)
    _rounded_rect(ctx, inner_x, inner_y + 2, inner_w, inner_h, radius)
    ctx.fill()

    # ── 2. Body — solid hive-black base ────────────────────────────────
    ctx.set_source_rgb(*HIVE_BLACK)
    _rounded_rect(ctx, inner_x, inner_y, inner_w, inner_h, radius)
    ctx.fill_preserve()

    # ── 3. Radial amber edge-bleed (dark center → amber rim) ──────────
    # Center the radial at the panel midpoint; inner radius covers ~45%
    # of the panel (stays black), outer radius reaches the corners so
    # amber bleeds out from the walls.
    cx = inner_x + inner_w / 2
    cy = inner_y + inner_h / 2
    inner_r = min(inner_w, inner_h) * 0.30
    outer_r = math.hypot(inner_w, inner_h) / 2  # corner distance
    rgrad = cairo.RadialGradient(cx, cy, inner_r, cx, cy, outer_r)
    rgrad.add_color_stop_rgba(0.0, *RAW_HONEY, 0.00)
    rgrad.add_color_stop_rgba(0.45, *RAW_HONEY, 0.12)
    rgrad.add_color_stop_rgba(0.78, *RAW_HONEY, 0.26)
    rgrad.add_color_stop_rgba(1.0, *RAW_HONEY, 0.40)
    ctx.save()
    ctx.clip()  # still clipped to rounded-rect from fill_preserve
    ctx.set_source(rgrad)
    ctx.paint()
    ctx.restore()

    # ── 4. Inner gold halo (faint rim inside the border) ───────────────
    ctx.save()
    _rounded_rect(ctx, inner_x, inner_y, inner_w, inner_h, radius)
    ctx.clip()
    ctx.set_line_width(2.0)
    ctx.set_source_rgba(*GOLD_HIGHLIGHT, 0.10)
    _rounded_rect(ctx, inner_x + 1, inner_y + 1,
                  inner_w - 2, inner_h - 2, radius - 1)
    ctx.stroke()
    ctx.restore()

    # ── 5. Border — 1.5px raw honey @ 40% alpha ────────────────────────
    ctx.set_line_width(1.5)
    ctx.set_source_rgba(*PANEL_BORDER, 0.60)
    _rounded_rect(ctx, inner_x + 0.75, inner_y + 0.75,
                  inner_w - 1.5, inner_h - 1.5, radius)
    ctx.stroke()

    # ── 6. Optional bright amber top stripe — honey drip (KPI tiles) ──
    # Accepts either a single RGB (legacy) or a list of RGBs that get laid
    # out left→right as gradient stops. The mockup uses a 3-stop
    # HONEY → AMBER → ORANGE stripe with a strong outer halo.
    if top_edge is not None:
        if isinstance(top_edge, list) and top_edge and isinstance(top_edge[0], (list, tuple)):
            stops = list(top_edge)
        else:
            stops = [tuple(top_edge)]  # type: ignore[arg-type]
        ctx.save()
        _rounded_rect(ctx, inner_x, inner_y, inner_w, inner_h, radius)
        ctx.clip()
        # Horizontal multi-stop stripe
        stripe_grad = cairo.LinearGradient(
            inner_x, 0, inner_x + inner_w, 0)
        n = max(1, len(stops) - 1)
        for i, c in enumerate(stops):
            stripe_grad.add_color_stop_rgba(i / n, c[0], c[1], c[2], 1.0)
        ctx.set_source(stripe_grad)
        ctx.rectangle(inner_x, inner_y, inner_w, 3)
        ctx.fill()
        # Soft outer halo just above the stripe so it reads as "lit"
        halo_c = stops[len(stops) // 2]
        ctx.set_source_rgba(halo_c[0], halo_c[1], halo_c[2], 0.55)
        ctx.rectangle(inner_x, inner_y - 1, inner_w, 1)
        ctx.fill()
        ctx.set_source_rgba(halo_c[0], halo_c[1], halo_c[2], 0.18)
        ctx.rectangle(inner_x, inner_y + 3, inner_w, 4)
        ctx.fill()
        ctx.restore()

    # ── 7. Optional state dot (top-right indicator) ────────────────────
    if state_dot is not None:
        dx = inner_x + inner_w - 14
        dy = inner_y + 12
        # Soft glow halo
        ctx.set_source_rgba(*state_dot, 0.55)
        ctx.arc(dx, dy, 6.0, 0, 2 * math.pi)
        ctx.fill()
        ctx.set_source_rgba(*state_dot, 0.30)
        ctx.arc(dx, dy, 9.0, 0, 2 * math.pi)
        ctx.fill()
        # Crisp inner dot
        ctx.set_source_rgba(*state_dot, 1.0)
        ctx.arc(dx, dy, 3.5, 0, 2 * math.pi)
        ctx.fill()


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
                 top_edge: tuple[float, float, float] | list | None = None,
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

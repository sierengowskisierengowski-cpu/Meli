"""Premium chart + KPI widgets for the dashboard.

All widgets are Cairo-drawn on Gtk.DrawingArea so they get pixel-
perfect honey-themed visuals (gradients, glow, severity colors).
No external charting deps — keeps install.sh footprint minimal.

Palette mirrors resources/css/style.css.
"""
from __future__ import annotations

import math
import time
from typing import Sequence

import gi
gi.require_version("Gtk", "4.0")
gi.require_version("Adw", "1")
from gi.repository import Gtk, Adw, GLib  # noqa: E402

import cairo  # noqa: E402

# ── Palette (matches style.css) ───────────────────────────────────────────
HIVE_BLACK     = (0.063, 0.039, 0.016)   # #100a04
COMB_DARK      = (0.102, 0.078, 0.063)   # #1a1410
COMB_PANEL     = (0.133, 0.102, 0.071)   # #221a12
RAW_HONEY      = (0.831, 0.627, 0.090)   # #d4a017
AMBER_GLOW     = (0.961, 0.620, 0.043)   # #f59e0b
PALE_COMB      = (0.996, 0.953, 0.780)   # #fef3c7
BEESWAX        = (0.992, 0.902, 0.541)   # #fde68a
STING_RED      = (0.863, 0.149, 0.149)   # #dc2626
BURNT_ORANGE   = (0.918, 0.498, 0.110)   # #ea7f1c
WARM_BORDER    = (0.227, 0.157, 0.094)   # #3a2818

SEV_COLORS = {
    "CRITICAL": STING_RED,
    "HIGH":     BURNT_ORANGE,
    "MEDIUM":   RAW_HONEY,
    "LOW":      BEESWAX,
    "INFO":     (0.761, 0.722, 0.639),  # faded comb
}


# ── Sparkline ─────────────────────────────────────────────────────────────
class Sparkline(Gtk.DrawingArea):
    """Smooth filled-area line chart. Premium look: gradient fill below
    the line, glow on the line itself, accent dot at the latest sample.
    """

    __gtype_name__ = "MeliSparkline"

    def __init__(self, width: int = 220, height: int = 56,
                 color: tuple[float, float, float] = AMBER_GLOW) -> None:
        super().__init__()
        self.set_content_width(width)
        self.set_content_height(height)
        self.set_hexpand(True)
        self._values: list[float] = []
        self._color = color
        self.set_draw_func(self._on_draw)

    def set_values(self, values: Sequence[float]) -> None:
        self._values = [max(0.0, float(v)) for v in values]
        self.queue_draw()

    def set_color(self, rgb: tuple[float, float, float]) -> None:
        self._color = rgb
        self.queue_draw()

    def _on_draw(self, _a, ctx: cairo.Context, w: int, h: int) -> None:
        vals = self._values
        if not vals:
            self._draw_empty(ctx, w, h)
            return
        # Single-sample fallback: duplicate it so we still render a flat
        # area + line + endpoint marker instead of an empty card. The
        # dashboard's rolling deque starts with one reading right after
        # refresh, and we want users to see SOMETHING immediately.
        if len(vals) == 1:
            vals = [vals[0], vals[0]]
        n = len(vals)
        vmax = max(vals) or 1.0
        pad_x, pad_y = 4, 6
        cw, ch = w - 2 * pad_x, h - 2 * pad_y

        pts = []
        for i, v in enumerate(vals):
            x = pad_x + (i / max(1, n - 1)) * cw
            # Flat single-sample: render at ~65% height so the line and
            # the area below it are both visible.
            if vmax == 0 or all(v == vals[0] for v in vals):
                y = pad_y + ch * 0.35
            else:
                y = pad_y + ch - (v / vmax) * ch
            pts.append((x, y))

        # Area fill (gradient)
        r, g, b = self._color
        grad = cairo.LinearGradient(0, pad_y, 0, pad_y + ch)
        grad.add_color_stop_rgba(0.0, r, g, b, 0.45)
        grad.add_color_stop_rgba(1.0, r, g, b, 0.02)
        ctx.set_source(grad)
        ctx.move_to(pts[0][0], pad_y + ch)
        for x, y in pts:
            ctx.line_to(x, y)
        ctx.line_to(pts[-1][0], pad_y + ch)
        ctx.close_path()
        ctx.fill()

        # Glow stroke (wide, low alpha)
        ctx.set_source_rgba(r, g, b, 0.30)
        ctx.set_line_width(3.5)
        ctx.set_line_join(cairo.LINE_JOIN_ROUND)
        ctx.move_to(*pts[0])
        for x, y in pts[1:]:
            ctx.line_to(x, y)
        ctx.stroke()

        # Crisp line
        ctx.set_source_rgba(r, g, b, 1.0)
        ctx.set_line_width(1.6)
        ctx.move_to(*pts[0])
        for x, y in pts[1:]:
            ctx.line_to(x, y)
        ctx.stroke()

        # Latest sample marker
        lx, ly = pts[-1]
        ctx.set_source_rgba(r, g, b, 0.35)
        ctx.arc(lx, ly, 4.5, 0, 2 * math.pi)
        ctx.fill()
        ctx.set_source_rgba(*PALE_COMB, 1.0)
        ctx.arc(lx, ly, 2.0, 0, 2 * math.pi)
        ctx.fill()

    def _draw_empty(self, ctx: cairo.Context, w: int, h: int) -> None:
        ctx.set_source_rgba(*WARM_BORDER, 0.45)
        ctx.set_line_width(1.0)
        ctx.set_dash([3, 3])
        ctx.move_to(4, h / 2)
        ctx.line_to(w - 4, h / 2)
        ctx.stroke()
        ctx.set_dash([])


# ── Mini bar chart ────────────────────────────────────────────────────────
class MiniBarChart(Gtk.DrawingArea):
    """Vertical bars for time-bucketed counts. Peak bar highlights red.
    Used for 24h attack intensity, hourly histograms, etc.
    """

    def __init__(self, height: int = 88) -> None:
        super().__init__()
        self.set_content_height(height)
        self.set_hexpand(True)
        self._values: list[int] = []
        self._labels: list[str] = []
        self.set_draw_func(self._on_draw)

    def set_data(self, values: Sequence[int], labels: Sequence[str] | None = None) -> None:
        self._values = list(values)
        self._labels = list(labels) if labels else []
        self.queue_draw()

    def _on_draw(self, _a, ctx: cairo.Context, w: int, h: int) -> None:
        vals = self._values
        if not vals:
            ctx.set_source_rgba(*WARM_BORDER, 0.4)
            ctx.set_line_width(1.0)
            ctx.move_to(0, h - 1)
            ctx.line_to(w, h - 1)
            ctx.stroke()
            return
        n = len(vals)
        vmax = max(vals) or 1
        peak_idx = vals.index(max(vals))

        gap_px = 2
        bar_area_h = h - 14
        bar_w = max(1.0, (w - gap_px * (n - 1)) / n)

        # Baseline
        ctx.set_source_rgba(*WARM_BORDER, 0.5)
        ctx.set_line_width(1.0)
        ctx.move_to(0, h - 12)
        ctx.line_to(w, h - 12)
        ctx.stroke()

        for i, v in enumerate(vals):
            x = i * (bar_w + gap_px)
            bh = (v / vmax) * (bar_area_h - 4) if v > 0 else 0
            y = (h - 12) - bh

            if i == peak_idx and v > 0:
                col = STING_RED
            elif v >= vmax * 0.66:
                col = AMBER_GLOW
            elif v > 0:
                col = RAW_HONEY
            else:
                col = (WARM_BORDER[0], WARM_BORDER[1], WARM_BORDER[2])

            if v > 0:
                # Gradient: solid at bottom, fading toward top
                grad = cairo.LinearGradient(0, y, 0, h - 12)
                grad.add_color_stop_rgba(0.0, col[0], col[1], col[2], 0.95)
                grad.add_color_stop_rgba(1.0, col[0], col[1], col[2], 0.55)
                ctx.set_source(grad)
                ctx.rectangle(x, y, bar_w, bh)
                ctx.fill()
                # Top highlight pixel for the "polished" look
                ctx.set_source_rgba(1, 1, 1, 0.18)
                ctx.rectangle(x, y, bar_w, 1)
                ctx.fill()
            else:
                ctx.set_source_rgba(*WARM_BORDER, 0.4)
                ctx.rectangle(x, h - 13, bar_w, 1)
                ctx.fill()

        # Optional sparse labels at start/middle/end
        if self._labels and len(self._labels) >= 2:
            ctx.set_source_rgba(*PALE_COMB, 0.45)
            ctx.select_font_face("monospace", cairo.FONT_SLANT_NORMAL,
                                 cairo.FONT_WEIGHT_NORMAL)
            ctx.set_font_size(8.5)
            picks = [0, len(self._labels) // 2, len(self._labels) - 1]
            for idx in picks:
                lab = self._labels[idx]
                te = ctx.text_extents(lab)
                lx = idx * (bar_w + gap_px) + bar_w / 2 - te.width / 2
                lx = max(0, min(w - te.width, lx))
                ctx.move_to(lx, h - 2)
                ctx.show_text(lab)


# ── Horizontal severity bars ──────────────────────────────────────────────
class HorizontalBars(Gtk.DrawingArea):
    """Horizontal bars with label + count. Each row severity-colored."""

    def __init__(self) -> None:
        super().__init__()
        self.set_content_height(140)
        self.set_hexpand(True)
        # list of (label, count, color_rgb)
        self._rows: list[tuple[str, int, tuple[float, float, float]]] = []
        self.set_draw_func(self._on_draw)

    def set_rows(self, rows: Sequence[tuple[str, int, tuple[float, float, float]]]) -> None:
        self._rows = list(rows)
        self.queue_draw()

    def _on_draw(self, _a, ctx: cairo.Context, w: int, h: int) -> None:
        rows = self._rows
        if not rows:
            return
        vmax = max((r[1] for r in rows), default=1) or 1
        dot_x = 6
        dot_r = 5
        label_x = dot_x + dot_r * 2 + 8   # gap after the severity dot
        label_w = 70
        count_w = 60
        bar_x = label_x + label_w + 8
        bar_w_max = w - bar_x - count_w - 8
        row_h = h / max(1, len(rows))

        ctx.select_font_face("Inter", cairo.FONT_SLANT_NORMAL, cairo.FONT_WEIGHT_BOLD)
        ctx.set_font_size(11)

        for i, (label, cnt, col) in enumerate(rows):
            cy = i * row_h + row_h / 2

            # ── Severity colour dot (with soft halo) ──
            ctx.set_source_rgba(col[0], col[1], col[2], 0.30)
            ctx.arc(dot_x + dot_r, cy, dot_r + 3, 0, 2 * math.pi)
            ctx.fill()
            ctx.set_source_rgba(col[0], col[1], col[2], 1.0)
            ctx.arc(dot_x + dot_r, cy, dot_r, 0, 2 * math.pi)
            ctx.fill()

            # Label
            ctx.set_source_rgba(col[0], col[1], col[2], 0.95)
            te = ctx.text_extents(label)
            ctx.move_to(label_x, cy + te.height / 2)
            ctx.show_text(label)

            # Bar track
            track_y = cy - 5
            ctx.set_source_rgba(*WARM_BORDER, 0.35)
            self._round_rect(ctx, bar_x, track_y, bar_w_max, 10, 5)
            ctx.fill()

            # Bar fill (gradient)
            frac = (cnt / vmax) if cnt > 0 else 0
            bw = max(0.0, bar_w_max * frac)
            if bw > 0:
                grad = cairo.LinearGradient(bar_x, 0, bar_x + bw, 0)
                grad.add_color_stop_rgba(0.0, col[0], col[1], col[2], 0.95)
                grad.add_color_stop_rgba(1.0, col[0], col[1], col[2], 0.55)
                ctx.set_source(grad)
                self._round_rect(ctx, bar_x, track_y, bw, 10, 5)
                ctx.fill()
                # Soft outer glow
                ctx.set_source_rgba(col[0], col[1], col[2], 0.18)
                self._round_rect(ctx, bar_x - 1, track_y - 1, bw + 2, 12, 6)
                ctx.fill()

            # Count
            ctx.select_font_face("JetBrains Mono", cairo.FONT_SLANT_NORMAL,
                                 cairo.FONT_WEIGHT_BOLD)
            ctx.set_font_size(12)
            ctx.set_source_rgba(*PALE_COMB, 0.95)
            cnt_str = f"{cnt:,}"
            te = ctx.text_extents(cnt_str)
            ctx.move_to(w - te.width - 2, cy + te.height / 2)
            ctx.show_text(cnt_str)
            ctx.select_font_face("Inter", cairo.FONT_SLANT_NORMAL,
                                 cairo.FONT_WEIGHT_BOLD)
            ctx.set_font_size(11)

    @staticmethod
    def _round_rect(ctx: cairo.Context, x, y, w, h, r) -> None:
        r = min(r, w / 2, h / 2)
        ctx.new_sub_path()
        ctx.arc(x + w - r, y + r,     r, -math.pi / 2, 0)
        ctx.arc(x + w - r, y + h - r, r, 0,             math.pi / 2)
        ctx.arc(x + r,     y + h - r, r, math.pi / 2,   math.pi)
        ctx.arc(x + r,     y + r,     r, math.pi,       3 * math.pi / 2)
        ctx.close_path()


# ── KPI tile (premium card) ───────────────────────────────────────────────
class KpiTile(Gtk.Box):
    """Premium KPI card: title, big animated count-up number, sub-line,
    accent stripe, hover-glow (via CSS), trailing sparkline."""

    __gtype_name__ = "MeliKpiTile"

    def __init__(self, title: str, subtitle: str = "",
                 accent: tuple[float, float, float] = AMBER_GLOW,
                 sparkline: bool = True) -> None:
        super().__init__(orientation=Gtk.Orientation.VERTICAL, spacing=6)
        self.add_css_class("kpi-tile")
        self.set_hexpand(True)
        # Inner padding so children don't crash into the cairo-painted
        # border. set_margin_* on a Gtk.Box is outer margin; for inner
        # padding we put margins on the first/last child labels. The
        # simplest path is to give every direct child a uniform inset by
        # margin-padding them via a wrapper... but it's cleaner to apply
        # CSS padding via the .kpi-tile rule (already 14px 16px). The
        # cairo paint below fills the entire widget bounds, and CSS
        # padding pushes children inward, so we get the right look.
        # Mockup-matching honey-drip top stripe: HONEY → AMBER → ORANGE
        self._accent_top_edge = [
            (0xd4 / 255, 0xa0 / 255, 0x17 / 255),   # raw honey
            (0xf5 / 255, 0x9e / 255, 0x0b / 255),   # amber glow
            (0xea / 255, 0x7c / 255, 0x1c / 255),   # orange drip
        ]
        # State dot in the top-right (ok=pale, warn=orange, critical=red)
        self._state_dot = (0xfe / 255, 0xf3 / 255, 0xc7 / 255)
        self._state = "ok"

        title_lbl = Gtk.Label(label=title.upper())
        title_lbl.add_css_class("kpi-title")
        title_lbl.set_xalign(0)
        self.append(title_lbl)

        self._value = 0
        self._target = 0
        self._anim_id: int | None = None
        self._value_lbl = Gtk.Label(label="0")
        self._value_lbl.add_css_class("kpi-value")
        self._value_lbl.set_xalign(0)
        self.append(self._value_lbl)

        self._sub_lbl = Gtk.Label(label=subtitle)
        self._sub_lbl.add_css_class("kpi-sub")
        self._sub_lbl.set_xalign(0)
        self.append(self._sub_lbl)

        if sparkline:
            # Prominent area chart filling the bottom 40% of the card.
            # vexpand + valign=END forces it to claim all leftover height
            # below the labels instead of collapsing to its min size.
            self._spark = Sparkline(height=96, color=accent)
            self._spark.set_margin_top(10)
            self._spark.set_vexpand(True)
            self._spark.set_valign(Gtk.Align.FILL)
            self._spark.set_hexpand(True)
            self.append(self._spark)
        else:
            self._spark = None

        self._accent = accent
        self.connect("destroy", self._on_destroy)

    # Cairo-painted KPI tile chrome — luminous honey gradient + bright
    # amber top edge + outer glow. Bypasses the CSS engine entirely (the
    # same proven path HoneyPotWidget uses for the jar).
    def do_snapshot(self, snapshot: Gtk.Snapshot) -> None:
        # Local import to avoid a cycle at module-load time.
        from meli.ui.widgets.cairo_panel import paint_hive_panel
        import cairo as _cairo  # noqa: F401  (kept for type clarity)
        from gi.repository import Graphene as _Graphene
        w = float(self.get_width())
        h = float(self.get_height())
        if w > 0 and h > 0:
            rect = _Graphene.Rect().init(0, 0, w, h)
            ctx = snapshot.append_cairo(rect)
            paint_hive_panel(ctx, w, h,
                             radius=16.0,
                             top_edge=self._accent_top_edge,
                             glow_strength=1.3,
                             state_dot=self._state_dot)
        Gtk.Box.do_snapshot(self, snapshot)

    def set_value(self, target: int, sub: str | None = None,
                  state: str | None = None) -> None:
        """Animate the number from the current displayed value to `target`.
        `state` can be "ok" / "warn" / "critical" to flip the accent color.
        """
        self._target = int(target)
        if sub is not None:
            self._sub_lbl.set_text(sub)
        if state:
            # Reset previous state classes, then apply this one
            for s in ("ok", "warn", "critical"):
                self._value_lbl.remove_css_class(f"kpi-{s}")
            self._value_lbl.add_css_class(f"kpi-{state}")
            self._state = state
            self._state_dot = {
                "critical": (0xef / 255, 0x44 / 255, 0x44 / 255),
                "warn":     (0xf9 / 255, 0x73 / 255, 0x16 / 255),
                "ok":       (0xfe / 255, 0xf3 / 255, 0xc7 / 255),
            }.get(state, (0xfe / 255, 0xf3 / 255, 0xc7 / 255))
            self.queue_draw()
        if self._anim_id is None:
            self._anim_id = GLib.timeout_add(28, self._anim_step)

    def set_sparkline(self, values: Sequence[float]) -> None:
        if self._spark is not None:
            self._spark.set_values(values)

    def _anim_step(self) -> bool:
        if self._value == self._target:
            self._anim_id = None
            return False
        diff = self._target - self._value
        step = max(1, abs(diff) // 8) * (1 if diff > 0 else -1)
        self._value += step
        if (step > 0 and self._value > self._target) or (step < 0 and self._value < self._target):
            self._value = self._target
        self._value_lbl.set_text(f"{self._value:,}")
        return True

    def _on_destroy(self, *_a) -> None:
        if self._anim_id is not None:
            try:
                GLib.source_remove(self._anim_id)
            except Exception:
                pass
            self._anim_id = None


# ── Cairo-painted ranked-row badge ────────────────────────────────────────
class CairoBadge(Gtk.DrawingArea):
    """Rounded-square amber gradient badge with a number centred inside.

    Matches the mockup's TOP ATTACKERS / TOP CREDENTIALS rank badges:
    bright amber gradient, faint outer glow, deep-comb numeral.
    """

    __gtype_name__ = "MeliCairoBadge"

    def __init__(self, number: int | str, size: int = 28,
                 color: tuple[float, float, float] = AMBER_GLOW) -> None:
        super().__init__()
        self._number = str(number)
        self._color = color
        self._size = size
        self.set_size_request(size, size)
        self.set_content_width(size)
        self.set_content_height(size)
        self.set_draw_func(self._on_draw)

    def _on_draw(self, _a, ctx: cairo.Context, w: int, h: int) -> None:
        r, g, b = self._color
        pad = 3.0
        # Outer halo
        ctx.set_source_rgba(r, g, b, 0.30)
        self._round_rect(ctx, 0, 0, w, h, 7)
        ctx.fill()
        # Body gradient (top brighter, bottom darker)
        grad = cairo.LinearGradient(0, pad, 0, h - pad)
        grad.add_color_stop_rgb(0.0, min(1.0, r + 0.12),
                                 min(1.0, g + 0.10), min(1.0, b + 0.04))
        grad.add_color_stop_rgb(1.0, r * 0.75, g * 0.75, b * 0.65)
        ctx.set_source(grad)
        self._round_rect(ctx, pad, pad, w - 2 * pad, h - 2 * pad, 5)
        ctx.fill_preserve()
        # Inner top sheen
        sheen = cairo.LinearGradient(0, pad, 0, pad + (h - 2 * pad) * 0.4)
        sheen.add_color_stop_rgba(0.0, 1, 1, 1, 0.30)
        sheen.add_color_stop_rgba(1.0, 1, 1, 1, 0)
        ctx.set_source(sheen)
        ctx.fill()
        # Border
        ctx.set_source_rgba(r * 0.5, g * 0.5, b * 0.4, 1.0)
        ctx.set_line_width(1.0)
        self._round_rect(ctx, pad + 0.5, pad + 0.5,
                         w - 2 * pad - 1, h - 2 * pad - 1, 5)
        ctx.stroke()
        # Number (deep-comb, bold)
        ctx.set_source_rgb(0.12, 0.07, 0.02)
        ctx.select_font_face("Inter", cairo.FONT_SLANT_NORMAL,
                             cairo.FONT_WEIGHT_BOLD)
        ctx.set_font_size(13)
        te = ctx.text_extents(self._number)
        ctx.move_to(w / 2 - te.width / 2 - te.x_bearing,
                    h / 2 - te.height / 2 - te.y_bearing)
        ctx.show_text(self._number)

    @staticmethod
    def _round_rect(ctx, x, y, w, h, r):
        r = min(r, w / 2, h / 2)
        ctx.new_sub_path()
        ctx.arc(x + w - r, y + r,     r, -math.pi / 2, 0)
        ctx.arc(x + w - r, y + h - r, r, 0,             math.pi / 2)
        ctx.arc(x + r,     y + h - r, r, math.pi / 2,   math.pi)
        ctx.arc(x + r,     y + r,     r, math.pi,       3 * math.pi / 2)
        ctx.close_path()


# ── Cairo-painted country / tag chip ──────────────────────────────────────
class CairoChip(Gtk.DrawingArea):
    """Small rounded amber-outlined chip with text. Used for country tags
    (Tor-DE, VPN-NL) and small tag pills next to ranked rows."""

    __gtype_name__ = "MeliCairoChip"

    def __init__(self, text: str,
                 color: tuple[float, float, float] = AMBER_GLOW) -> None:
        super().__init__()
        self._text = text
        self._color = color
        # Measure text to size the widget
        surface = cairo.ImageSurface(cairo.FORMAT_ARGB32, 1, 1)
        ctx = cairo.Context(surface)
        ctx.select_font_face("JetBrains Mono", cairo.FONT_SLANT_NORMAL,
                             cairo.FONT_WEIGHT_BOLD)
        ctx.set_font_size(10)
        te = ctx.text_extents(text)
        w = int(te.width + 16)
        h = 18
        self.set_size_request(w, h)
        self.set_content_width(w)
        self.set_content_height(h)
        self.set_draw_func(self._on_draw)

    def _on_draw(self, _a, ctx: cairo.Context, w: int, h: int) -> None:
        r, g, b = self._color
        ctx.set_source_rgba(r, g, b, 0.14)
        CairoBadge._round_rect(ctx, 0, 0, w, h, 9)
        ctx.fill_preserve()
        ctx.set_source_rgba(r, g, b, 0.55)
        ctx.set_line_width(1.0)
        ctx.stroke()
        ctx.set_source_rgba(r, g, b, 1.0)
        ctx.select_font_face("JetBrains Mono", cairo.FONT_SLANT_NORMAL,
                             cairo.FONT_WEIGHT_BOLD)
        ctx.set_font_size(10)
        te = ctx.text_extents(self._text)
        ctx.move_to(w / 2 - te.width / 2 - te.x_bearing,
                    h / 2 - te.height / 2 - te.y_bearing)
        ctx.show_text(self._text)

"""Timeline / Historical view — attack charts over time."""
from __future__ import annotations

import gi
gi.require_version("Gtk", "4.0")
gi.require_version("Adw", "1")
from gi.repository import Gtk, Adw, GLib

import threading
import structlog
from datetime import datetime, timedelta, timezone

log = structlog.get_logger()


class TimelineView(Gtk.Box):
    def __init__(self) -> None:
        super().__init__(orientation=Gtk.Orientation.VERTICAL)
        self._period = "7d"
        self._build_ui()
        self.refresh()

    def _build_ui(self) -> None:
        header = Adw.HeaderBar()
        header.set_title_widget(Gtk.Label(label="Timeline / Historical"))

        period_box = Gtk.Box(spacing=4)
        for label, key in [("1h", "1h"), ("24h", "24h"), ("7d", "7d"), ("30d", "30d"), ("90d", "90d")]:
            btn = Gtk.ToggleButton(label=label)
            btn.set_active(key == "7d")
            btn.connect("toggled", self._on_period, key)
            period_box.append(btn)
        header.pack_end(period_box)

        refresh_btn = Gtk.Button.new_from_icon_name("view-refresh-symbolic")
        refresh_btn.connect("clicked", lambda _: self.refresh())
        header.pack_end(refresh_btn)
        self.append(header)

        scroll = Gtk.ScrolledWindow()
        scroll.set_vexpand(True)
        self._content = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=16)
        self._content.set_margin_all(24)
        self._status_label = Gtk.Label(label="Loading...")
        self._status_label.set_valign(Gtk.Align.CENTER)
        self._status_label.set_vexpand(True)
        self._content.append(self._status_label)
        scroll.set_child(self._content)
        self.append(scroll)

    def refresh(self) -> None:
        threading.Thread(target=self._load, daemon=True).start()

    def _load(self) -> None:
        try:
            from meli.database import get_db
            from meli.database.models import Event
            from sqlalchemy import func, select, and_

            now = datetime.now(timezone.utc)
            periods = {
                "1h": (now - timedelta(hours=1), "%H:%M", timedelta(minutes=5)),
                "24h": (now - timedelta(hours=24), "%H:%M", timedelta(hours=1)),
                "7d": (now - timedelta(days=7), "%a %d", timedelta(days=1)),
                "30d": (now - timedelta(days=30), "%b %d", timedelta(days=1)),
                "90d": (now - timedelta(days=90), "%b %d", timedelta(days=3)),
            }
            start, fmt, bucket = periods.get(self._period, periods["7d"])

            with get_db() as db:
                rows = db.execute(
                    select(Event.timestamp, Event.severity)
                    .where(Event.timestamp >= start)
                    .order_by(Event.timestamp)
                ).all()

            # Bucket into intervals
            buckets: dict[str, dict[str, int]] = {}
            t = start
            while t <= now:
                key = t.strftime(fmt)
                buckets[key] = {"CRITICAL": 0, "HIGH": 0, "MEDIUM": 0, "LOW": 0, "INFO": 0}
                t += bucket

            for ts, sev in rows:
                if ts:
                    ts_tz = ts.replace(tzinfo=timezone.utc) if ts.tzinfo is None else ts
                    key = ts_tz.strftime(fmt)
                    if key in buckets and sev in buckets[key]:
                        buckets[key][sev] += 1

            GLib.idle_add(self._render_chart, buckets)
        except Exception as e:
            log.error("Timeline load failed", error=str(e))
            GLib.idle_add(self._status_label.set_text, f"Error loading timeline: {e}")

    def _render_chart(self, buckets: dict) -> bool:
        child = self._content.get_first_child()
        while child:
            nxt = child.get_next_sibling()
            self._content.remove(child)
            child = nxt

        if not buckets:
            lbl = Gtk.Label(label="No data for this period")
            lbl.set_opacity(0.5)
            self._content.append(lbl)
            return False

        # ASCII-style bar chart using GTK widgets
        title = Gtk.Label(label=f"Attack Timeline — {self._period}")
        title.add_css_class("title-3")
        title.set_xalign(0)
        self._content.append(title)

        max_total = max(sum(v.values()) for v in buckets.values()) or 1
        chart_height = 120

        frame = Gtk.Frame()
        chart_box = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=2)
        chart_box.set_margin_all(8)
        chart_box.set_vexpand(False)
        chart_box.set_size_request(-1, chart_height + 40)

        colors = {"CRITICAL": "#ef4444", "HIGH": "#f97316", "MEDIUM": "#f59e0b",
                  "LOW": "#60a5fa", "INFO": "#94a3b8"}

        for label, sev_counts in buckets.items():
            total = sum(sev_counts.values())
            col = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=1)
            col.set_valign(Gtk.Align.END)
            col.set_hexpand(True)

            bar_h = max(2, int((total / max_total) * chart_height)) if total else 0
            bar = Gtk.Box()
            bar.set_size_request(-1, bar_h)
            if total > 0:
                most_severe = next(s for s in ["CRITICAL", "HIGH", "MEDIUM", "LOW", "INFO"]
                                   if sev_counts.get(s, 0) > 0)
                css = Gtk.CssProvider()
                color = colors.get(most_severe, "#94a3b8")
                css.load_from_string(f"box {{ background-color: {color}; border-radius: 2px; }}")
                bar.get_style_context().add_provider(css, 800)

            lbl = Gtk.Label(label=label)
            lbl.add_css_class("caption")
            lbl.set_opacity(0.6)

            col.append(bar)
            col.append(lbl)
            chart_box.append(col)

        frame.set_child(chart_box)
        self._content.append(frame)

        # Legend
        legend = Gtk.Box(spacing=12)
        legend.set_margin_top(8)
        for sev, color in colors.items():
            box = Gtk.Box(spacing=4)
            swatch = Gtk.Box()
            swatch.set_size_request(12, 12)
            css = Gtk.CssProvider()
            css.load_from_string(f"box {{ background-color: {color}; border-radius: 2px; }}")
            swatch.get_style_context().add_provider(css, 800)
            lbl = Gtk.Label(label=sev)
            lbl.add_css_class("caption")
            box.append(swatch)
            box.append(lbl)
            legend.append(box)
        self._content.append(legend)

        # Data table
        grp = Adw.PreferencesGroup(title="Data Table")
        for label, sev_counts in list(buckets.items())[-20:]:
            total = sum(sev_counts.values())
            if total > 0:
                grp.add(Adw.ActionRow(
                    title=label,
                    subtitle=f"Total: {total} | C:{sev_counts.get('CRITICAL',0)} H:{sev_counts.get('HIGH',0)} M:{sev_counts.get('MEDIUM',0)}"
                ))
        self._content.append(grp)
        return False

    def _on_period(self, btn: Gtk.ToggleButton, period: str) -> None:
        if btn.get_active():
            self._period = period
            self.refresh()

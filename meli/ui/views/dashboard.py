"""Dashboard view — Hive Command Center (v2.7.0).

Visual contract: matches the React mockup at
``artifacts/mockup-sandbox/src/components/mockups/meli/Dashboard.tsx``.

Layout (top → bottom):
  HiveHeader ("Hive Command Center · OPERATIONAL · UPTIME/INGEST/DB · avatar")
  ─ KPI row: Events/24h · Critical Alerts · Unique Attackers · Honeypots Online
  ─ 24h Attack Intensity (2/3) | Severity Breakdown (1/3)
  ─ Top Attacker IPs (1/2)     | Top Credentials Tried (1/2)
  ─ Hive Activity (2/5)        | Live Event Feed (3/5)
  ─ Honeypot Fleet — 6-up grid
"""
from __future__ import annotations

import gi
gi.require_version("Gtk", "4.0")
gi.require_version("Adw", "1")
from gi.repository import Gtk, GLib

import threading
import structlog
from collections import deque
from datetime import datetime, timedelta, timezone
from sqlalchemy import func, select, and_

from meli import event_bus
from meli.ui.widgets import (
    HoneyPotWidget, HiveHeader, KpiTile, MiniBarChart, HorizontalBars,
    CairoPanel,
    AMBER_GLOW, RAW_HONEY, STING_RED, BURNT_ORANGE, BEESWAX, PALE_COMB,
)

log = structlog.get_logger()


# ── Severity colour map for HorizontalBars (RGB tuples 0..1) ─────────
_SEV_BARS = [
    ("CRITICAL", STING_RED),
    ("HIGH",     BURNT_ORANGE),
    ("MEDIUM",   RAW_HONEY),
    ("LOW",      BEESWAX),
    ("INFO",     (0.65, 0.59, 0.50)),
]


def _section_header(title: str, accent: str | None = None) -> Gtk.Box:
    """Render the gold-bar + uppercase-tracked panel section header."""
    bar = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=10)
    stripe = Gtk.Box()
    stripe.add_css_class("hive-section-bar")
    stripe.set_size_request(5, 18)
    bar.append(stripe)
    title_lbl = Gtk.Label(label=title.upper())
    title_lbl.add_css_class("hive-section-title")
    title_lbl.set_xalign(0)
    bar.append(title_lbl)
    if accent:
        pill = Gtk.Label(label=accent)
        pill.add_css_class("hive-section-accent")
        bar.append(pill)
    spacer = Gtk.Box()
    spacer.set_hexpand(True)
    bar.append(spacer)
    return bar


def _panel(*, section: str, accent: str | None = None) -> tuple[Gtk.Widget, Gtk.Box]:
    """Create a hive-styled panel; returns (outer, body) so caller can
    append children into `body` after the section header is already in
    place.

    The outer widget is a `CairoPanel` — luminous honey gradient + glow
    are painted directly via cairo (CSS background-image is unreliable
    across GTK4 builds; this is the same proven path HoneyPotWidget uses
    for the jar).
    """
    outer = CairoPanel(orientation=Gtk.Orientation.VERTICAL,
                       spacing=12, padding=18, radius=14.0)
    outer.append(_section_header(section, accent))
    body = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=6)
    body.set_hexpand(True)
    outer.append(body)
    return outer, body


def _sev_class(sev: str | None) -> str:
    return (sev or "info").lower()


class DashboardView(Gtk.Box):
    def __init__(self) -> None:
        super().__init__(orientation=Gtk.Orientation.VERTICAL)
        self._refresh_id: int | None = None
        self._honey_pot: HoneyPotWidget | None = None
        # Rolling memory of sparkline series so the KPIs animate over
        # time rather than snap-jump on every refresh.
        self._spark_events = deque(maxlen=14)
        self._spark_critical = deque(maxlen=14)
        self._spark_attackers = deque(maxlen=14)
        self._spark_pots = deque(maxlen=14)
        self._build_ui()
        self.refresh()
        self._start_auto_refresh()
        event_bus.subscribe("event.ingested", self._on_ingest_signal)
        self.connect("destroy", self._on_destroy)

    def _on_ingest_signal(self, _topic: str, payload: dict) -> None:
        sev = (payload or {}).get("severity", "INFO")
        if self._honey_pot is not None:
            GLib.idle_add(self._honey_pot.pulse, sev)

    def _on_destroy(self, *_):
        event_bus.unsubscribe("event.ingested", self._on_ingest_signal)
        if self._refresh_id is not None:
            try:
                GLib.source_remove(self._refresh_id)
            except Exception:
                pass
            self._refresh_id = None

    # ── UI build ─────────────────────────────────────────────────────

    def _build_ui(self) -> None:
        # Hive header
        self._header = HiveHeader(title="Hive Command Center",
                                  status_label="OPERATIONAL",
                                  status_kind="operational")
        refresh_btn = Gtk.Button.new_from_icon_name("view-refresh-symbolic")
        refresh_btn.set_tooltip_text("Refresh (Ctrl+R)")
        refresh_btn.connect("clicked", lambda _: self.refresh())
        self._header.pack_end(refresh_btn)
        self._digest_btn = Gtk.Button(label="Build digest")
        self._digest_btn.set_tooltip_text(
            "Generate the last-24h Labyrinth digest report immediately")
        self._digest_btn.connect("clicked", lambda *_: self._build_digest_now())
        self._header.pack_end(self._digest_btn)
        self.append(self._header)

        # Scrolled content
        scroll = Gtk.ScrolledWindow()
        scroll.set_policy(Gtk.PolicyType.NEVER, Gtk.PolicyType.AUTOMATIC)
        scroll.set_vexpand(True)
        content = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=16)
        content.set_margin_top(20)
        content.set_margin_bottom(20)
        content.set_margin_start(20)
        content.set_margin_end(20)

        # ─── KPI tiles ────────────────────────────────────────────────
        kpi_row = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=14)
        kpi_row.set_homogeneous(True)
        self._kpi_events = KpiTile("Events / 24h", subtitle="—", accent=AMBER_GLOW)
        self._kpi_critical = KpiTile("Critical Alerts", subtitle="—", accent=STING_RED)
        self._kpi_attackers = KpiTile("Unique Attackers", subtitle="—", accent=BURNT_ORANGE)
        self._kpi_pots = KpiTile("Honeypots Online", subtitle="—", accent=RAW_HONEY)
        for k in (self._kpi_events, self._kpi_critical,
                  self._kpi_attackers, self._kpi_pots):
            kpi_row.append(k)
        content.append(kpi_row)

        # ─── HERO ROW (matches mockup): Big jar centerpiece LEFT +
        #     Severity (24h) + Top Attackers stacked RIGHT ─────────────
        hero = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=14)

        # — LEFT: Jar centerpiece panel (cairo-painted hive backdrop)
        jar_panel = CairoPanel(orientation=Gtk.Orientation.VERTICAL,
                               spacing=8, padding=20, radius=16.0,
                               glow_strength=1.4)
        jar_panel.set_hexpand(True)
        jar_panel.set_size_request(560, 460)

        # The honey-jar drawing area, scaled up to ~440px tall
        self._honey_pot = HoneyPotWidget()
        self._honey_pot.set_size_request(380, 420)
        self._honey_pot.set_content_width(380)
        self._honey_pot.set_content_height(420)
        self._honey_pot.set_hexpand(True)
        self._honey_pot.set_vexpand(True)
        self._honey_pot.set_halign(Gtk.Align.CENTER)
        self._honey_pot.set_valign(Gtk.Align.CENTER)

        # Overlay corner stats around the jar
        jar_overlay = Gtk.Overlay()
        jar_overlay.set_hexpand(True)
        jar_overlay.set_vexpand(True)
        jar_overlay.set_child(self._honey_pot)

        def _corner(halign, valign, margin=14):
            box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=2)
            box.set_halign(halign)
            box.set_valign(valign)
            box.set_margin_top(margin)
            box.set_margin_bottom(margin)
            box.set_margin_start(margin)
            box.set_margin_end(margin)
            return box

        # TOP-RIGHT: CAPACITY 78% / 2,762 captured
        cap_box = _corner(Gtk.Align.END, Gtk.Align.START)
        cap_title = Gtk.Label(label="POT CAPACITY")
        cap_title.add_css_class("hive-corner-title")
        cap_title.set_halign(Gtk.Align.END)
        self._cap_value = Gtk.Label(label="—")
        self._cap_value.add_css_class("hive-corner-value")
        self._cap_value.set_halign(Gtk.Align.END)
        self._cap_sub = Gtk.Label(label="0 events captured")
        self._cap_sub.add_css_class("hive-corner-sub")
        self._cap_sub.set_halign(Gtk.Align.END)
        cap_box.append(cap_title)
        cap_box.append(self._cap_value)
        cap_box.append(self._cap_sub)
        jar_overlay.add_overlay(cap_box)

        # BOTTOM-LEFT: LAST STRIKE
        ls_box = _corner(Gtk.Align.START, Gtk.Align.END)
        ls_title = Gtk.Label(label="LAST STRIKE")
        ls_title.add_css_class("hive-corner-title")
        ls_title.set_halign(Gtk.Align.START)
        self._ls_value = Gtk.Label(label="—")
        self._ls_value.add_css_class("hive-corner-strike")
        self._ls_value.set_halign(Gtk.Align.START)
        self._ls_ip = Gtk.Label(label="")
        self._ls_ip.add_css_class("hive-corner-ip")
        self._ls_ip.set_halign(Gtk.Align.START)
        ls_box.append(ls_title)
        ls_box.append(self._ls_value)
        ls_box.append(self._ls_ip)
        jar_overlay.add_overlay(ls_box)

        # BOTTOM-RIGHT: STRIKES / HR
        sh_box = _corner(Gtk.Align.END, Gtk.Align.END)
        sh_title = Gtk.Label(label="STRIKES / HR")
        sh_title.add_css_class("hive-corner-title")
        sh_title.set_halign(Gtk.Align.END)
        self._sh_value = Gtk.Label(label="0")
        self._sh_value.add_css_class("hive-corner-strikes")
        self._sh_value.set_halign(Gtk.Align.END)
        sh_box.append(sh_title)
        sh_box.append(self._sh_value)
        jar_overlay.add_overlay(sh_box)

        jar_panel.append(jar_overlay)
        hero.append(jar_panel)

        # — RIGHT: stacked Severity + Top Attackers
        right_col = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=14)
        right_col.set_size_request(380, -1)

        # Severity panel
        sev_panel, sev_body = _panel(section="Severity (24h)")
        self._sev_bars = HorizontalBars()
        sev_body.append(self._sev_bars)
        right_col.append(sev_panel)

        # Top attackers panel
        self._top_attk_panel, self._top_attk_body = _panel(
            section="Top Attackers", accent="LAST 24H")
        self._top_attk_panel.set_vexpand(True)
        right_col.append(self._top_attk_panel)

        hero.append(right_col)
        content.append(hero)

        # ─── 24h Attack Intensity (full width, below hero) ───────────
        intensity_panel, intensity_body = _panel(
            section="24h Attack Intensity", accent="HOURLY")
        self._intensity_chart = MiniBarChart(height=110)
        intensity_body.append(self._intensity_chart)
        axis = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL)
        for lbl in ("00:00", "06:00", "12:00", "18:00", "NOW"):
            l = Gtk.Label(label=lbl)
            l.add_css_class("text-muted")
            l.set_hexpand(True)
            l.set_xalign(0.5)
            axis.append(l)
        intensity_body.append(axis)
        content.append(intensity_panel)

        # ─── Top Credentials + Live Feed ─────────────────────────────
        tops = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=14)
        self._top_cred_panel, self._top_cred_body = _panel(
            section="Top Credentials Tried")
        self._top_cred_panel.set_size_request(380, -1)
        self._ticker_panel, self._ticker_body = _panel(
            section="Live Event Feed", accent="STREAMING")
        self._ticker_panel.set_hexpand(True)
        tops.append(self._top_cred_panel)
        tops.append(self._ticker_panel)
        content.append(tops)

        # ─── Honeypot Fleet ──────────────────────────────────────────
        self._fleet_panel, self._fleet_body = _panel(
            section="Honeypot Fleet", accent="ACTIVE")
        # Body is a vertical box; we'll replace with a Gtk.Grid each refresh
        self._fleet_grid_holder = Gtk.Box(orientation=Gtk.Orientation.VERTICAL)
        self._fleet_body.append(self._fleet_grid_holder)
        content.append(self._fleet_panel)

        scroll.set_child(content)
        self.append(scroll)

    # ── Data load ────────────────────────────────────────────────────

    def refresh(self) -> None:
        threading.Thread(target=self._load_data, daemon=True).start()

    def _load_data(self) -> None:
        try:
            from meli.database import get_db
            from meli.database.models import (
                Event, Alert, Credential, Honeypot)
            now = datetime.now(timezone.utc)
            ago_24h = now - timedelta(hours=24)
            ago_1h = now - timedelta(hours=1)
            ago_7d = now - timedelta(days=7)

            with get_db() as db:
                total = db.execute(select(func.count(Event.id))).scalar() or 0
                last_24h = db.execute(
                    select(func.count(Event.id))
                    .where(Event.timestamp >= ago_24h)
                ).scalar() or 0
                last_1h = db.execute(
                    select(func.count(Event.id))
                    .where(Event.timestamp >= ago_1h)
                ).scalar() or 0
                last_7d = db.execute(
                    select(func.count(Event.id))
                    .where(Event.timestamp >= ago_7d)
                ).scalar() or 0
                critical_unacked = db.execute(
                    select(func.count(Alert.id)).where(and_(
                        Alert.severity == "CRITICAL",
                        Alert.acknowledged == False))  # noqa: E712
                ).scalar() or 0
                unique_attackers = db.execute(
                    select(func.count(func.distinct(Event.source_ip)))
                    .where(Event.timestamp >= ago_24h)
                ).scalar() or 0

                # Severity breakdown (24h)
                sev_rows = db.execute(
                    select(Event.severity, func.count(Event.id))
                    .where(Event.timestamp >= ago_24h)
                    .group_by(Event.severity)
                ).all()
                sev_data = {r[0]: r[1] for r in sev_rows}

                # Hourly buckets — 24 ints, oldest → newest
                hourly = [0] * 24
                rows = db.execute(
                    select(Event.timestamp)
                    .where(Event.timestamp >= ago_24h)
                ).all()
                for (ts,) in rows:
                    if ts is None:
                        continue
                    if ts.tzinfo is None:
                        ts = ts.replace(tzinfo=timezone.utc)
                    delta_h = int((now - ts).total_seconds() // 3600)
                    if 0 <= delta_h < 24:
                        hourly[23 - delta_h] += 1

                # Top attackers (24h)
                top_attk = db.execute(
                    select(Event.source_ip,
                           Event.country_code,
                           func.count(Event.id).label("cnt"))
                    .where(Event.timestamp >= ago_24h)
                    .group_by(Event.source_ip, Event.country_code)
                    .order_by(func.count(Event.id).desc())
                    .limit(5)
                ).all()

                # Top creds — Credential model has source_honeypots
                # (JSON list) not honeypot_service. Parse it in render.
                top_creds = db.execute(
                    select(Credential.username,
                           Credential.password,
                           Credential.attempt_count,
                           Credential.source_honeypots)
                    .order_by(Credential.attempt_count.desc())
                    .limit(5)
                ).all()

                # Live ticker — most-recent 8 events
                recent = db.execute(
                    select(Event).order_by(Event.timestamp.desc()).limit(8)
                ).scalars().all()
                # Event model has parsed_data (JSON text), not event_data.
                def _msg(ev):
                    raw = getattr(ev, "parsed_data", None)
                    if not raw:
                        return ""
                    try:
                        import json as _json
                        d = _json.loads(raw) if isinstance(raw, str) else raw
                        if isinstance(d, dict):
                            return str(d.get("message")
                                       or d.get("msg")
                                       or d.get("command")
                                       or d.get("input")
                                       or "")[:120]
                    except Exception:
                        pass
                    return ""
                recent_data = [(e.timestamp, e.source_ip, e.honeypot_service,
                                e.severity, _msg(e))
                               for e in recent]

                # Fleet
                honeypots = db.execute(select(Honeypot)).scalars().all()
                fleet_data = []
                for h in honeypots:
                    last_event = getattr(h, "last_event_at", None)
                    is_recent = (
                        last_event is not None
                        and (now - (last_event.replace(tzinfo=timezone.utc)
                                    if last_event.tzinfo is None
                                    else last_event)).total_seconds() < 3600
                    )
                    if not h.enabled:
                        status = "offline"
                    elif last_event is None:
                        status = "warning"
                    elif is_recent:
                        status = "online"
                    else:
                        status = "warning"
                    # Per-pot 24h count
                    cnt = db.execute(
                        select(func.count(Event.id)).where(and_(
                            Event.honeypot_service == h.honeypot_type,
                            Event.timestamp >= ago_24h))
                    ).scalar() or 0
                    fleet_data.append((h.name or h.honeypot_type,
                                       h.honeypot_type, status, cnt))

            GLib.idle_add(self._update_ui, total, last_24h, last_1h, last_7d,
                          critical_unacked, unique_attackers, sev_data,
                          hourly, list(top_attk), list(top_creds),
                          recent_data, fleet_data)
        except Exception as e:
            log.error("Dashboard load failed", error=str(e))

    # ── UI update ────────────────────────────────────────────────────

    def _update_ui(self, total, last_24h, last_1h, last_7d,
                   critical_unacked, unique_attackers,
                   sev_data, hourly,
                   top_attk, top_creds, recent_data, fleet_data) -> bool:
        # HoneyPot fill (rolling 7-day window)
        if self._honey_pot is not None:
            self._honey_pot.set_event_count(last_7d)

        # Jar corner stats — match mockup
        import math as _math
        max_cap = max(getattr(self._honey_pot, "_max_events", 5000), 1)
        if last_7d <= 0:
            pct = 0
        else:
            pct = int(round(
                100.0 * _math.log10(last_7d + 1) / _math.log10(max_cap + 1)))
            pct = max(0, min(100, pct))
        self._cap_value.set_markup(
            f"<span size='28000' weight='bold'>{pct}</span>"
            f"<span size='14000'>%</span>")
        self._cap_sub.set_text(f"{last_7d:,} events captured")

        # Last strike from recent_data (newest first)
        if recent_data:
            ts, ip, _svc, _sev, _msg = recent_data[0]
            try:
                if ts.tzinfo is None:
                    ts = ts.replace(tzinfo=timezone.utc)
                delta = (datetime.now(timezone.utc) - ts).total_seconds()
                if delta < 60:
                    rel = f"{int(delta)} sec ago"
                elif delta < 3600:
                    rel = f"{int(delta // 60)} min ago"
                elif delta < 86400:
                    rel = f"{int(delta // 3600)} hr ago"
                else:
                    rel = f"{int(delta // 86400)} d ago"
            except Exception:
                rel = "—"
            self._ls_value.set_text(rel)
            self._ls_ip.set_text(ip or "")
        else:
            self._ls_value.set_text("none yet")
            self._ls_ip.set_text("")

        # Strikes per hour — last_1h is already that number
        self._sh_value.set_markup(
            f"<span size='28000' weight='bold'>{last_1h}</span>")

        # KPI tiles + animated sparklines
        self._spark_events.append(last_24h)
        self._spark_critical.append(critical_unacked)
        self._spark_attackers.append(unique_attackers)
        online = sum(1 for *_, st, _ in fleet_data if st == "online")
        total_pots = max(len(fleet_data), 1)
        self._spark_pots.append(online)

        ev_delta = (last_24h - last_1h * 24) if last_24h else 0
        self._kpi_events.set_value(
            last_24h,
            sub=("↗ trending up" if ev_delta >= 0 else "↘ slowing"),
            state="ok")
        self._kpi_events.set_sparkline(list(self._spark_events))

        self._kpi_critical.set_value(
            critical_unacked,
            sub=("unacknowledged" if critical_unacked
                 else "no critical alerts"),
            state=("critical" if critical_unacked else "ok"))
        self._kpi_critical.set_sparkline(list(self._spark_critical))

        self._kpi_attackers.set_value(
            unique_attackers,
            sub=f"in last 24h",
            state=("warn" if unique_attackers > 50 else "ok"))
        self._kpi_attackers.set_sparkline(list(self._spark_attackers))

        # Honeypots online — show as count but label includes total
        self._kpi_pots.set_value(
            online,
            sub=f"of {total_pots} configured",
            state=("ok" if online == total_pots else "warn"))
        self._kpi_pots.set_sparkline(list(self._spark_pots))

        # Intensity bar chart
        self._intensity_chart.set_data(hourly)

        # Severity horizontal bars
        rows = []
        for sev, color in _SEV_BARS:
            rows.append((sev, sev_data.get(sev, 0), color))
        self._sev_bars.set_rows(rows)

        # Top attacker IPs
        self._clear(self._top_attk_body)
        if not top_attk:
            empty = Gtk.Label(label="No events captured yet")
            empty.add_css_class("text-muted")
            self._top_attk_body.append(empty)
        for i, (ip, cc, cnt) in enumerate(top_attk, start=1):
            self._top_attk_body.append(
                self._rank_row(i, ip or "—",
                               f"{cc or '??'} · {cnt} events", cnt))

        # Top credentials
        self._clear(self._top_cred_body)
        if not top_creds:
            empty = Gtk.Label(label="No credentials captured yet")
            empty.add_css_class("text-muted")
            self._top_cred_body.append(empty)
        for i, (user, pwd, cnt, src_honeypots) in enumerate(top_creds, start=1):
            label = f"{user or '—'} : {pwd or '—'}"
            # source_honeypots is JSON list-as-text: ["cowrie","heralding"]
            svc = "—"
            if src_honeypots:
                try:
                    import json as _json
                    items = _json.loads(src_honeypots) if isinstance(
                        src_honeypots, str) else src_honeypots
                    if isinstance(items, list) and items:
                        svc = ", ".join(str(x) for x in items[:3])
                except Exception:
                    svc = str(src_honeypots)[:24]
            self._top_cred_body.append(
                self._rank_row(i, label, f"{svc} · {cnt}x", cnt))

        # Live ticker
        self._clear(self._ticker_body)
        if not recent_data:
            empty = Gtk.Label(label="No live events — connect a honeypot")
            empty.add_css_class("text-muted")
            self._ticker_body.append(empty)
        for ts, ip, svc, sev, msg in recent_data:
            self._ticker_body.append(self._ticker_row(ts, ip, svc, sev, msg))

        # Fleet
        self._clear(self._fleet_grid_holder)
        grid = Gtk.Grid(column_spacing=10, row_spacing=10)
        grid.set_column_homogeneous(True)
        cols = 6
        for idx, (name, ptype, status, cnt) in enumerate(fleet_data):
            grid.attach(self._fleet_card(name, ptype, status, cnt),
                        idx % cols, idx // cols, 1, 1)
        if not fleet_data:
            empty = Gtk.Label(
                label="No honeypots configured — add one in Settings")
            empty.add_css_class("text-muted")
            grid.attach(empty, 0, 0, cols, 1)
        self._fleet_grid_holder.append(grid)

        # Header pill — turn red if there are unacked criticals
        try:
            if critical_unacked > 0:
                self._header.set_status(
                    f"{critical_unacked} CRITICAL UNACKED", "critical")
            else:
                self._header.set_status("OPERATIONAL", "operational")
        except Exception:
            pass

        return False

    # ── Row builders ─────────────────────────────────────────────────

    def _rank_row(self, n: int, primary: str, secondary: str,
                  count: int) -> Gtk.Box:
        row = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=10)
        row.add_css_class("rank-row")
        badge = Gtk.Label(label=str(n))
        badge.add_css_class("rank-badge")
        badge.set_size_request(24, 24)
        row.append(badge)
        col = Gtk.Box(orientation=Gtk.Orientation.VERTICAL)
        col.set_hexpand(True)
        p = Gtk.Label(label=primary)
        p.add_css_class("text-pale")
        p.add_css_class("mono")
        p.set_xalign(0)
        p.set_ellipsize(3)
        s = Gtk.Label(label=secondary)
        s.add_css_class("text-muted")
        s.set_xalign(0)
        col.append(p)
        col.append(s)
        row.append(col)
        c = Gtk.Label(label=f"{count:,}")
        c.add_css_class("text-amber")
        c.add_css_class("mono")
        row.append(c)
        return row

    def _ticker_row(self, ts, ip, svc, sev, msg) -> Gtk.Box:
        sev_cls = _sev_class(sev)
        row = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=8)
        row.add_css_class("ticker-row")
        row.add_css_class(sev_cls)
        t = Gtk.Label(label=ts.strftime("%H:%M:%S") if ts else "--:--:--")
        t.add_css_class("ticker-time")
        row.append(t)
        sev_pill = Gtk.Label(label=(sev or "INFO").upper())
        sev_pill.add_css_class("ticker-sev-pill")
        sev_pill.add_css_class(f"ticker-sev-{sev_cls}")
        row.append(sev_pill)
        ip_lbl = Gtk.Label(label=ip or "—")
        ip_lbl.add_css_class("ticker-ip")
        row.append(ip_lbl)
        svc_lbl = Gtk.Label(label=svc or "—")
        svc_lbl.add_css_class("ticker-svc")
        row.append(svc_lbl)
        msg_lbl = Gtk.Label(label=(msg or "")[:80])
        msg_lbl.add_css_class("ticker-msg")
        msg_lbl.set_xalign(0)
        msg_lbl.set_hexpand(True)
        msg_lbl.set_ellipsize(3)
        row.append(msg_lbl)
        return row

    def _fleet_card(self, name: str, _ptype: str, status: str,
                    count: int) -> Gtk.Box:
        card = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=4)
        card.add_css_class("fleet-card")
        head = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=6)
        dot = Gtk.Box()
        dot.add_css_class("state-dot")
        dot.add_css_class(status)
        dot.set_size_request(8, 8)
        head.append(dot)
        n = Gtk.Label(label=name)
        n.add_css_class("fleet-name")
        n.set_xalign(0)
        n.set_ellipsize(3)
        head.append(n)
        card.append(head)
        v = Gtk.Label(label=f"{count:,}")
        v.add_css_class("fleet-events")
        v.set_xalign(0)
        card.append(v)
        l = Gtk.Label(label="EVENTS / 24H")
        l.add_css_class("fleet-events-label")
        l.set_xalign(0)
        card.append(l)
        return card

    @staticmethod
    def _clear(box: Gtk.Box) -> None:
        child = box.get_first_child()
        while child:
            nxt = child.get_next_sibling()
            box.remove(child)
            child = nxt

    # ── Background tasks ─────────────────────────────────────────────

    def _start_auto_refresh(self) -> None:
        from meli.config import get_config
        seconds = get_config().get("general", "auto_refresh_seconds",
                                   default=30)
        self._refresh_id = GLib.timeout_add_seconds(
            seconds, self._auto_refresh)

    def _auto_refresh(self) -> bool:
        self.refresh()
        return True

    # ── On-demand digest (preserved from previous dashboard) ─────────

    def _build_digest_now(self) -> None:
        btn = getattr(self, "_digest_btn", None)
        if btn is not None:
            if not btn.get_sensitive():
                return
            btn.set_sensitive(False)
            btn.set_label("Building digest…")

        def _worker():
            err = None
            out_path = None
            try:
                from meli.labyrinth import digest
                from pathlib import Path
                out_path = digest.write(digest.default_path(), hours=24)
                out_path = Path(str(out_path))
                log.info("digest built on demand", path=str(out_path))
            except Exception as e:
                err = str(e)
                log.warning("digest build failed", error=err)
            GLib.idle_add(self._show_digest_result, out_path, err)

        threading.Thread(target=_worker, name="meli-digest-ondemand",
                         daemon=True).start()

    def _show_digest_result(self, out_path, err) -> bool:
        from gi.repository import Adw
        btn = getattr(self, "_digest_btn", None)
        if btn is not None:
            btn.set_sensitive(True)
            btn.set_label("Build digest")
        root = self.get_root()
        dlg = Adw.MessageDialog()
        if isinstance(root, Gtk.Window):
            dlg.set_transient_for(root)
        dlg.set_modal(True)
        if err:
            dlg.set_heading("Digest build failed")
            dlg.set_body(err)
        else:
            dlg.set_heading("Digest built")
            dlg.set_body(f"Saved to:\n{out_path}")
        dlg.add_response("ok", "OK")
        dlg.set_default_response("ok")
        dlg.set_close_response("ok")
        dlg.present()
        return False

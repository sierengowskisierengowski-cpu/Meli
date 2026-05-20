"""Dashboard view — home screen with stat cards, live feed, and charts."""
from __future__ import annotations

import gi
gi.require_version("Gtk", "4.0")
gi.require_version("Adw", "1")
from gi.repository import Gtk, Adw, GLib

import json
import threading
import structlog
from datetime import datetime, timedelta, timezone
from sqlalchemy import func, select, and_

log = structlog.get_logger()


class DashboardView(Gtk.Box):
    def __init__(self) -> None:
        super().__init__(orientation=Gtk.Orientation.VERTICAL)
        self._refresh_id: int | None = None
        self._build_ui()
        self.refresh()
        self._start_auto_refresh()

    def _build_ui(self) -> None:
        # Header
        header = Adw.HeaderBar()
        header.set_title_widget(Gtk.Label(label="Dashboard"))
        header.add_css_class("meli-header")
        refresh_btn = Gtk.Button.new_from_icon_name("view-refresh-symbolic")
        refresh_btn.connect("clicked", lambda _: self.refresh())
        refresh_btn.set_tooltip_text("Refresh (Ctrl+R)")
        header.pack_end(refresh_btn)
        self.append(header)

        scroll = Gtk.ScrolledWindow()
        scroll.set_policy(Gtk.PolicyType.NEVER, Gtk.PolicyType.AUTOMATIC)
        scroll.set_vexpand(True)

        content = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=20)
        content.set_margin_all(24)

        # Stat cards row
        self._cards_row = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=12)
        self._cards_row.set_homogeneous(True)
        self._card_total = self._make_stat_card("Total Events", "—", "All time")
        self._card_24h = self._make_stat_card("Last 24h", "—", "Events")
        self._card_1h = self._make_stat_card("Last Hour", "—", "Events")
        self._card_critical = self._make_stat_card("Critical Unacked", "—", "Alerts")
        for card in [self._card_total, self._card_24h, self._card_1h, self._card_critical]:
            self._cards_row.append(card)
        content.append(self._cards_row)

        # Middle row: severity + top attackers + top creds
        mid = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=12)

        self._sev_box = self._make_section("Severity Breakdown")
        self._sev_content = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=4)
        self._sev_box.append(self._sev_content)
        mid.append(self._sev_box)

        self._top_attk_box = self._make_section("Top Attackers Today")
        self._top_attk_list = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=2)
        self._top_attk_box.append(self._top_attk_list)
        mid.append(self._top_attk_box)

        self._top_cred_box = self._make_section("Top Credentials Today")
        self._top_cred_list = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=2)
        self._top_cred_box.append(self._top_cred_list)
        mid.append(self._top_cred_box)

        for box in [self._sev_box, self._top_attk_box, self._top_cred_box]:
            box.set_hexpand(True)
        content.append(mid)

        # Recent events
        recent_section = self._make_section("Recent Events")
        self._recent_list = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=2)
        recent_section.append(self._recent_list)
        content.append(recent_section)

        # Service health
        health_section = self._make_section("Honeypot Health")
        self._health_list = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=8)
        health_section.append(self._health_list)
        content.append(health_section)

        scroll.set_child(content)
        self.append(scroll)

    def refresh(self) -> None:
        threading.Thread(target=self._load_data, daemon=True).start()

    def _load_data(self) -> None:
        try:
            from meli.database import get_db
            from meli.database.models import Event, Alert, Attacker, Credential
            now = datetime.now(timezone.utc)
            ago_24h = now - timedelta(hours=24)
            ago_1h = now - timedelta(hours=1)

            with get_db() as db:
                total = db.execute(select(func.count(Event.id))).scalar() or 0
                last_24h = db.execute(
                    select(func.count(Event.id)).where(Event.timestamp >= ago_24h)
                ).scalar() or 0
                last_1h = db.execute(
                    select(func.count(Event.id)).where(Event.timestamp >= ago_1h)
                ).scalar() or 0
                critical_unacked = db.execute(
                    select(func.count(Alert.id)).where(
                        and_(Alert.severity == "CRITICAL", Alert.acknowledged == False)
                    )
                ).scalar() or 0

                # Severity breakdown
                sev_rows = db.execute(
                    select(Event.severity, func.count(Event.id))
                    .where(Event.timestamp >= ago_24h)
                    .group_by(Event.severity)
                ).all()
                sev_data = {r[0]: r[1] for r in sev_rows}

                # Top attackers
                top_attk = db.execute(
                    select(Event.source_ip, func.count(Event.id).label("cnt"))
                    .where(Event.timestamp >= ago_24h)
                    .group_by(Event.source_ip)
                    .order_by(func.count(Event.id).desc()).limit(5)
                ).all()

                # Top credentials
                top_creds = db.execute(
                    select(Credential.username, Credential.password, Credential.attempt_count)
                    .order_by(Credential.attempt_count.desc()).limit(5)
                ).all()

                # Recent events
                recent = db.execute(
                    select(Event)
                    .order_by(Event.timestamp.desc()).limit(10)
                ).scalars().all()
                recent_data = [
                    (e.timestamp, e.source_ip, e.honeypot_service, e.severity, e.country_code)
                    for e in recent
                ]

                # Health
                from meli.database.models import Honeypot
                honeypots = db.execute(select(Honeypot)).scalars().all()
                health_data = [(h.name, h.honeypot_type, h.enabled, h.last_event_at) for h in honeypots]

            GLib.idle_add(self._update_ui, total, last_24h, last_1h, critical_unacked,
                          sev_data, list(top_attk), list(top_creds), recent_data, health_data)
        except Exception as e:
            log.error("Dashboard load failed", error=str(e))

    def _update_ui(self, total, last_24h, last_1h, critical_unacked,
                   sev_data, top_attk, top_creds, recent_data, health_data) -> bool:
        self._update_card(self._card_total, f"{total:,}")
        self._update_card(self._card_24h, f"{last_24h:,}")
        self._update_card(self._card_1h, f"{last_1h:,}")
        self._update_card(self._card_critical, str(critical_unacked),
                          "critical" if critical_unacked > 0 else None)

        # Severity
        self._clear(self._sev_content)
        for sev in ["CRITICAL", "HIGH", "MEDIUM", "LOW", "INFO"]:
            cnt = sev_data.get(sev, 0)
            row = Gtk.Box(spacing=8)
            lbl = Gtk.Label(label=sev)
            lbl.add_css_class(f"severity-{sev.lower()}")
            lbl.set_xalign(0)
            lbl.set_size_request(80, -1)
            val = Gtk.Label(label=f"{cnt:,}")
            val.set_hexpand(True)
            val.set_xalign(1)
            row.append(lbl)
            row.append(val)
            self._sev_content.append(row)

        # Top attackers
        self._clear(self._top_attk_list)
        for ip, cnt in top_attk:
            row = Gtk.Box(spacing=8)
            ip_lbl = Gtk.Label(label=ip or "—")
            ip_lbl.add_css_class("monospace")
            ip_lbl.set_xalign(0)
            ip_lbl.set_hexpand(True)
            cnt_lbl = Gtk.Label(label=f"{cnt:,}")
            row.append(ip_lbl)
            row.append(cnt_lbl)
            self._top_attk_list.append(row)
        if not top_attk:
            self._top_attk_list.append(Gtk.Label(label="No events yet"))

        # Top credentials
        self._clear(self._top_cred_list)
        for user, pwd, cnt in top_creds:
            row = Gtk.Box(spacing=4)
            lbl = Gtk.Label(label=f"{user}:{pwd}")
            lbl.add_css_class("monospace")
            lbl.set_xalign(0)
            lbl.set_hexpand(True)
            lbl.set_ellipsize(3)  # END
            cnt_lbl = Gtk.Label(label=str(cnt))
            row.append(lbl)
            row.append(cnt_lbl)
            self._top_cred_list.append(row)
        if not top_creds:
            self._top_cred_list.append(Gtk.Label(label="No credentials captured"))

        # Recent events
        self._clear(self._recent_list)
        for ts, ip, service, severity, country in recent_data:
            row = Gtk.Box(spacing=8)
            row.set_margin_top(2)
            row.set_margin_bottom(2)
            ts_lbl = Gtk.Label(label=str(ts)[:19] if ts else "—")
            ts_lbl.add_css_class("monospace")
            ts_lbl.set_size_request(160, -1)
            sev_lbl = Gtk.Label(label=severity or "—")
            sev_lbl.add_css_class(f"severity-{(severity or 'info').lower()}")
            sev_lbl.set_size_request(80, -1)
            ip_lbl = Gtk.Label(label=ip or "—")
            ip_lbl.add_css_class("monospace")
            ip_lbl.set_size_request(140, -1)
            svc_lbl = Gtk.Label(label=service or "—")
            svc_lbl.set_hexpand(True)
            for w in [ts_lbl, sev_lbl, ip_lbl, svc_lbl]:
                row.append(w)
            self._recent_list.append(row)
        if not recent_data:
            self._recent_list.append(Gtk.Label(label="No events yet — connect a honeypot to start receiving data"))

        # Health
        self._clear(self._health_list)
        now = datetime.now(timezone.utc)
        for name, hp_type, enabled, last_event in health_data:
            card = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=4)
            card.add_css_class("stat-card")
            card.set_size_request(120, -1)
            name_lbl = Gtk.Label(label=name)
            name_lbl.add_css_class("caption-heading")
            type_lbl = Gtk.Label(label=hp_type)
            type_lbl.add_css_class("caption")
            type_lbl.set_opacity(0.6)
            if not enabled:
                status = "Disabled"
                color = "severity-info"
            elif last_event and (now - last_event.replace(tzinfo=timezone.utc if last_event.tzinfo is None else last_event.tzinfo)).total_seconds() < 3600:
                status = "Online"
                color = "severity-low"
            elif last_event:
                status = "Stale"
                color = "severity-medium"
            else:
                status = "No data"
                color = "severity-info"
            status_lbl = Gtk.Label(label=status)
            status_lbl.add_css_class(color)
            for w in [name_lbl, type_lbl, status_lbl]:
                card.append(w)
            self._health_list.append(card)
        if not health_data:
            self._health_list.append(Gtk.Label(label="No honeypots configured — add one in Settings"))

        return False  # GLib.idle_add once

    def _make_stat_card(self, title: str, value: str, subtitle: str) -> Gtk.Box:
        card = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=4)
        card.add_css_class("stat-card")
        t = Gtk.Label(label=title)
        t.add_css_class("caption-heading")
        t.set_opacity(0.7)
        v = Gtk.Label(label=value)
        v.add_css_class("title-1")
        v.add_css_class("amber-accent")
        s = Gtk.Label(label=subtitle)
        s.add_css_class("caption")
        s.set_opacity(0.5)
        card._value_label = v
        card._color_class = None
        for w in [t, v, s]:
            card.append(w)
        return card

    def _update_card(self, card: Gtk.Box, value: str, color_class: str | None = None) -> None:
        card._value_label.set_text(value)
        if card._color_class:
            card._value_label.remove_css_class(card._color_class)
        if color_class:
            card._value_label.add_css_class(f"severity-{color_class}")
            card._color_class = f"severity-{color_class}"
        else:
            card._value_label.add_css_class("amber-accent")
            card._color_class = "amber-accent"

    def _make_section(self, title: str) -> Gtk.Box:
        box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=8)
        box.add_css_class("stat-card")
        lbl = Gtk.Label(label=title)
        lbl.add_css_class("heading")
        lbl.set_xalign(0)
        box.append(lbl)
        sep = Gtk.Separator()
        box.append(sep)
        return box

    @staticmethod
    def _clear(box: Gtk.Box) -> None:
        child = box.get_first_child()
        while child:
            nxt = child.get_next_sibling()
            box.remove(child)
            child = nxt

    def _start_auto_refresh(self) -> None:
        from meli.config import get_config
        seconds = get_config().get("general", "auto_refresh_seconds", default=30)
        self._refresh_id = GLib.timeout_add_seconds(seconds, self._auto_refresh)

    def _auto_refresh(self) -> bool:
        self.refresh()
        return True  # repeat

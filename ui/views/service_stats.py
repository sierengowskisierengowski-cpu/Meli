"""Service Stats view — per-honeypot breakdown."""
from __future__ import annotations

import gi
gi.require_version("Gtk", "4.0")
gi.require_version("Adw", "1")
from gi.repository import Gtk, Adw, GLib

import threading
import structlog
from datetime import datetime, timedelta, timezone

log = structlog.get_logger()


class ServiceStatsView(Gtk.Box):
    def __init__(self) -> None:
        super().__init__(orientation=Gtk.Orientation.VERTICAL)
        self._build_ui()
        self.refresh()

    def _build_ui(self) -> None:
        header = Adw.HeaderBar()
        header.set_title_widget(Gtk.Label(label="Service Stats"))
        refresh_btn = Gtk.Button.new_from_icon_name("view-refresh-symbolic")
        refresh_btn.connect("clicked", lambda _: self.refresh())
        header.pack_end(refresh_btn)
        self.append(header)

        scroll = Gtk.ScrolledWindow()
        scroll.set_vexpand(True)
        self._content = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=16)
        self._content.set_margin_all(16)
        scroll.set_child(self._content)
        self.append(scroll)

    def refresh(self) -> None:
        threading.Thread(target=self._load, daemon=True).start()

    def _load(self) -> None:
        try:
            from meli.database import get_db
            from meli.database.models import Event, Honeypot
            from sqlalchemy import func, select, and_
            now = datetime.now(timezone.utc)
            ago_24h = now - timedelta(hours=24)

            with get_db() as db:
                honeypots = db.execute(select(Honeypot)).scalars().all()
                hp_data = []
                for hp in honeypots:
                    total = db.execute(
                        select(func.count(Event.id)).where(Event.honeypot_service == hp.honeypot_type)
                    ).scalar() or 0
                    last_24h = db.execute(
                        select(func.count(Event.id)).where(
                            and_(Event.honeypot_service == hp.honeypot_type, Event.timestamp >= ago_24h)
                        )
                    ).scalar() or 0
                    sev_rows = db.execute(
                        select(Event.severity, func.count(Event.id))
                        .where(Event.honeypot_service == hp.honeypot_type)
                        .group_by(Event.severity)
                    ).all()
                    sev_data = {r[0]: r[1] for r in sev_rows}
                    hp_data.append((hp.name, hp.honeypot_type, hp.enabled, hp.last_event_at,
                                    total, last_24h, sev_data))
            GLib.idle_add(self._populate, hp_data)
        except Exception as e:
            log.error("Service stats load failed", error=str(e))

    def _populate(self, data: list) -> bool:
        child = self._content.get_first_child()
        while child:
            nxt = child.get_next_sibling()
            self._content.remove(child)
            child = nxt

        if not data:
            lbl = Gtk.Label(label="No honeypots configured.\nAdd honeypots in Settings → Honeypot Sources.")
            lbl.set_justify(Gtk.Justification.CENTER)
            lbl.set_opacity(0.6)
            lbl.set_vexpand(True)
            lbl.set_valign(Gtk.Align.CENTER)
            self._content.append(lbl)
            return False

        for name, hp_type, enabled, last_event, total, last_24h, sev_data in data:
            grp = Adw.PreferencesGroup(title=f"{name} ({hp_type})")

            grp.add(Adw.ActionRow(title="Status",
                                   subtitle="Enabled" if enabled else "Disabled"))
            grp.add(Adw.ActionRow(title="Total Events", subtitle=f"{total:,}"))
            grp.add(Adw.ActionRow(title="Last 24h", subtitle=f"{last_24h:,}"))
            if last_event:
                grp.add(Adw.ActionRow(title="Last Event", subtitle=str(last_event)[:19]))

            for sev in ["CRITICAL", "HIGH", "MEDIUM", "LOW", "INFO"]:
                cnt = sev_data.get(sev, 0)
                if cnt > 0:
                    grp.add(Adw.ActionRow(title=sev, subtitle=f"{cnt:,}"))

            self._content.append(grp)
        return False

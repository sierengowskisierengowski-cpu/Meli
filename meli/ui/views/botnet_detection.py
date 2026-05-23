"""Botnet Detection view — coordinated attack cluster analysis."""
from __future__ import annotations

import gi
gi.require_version("Gtk", "4.0")
gi.require_version("Adw", "1")
from gi.repository import Gtk, Adw, GLib

import json
import threading
import structlog

from meli.ui.widgets import HiveHeader, HivePrefsGroup
from datetime import datetime, timedelta, timezone
from collections import defaultdict

log = structlog.get_logger()


def detect_clusters(events: list[dict]) -> list[dict]:
    """Simple cluster detection: IPs sharing credential sets in short time windows."""
    cred_groups: dict[str, list[str]] = defaultdict(list)
    cmd_groups: dict[str, list[str]] = defaultdict(list)
    hash_groups: dict[str, list[str]] = defaultdict(list)

    for ev in events:
        ip = ev.get("source_ip", "")
        if not ip:
            continue
        cred = f"{ev.get('username','')}{ev.get('password','')}"
        if cred and cred != "None None":
            cred_groups[cred].append(ip)
        cmd = ev.get("command", "")
        if cmd:
            cmd_groups[cmd[:100]].append(ip)
        h = ev.get("payload_hash", "")
        if h:
            hash_groups[h].append(ip)

    clusters = []
    for key, ips in {**cred_groups, **cmd_groups, **hash_groups}.items():
        unique_ips = list(set(ips))
        if len(unique_ips) >= 3:
            clusters.append({
                "indicator": key[:80],
                "ips": unique_ips[:20],
                "ip_count": len(unique_ips),
                "event_count": len(ips),
            })

    return sorted(clusters, key=lambda c: c["ip_count"], reverse=True)[:50]


class BotnetView(Gtk.Box):
    def __init__(self) -> None:
        super().__init__(orientation=Gtk.Orientation.VERTICAL)
        self._build_ui()
        self.refresh()

    def _build_ui(self) -> None:
        header = HiveHeader(title="Botnet Detection",

                           status_label="LIVE",

                           status_kind="live")
        refresh_btn = Gtk.Button.new_from_icon_name("view-refresh-symbolic")
        refresh_btn.connect("clicked", lambda _: self.refresh())
        header.pack_end(refresh_btn)
        self.append(header)

        desc = Gtk.Label(label=(
            "Coordinated attack clusters — groups of IPs sharing the same credentials, "
            "commands, or payload hashes in recent activity."
        ))
        desc.set_wrap(True)
        desc.set_margin_all(12)
        desc.set_opacity(0.7)
        self.append(desc)

        scroll = Gtk.ScrolledWindow()
        scroll.set_vexpand(True)
        self._content = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=12)
        self._content.set_margin_all(16)
        scroll.set_child(self._content)
        self.append(scroll)

    def refresh(self) -> None:
        threading.Thread(target=self._load, daemon=True).start()

    def _load(self) -> None:
        try:
            from meli.database import get_db
            from meli.database.models import Event
            from sqlalchemy import select
            ago_24h = datetime.now(timezone.utc) - timedelta(hours=24)
            with get_db() as db:
                rows = db.execute(
                    select(Event.source_ip, Event.username, Event.password,
                           Event.command, Event.payload_hash)
                    .where(Event.timestamp >= ago_24h)
                ).all()
            events = [{"source_ip": r[0], "username": r[1], "password": r[2],
                       "command": r[3], "payload_hash": r[4]} for r in rows]
            clusters = detect_clusters(events)
            GLib.idle_add(self._populate, clusters)
        except Exception as e:
            log.error("Botnet detection failed", error=str(e))

    def _populate(self, clusters: list) -> bool:
        child = self._content.get_first_child()
        while child:
            nxt = child.get_next_sibling()
            self._content.remove(child)
            child = nxt

        if not clusters:
            lbl = Gtk.Label(label="No coordinated attack clusters detected in the last 24h.\n\n"
                                   "Clusters appear when 3+ IPs share the same credential, command, or payload hash.")
            lbl.set_justify(Gtk.Justification.CENTER)
            lbl.set_opacity(0.6)
            lbl.set_vexpand(True)
            lbl.set_valign(Gtk.Align.CENTER)
            self._content.append(lbl)
            return False

        for cluster in clusters:
            grp = HivePrefsGroup(
                title=f"Cluster: {cluster['indicator']}",
                description=f"{cluster['ip_count']} IPs — {cluster['event_count']} events"
            )
            grp.add(Adw.ActionRow(
                title="Member IPs (first 10)",
                subtitle=", ".join(cluster["ips"][:10])
            ))
            self._content.append(grp)
        return False

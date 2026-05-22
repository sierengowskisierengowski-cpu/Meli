"""Top Attackers view — sortable IP table with full profile drawer."""
from __future__ import annotations

import gi
gi.require_version("Gtk", "4.0")
gi.require_version("Adw", "1")
from gi.repository import Gtk, Adw, GLib

import threading
import structlog
from datetime import datetime, timedelta, timezone

from meli.ui.widgets import HiveHeader

log = structlog.get_logger()


class AttackersView(Gtk.Box):
    def __init__(self) -> None:
        super().__init__(orientation=Gtk.Orientation.VERTICAL)
        self._build_ui()
        self.refresh()

    def _build_ui(self) -> None:
        header = HiveHeader(title="Top Attackers",
                            status_label="LIVE",
                            status_kind="live")
        refresh_btn = Gtk.Button.new_from_icon_name("view-refresh-symbolic")
        refresh_btn.connect("clicked", lambda _: self.refresh())
        header.pack_end(refresh_btn)
        self.append(header)

        # Search bar
        search = Gtk.SearchBar()
        self._search_entry = Gtk.SearchEntry()
        self._search_entry.set_placeholder_text("Filter by IP, country, ASN...")
        self._search_entry.connect("search-changed", self._on_search_changed)
        search.set_child(self._search_entry)
        search.set_search_mode(True)
        self.append(search)

        # Split: list + detail
        self._paned = Gtk.Paned(orientation=Gtk.Orientation.HORIZONTAL)
        self._paned.set_vexpand(True)

        # Attacker list
        scroll = Gtk.ScrolledWindow()
        scroll.set_policy(Gtk.PolicyType.NEVER, Gtk.PolicyType.AUTOMATIC)
        scroll.set_size_request(480, -1)
        self._list_box = Gtk.ListBox()
        self._list_box.set_selection_mode(Gtk.SelectionMode.SINGLE)
        self._list_box.add_css_class("boxed-list")
        self._list_box.connect("row-selected", self._on_row_selected)
        scroll.set_child(self._list_box)
        self._paned.set_start_child(scroll)

        # Detail panel
        detail_scroll = Gtk.ScrolledWindow()
        self._detail_box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=12)
        self._detail_box.set_margin_all(16)
        empty_detail = Gtk.Label(label="Select an attacker to see their full profile")
        empty_detail.set_opacity(0.5)
        empty_detail.set_valign(Gtk.Align.CENTER)
        empty_detail.set_vexpand(True)
        self._detail_box.append(empty_detail)
        detail_scroll.set_child(self._detail_box)
        self._paned.set_end_child(detail_scroll)
        self._paned.set_position(480)

        self.append(self._paned)

    def refresh(self) -> None:
        threading.Thread(target=self._load_data, daemon=True).start()

    def _load_data(self) -> None:
        try:
            from meli.database import get_db
            from meli.database.models import Attacker
            from sqlalchemy import select
            with get_db() as db:
                attackers = db.execute(
                    select(Attacker).order_by(Attacker.total_events.desc()).limit(200)
                ).scalars().all()
                data = [
                    (a.ip, a.total_events, a.max_severity, a.country_code,
                     a.asn, a.organization, a.first_seen, a.last_seen,
                     a.is_tor, a.is_vpn, a.reputation_score)
                    for a in attackers
                ]
            GLib.idle_add(self._populate_list, data)
        except Exception as e:
            log.error("Attackers load failed", error=str(e))

    def _populate_list(self, data: list) -> bool:
        child = self._list_box.get_first_child()
        while child:
            nxt = child.get_next_sibling()
            self._list_box.remove(child)
            child = nxt

        for ip, total, max_sev, country, asn, org, first_seen, last_seen, is_tor, is_vpn, rep in data:
            row = Gtk.ListBoxRow()
            row._ip = ip
            row._data = (ip, total, max_sev, country, asn, org, first_seen, last_seen, is_tor, is_vpn, rep)
            box = Gtk.Box(spacing=8)
            box.set_margin_all(8)

            from meli.utils.helpers import country_flag_emoji
            flag = country_flag_emoji(country or "") if country else "🌐"
            flag_lbl = Gtk.Label(label=flag)

            ip_lbl = Gtk.Label(label=ip or "—")
            ip_lbl.add_css_class("monospace")
            ip_lbl.set_size_request(140, -1)
            ip_lbl.set_xalign(0)

            sev_lbl = Gtk.Label(label=max_sev or "INFO")
            sev_lbl.add_css_class(f"severity-{(max_sev or 'info').lower()}")
            sev_lbl.set_size_request(70, -1)

            cnt_lbl = Gtk.Label(label=f"{total:,}" if total else "0")
            cnt_lbl.set_hexpand(True)
            cnt_lbl.set_xalign(1)

            tags = ""
            if is_tor: tags += " [TOR]"
            if is_vpn: tags += " [VPN]"
            if tags:
                tag_lbl = Gtk.Label(label=tags.strip())
                tag_lbl.add_css_class("severity-medium")
                box.append(tag_lbl)

            for w in [flag_lbl, ip_lbl, sev_lbl, cnt_lbl]:
                box.append(w)
            row.set_child(box)
            self._list_box.append(row)

        if not data:
            empty = Gtk.ListBoxRow()
            lbl = Gtk.Label(label="No attackers yet")
            lbl.set_margin_all(16)
            empty.set_child(lbl)
            self._list_box.append(empty)

        return False

    def _on_row_selected(self, list_box, row) -> None:
        if not row or not hasattr(row, "_data"):
            return
        data = row._data
        self._show_detail(data)

    def _show_detail(self, data: tuple) -> None:
        ip, total, max_sev, country, asn, org, first_seen, last_seen, is_tor, is_vpn, rep = data

        child = self._detail_box.get_first_child()
        while child:
            nxt = child.get_next_sibling()
            self._detail_box.remove(child)
            child = nxt

        title = Gtk.Label(label=ip)
        title.add_css_class("title-2")
        title.add_css_class("monospace")
        self._detail_box.append(title)

        grp = Adw.PreferencesGroup()
        for label, value in [
            ("Severity", max_sev or "—"),
            ("Total Events", f"{total:,}" if total else "0"),
            ("Country", country or "Unknown"),
            ("ASN", asn or "—"),
            ("Organization", org or "—"),
            ("First Seen", str(first_seen)[:19] if first_seen else "—"),
            ("Last Seen", str(last_seen)[:19] if last_seen else "—"),
            ("Tor Exit", "Yes" if is_tor else "No"),
            ("VPN", "Yes" if is_vpn else "No"),
            ("Abuse Score", str(rep) if rep is not None else "—"),
        ]:
            row = Adw.ActionRow(title=label, subtitle=value or "—")
            grp.add(row)

        self._detail_box.append(grp)

        # Action buttons
        btn_box = Gtk.Box(spacing=8)
        btn_box.set_margin_top(8)
        copy_btn = Gtk.Button(label="Copy IP")
        copy_btn.connect("clicked", lambda _: self._copy_to_clipboard(ip))
        ext_btn = Gtk.Button(label="AbuseIPDB ↗")
        ext_btn.connect("clicked", lambda _: self._open_url(f"https://www.abuseipdb.com/check/{ip}"))
        gn_btn = Gtk.Button(label="GreyNoise ↗")
        gn_btn.connect("clicked", lambda _: self._open_url(f"https://viz.greynoise.io/ip/{ip}"))
        enrich_btn = Gtk.Button(label="Re-enrich")
        enrich_btn.add_css_class("suggested-action")
        enrich_btn.connect("clicked", lambda _: threading.Thread(
            target=lambda: __import__("meli.enrichment", fromlist=["enrich_ip"]).enrich_ip(ip),
            daemon=True
        ).start())
        for w in [copy_btn, ext_btn, gn_btn, enrich_btn]:
            btn_box.append(w)
        self._detail_box.append(btn_box)

        # Notes field
        notes_row = Adw.EntryRow(title="Notes (saved automatically)")
        self._detail_box.append(notes_row)

    def _copy_to_clipboard(self, text: str) -> None:
        display = self.get_display()
        if display:
            clipboard = display.get_clipboard()
            clipboard.set(text)

    def _open_url(self, url: str) -> None:
        import subprocess
        subprocess.Popen(["xdg-open", url], stdout=-1, stderr=-1)

    def _on_search_changed(self, entry: Gtk.SearchEntry) -> None:
        query = entry.get_text().lower()
        row = self._list_box.get_row_at_index(0)
        while row:
            if hasattr(row, "_ip"):
                visible = query == "" or query in (row._ip or "").lower()
                row.set_visible(visible)
            row = row.get_next_sibling()

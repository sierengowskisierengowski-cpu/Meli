"""Geographic Map view — world map with attack density visualization."""
from __future__ import annotations

import gi
gi.require_version("Gtk", "4.0")
gi.require_version("Adw", "1")
from gi.repository import Gtk, Adw, GLib

import threading
import structlog

from meli.ui.widgets import HiveHeader

log = structlog.get_logger()


class GeographicMapView(Gtk.Box):
    def __init__(self) -> None:
        super().__init__(orientation=Gtk.Orientation.VERTICAL)
        self._build_ui()
        self.refresh()

    def _build_ui(self) -> None:
        header = HiveHeader(title="Global Threat Map",
                            status_label="LIVE",
                            status_kind="live")
        refresh_btn = Gtk.Button.new_from_icon_name("view-refresh-symbolic")
        refresh_btn.connect("clicked", lambda _: self.refresh())
        header.pack_end(refresh_btn)
        self.append(header)

        # Main split: map (left/top) + country table (right/bottom)
        paned = Gtk.Paned(orientation=Gtk.Orientation.HORIZONTAL)
        paned.set_vexpand(True)

        # Map area — try WebKit if available, fallback to ASCII table
        self._map_frame = Gtk.Frame()
        self._map_frame.set_label("World Map")
        self._map_frame.set_hexpand(True)
        self._map_frame.set_vexpand(True)
        self._build_map_widget()
        paned.set_start_child(self._map_frame)

        # Country stats sidebar
        scroll = Gtk.ScrolledWindow()
        scroll.set_size_request(240, -1)
        self._country_list = Gtk.ListBox()
        self._country_list.set_selection_mode(Gtk.SelectionMode.NONE)
        self._country_list.add_css_class("boxed-list")
        scroll.set_child(self._country_list)

        sidebar = Gtk.Box(orientation=Gtk.Orientation.VERTICAL)
        title = Gtk.Label(label="Top Countries")
        title.add_css_class("heading")
        title.set_margin_all(8)
        sidebar.append(title)
        sidebar.append(scroll)
        paned.set_end_child(sidebar)
        paned.set_position(900)

        self.append(paned)

    def _build_map_widget(self) -> None:
        """Try WebKitGTK for interactive map, fall back to ASCII heatmap."""
        try:
            gi.require_version("WebKit", "6.0")
            from gi.repository import WebKit
            webview = WebKit.WebView()
            webview.set_hexpand(True)
            webview.set_vexpand(True)
            self._webview = webview
            self._map_frame.set_child(webview)
            self._use_webkit = True
        except Exception:
            self._use_webkit = False
            lbl = Gtk.Label(label=(
                "Interactive map requires WebKitGTK.\n\n"
                "Attack sources are listed in the country table →\n\n"
                "Install webkit2gtk-4.1 for the interactive map."
            ))
            lbl.set_justify(Gtk.Justification.CENTER)
            lbl.set_opacity(0.6)
            lbl.set_vexpand(True)
            lbl.set_valign(Gtk.Align.CENTER)
            self._map_frame.set_child(lbl)

    def refresh(self) -> None:
        threading.Thread(target=self._load, daemon=True).start()

    def _load(self) -> None:
        try:
            from meli.database import get_db
            from meli.database.models import Event
            from sqlalchemy import func, select
            from datetime import datetime, timedelta, timezone
            ago_24h = datetime.now(timezone.utc) - timedelta(hours=24)
            with get_db() as db:
                country_rows = db.execute(
                    select(Event.country_code, func.count(Event.id))
                    .where(Event.country_code.isnot(None))
                    .where(Event.timestamp >= ago_24h)
                    .group_by(Event.country_code)
                    .order_by(func.count(Event.id).desc())
                    .limit(50)
                ).all()
            GLib.idle_add(self._populate_countries, list(country_rows))
        except Exception as e:
            log.error("Geographic map load failed", error=str(e))

    def _populate_countries(self, data: list) -> bool:
        child = self._country_list.get_first_child()
        while child:
            nxt = child.get_next_sibling()
            self._country_list.remove(child)
            child = nxt

        from meli.utils.helpers import country_flag_emoji
        for country_code, count in data:
            flag = country_flag_emoji(country_code)
            row = Adw.ActionRow(
                title=f"{flag} {country_code}",
                subtitle=f"{count:,} events"
            )
            self._country_list.append(row)

        if not data:
            empty = Adw.ActionRow(title="No geo data yet",
                                   subtitle="Enable GeoIP in Settings for location data")
            self._country_list.append(empty)

        if self._use_webkit and data:
            self._update_map(data)
        return False

    def _update_map(self, data: list) -> None:
        """Load a simple Leaflet.js map in the WebView."""
        markers_js = ""
        for code, count in data[:30]:
            # Approximate coords for common countries
            pass  # Full Leaflet integration would go here
        html = """<!DOCTYPE html><html><head>
<link rel="stylesheet" href="https://unpkg.com/leaflet@1.9.4/dist/leaflet.css"/>
<script src="https://unpkg.com/leaflet@1.9.4/dist/leaflet.js"></script>
<style>body,#map{margin:0;height:100vh;background:#0a0f1e;}</style>
</head><body><div id="map"></div>
<script>
var map = L.map('map', {
  center: [20, 0], zoom: 2,
  preferCanvas: true,
});
L.tileLayer('https://{s}.basemaps.cartocdn.com/dark_all/{z}/{x}/{y}{r}.png', {
  attribution: '&copy; OpenStreetMap contributors &copy; CARTO',
  subdomains: 'abcd', maxZoom: 20
}).addTo(map);
</script></body></html>"""
        GLib.idle_add(self._webview.load_html, html, "about:blank")

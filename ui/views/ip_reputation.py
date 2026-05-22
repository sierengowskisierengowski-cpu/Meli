"""IP Reputation view — single IP lookup with all enrichment services."""
from __future__ import annotations

import gi
gi.require_version("Gtk", "4.0")
gi.require_version("Adw", "1")
from gi.repository import Gtk, Adw, GLib

import json
import threading
import structlog

log = structlog.get_logger()


class IpReputationView(Gtk.Box):
    def __init__(self) -> None:
        super().__init__(orientation=Gtk.Orientation.VERTICAL)
        self._build_ui()

    def _build_ui(self) -> None:
        header = Adw.HeaderBar()
        header.set_title_widget(Gtk.Label(label="IP Reputation Lookup"))
        self.append(header)

        search_box = Gtk.Box(spacing=8)
        search_box.set_margin_all(16)
        self._ip_entry = Gtk.Entry()
        self._ip_entry.set_placeholder_text("Enter IP address (e.g. 1.2.3.4)")
        self._ip_entry.set_hexpand(True)
        self._ip_entry.connect("activate", self._on_lookup)
        lookup_btn = Gtk.Button(label="Lookup")
        lookup_btn.add_css_class("suggested-action")
        lookup_btn.connect("clicked", self._on_lookup)
        search_box.append(self._ip_entry)
        search_box.append(lookup_btn)
        self.append(search_box)

        scroll = Gtk.ScrolledWindow()
        scroll.set_vexpand(True)
        self._results = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=12)
        self._results.set_margin_all(16)
        self._placeholder = Gtk.Label(label=(
            "Enter an IP address above to look it up across all configured enrichment services.\n\n"
            "Configured services: AbuseIPDB, GreyNoise, VirusTotal, Shodan, IPInfo\n"
            "Offline: MaxMind GeoLite2 (always available)"
        ))
        self._placeholder.set_justify(Gtk.Justification.CENTER)
        self._placeholder.set_opacity(0.5)
        self._placeholder.set_valign(Gtk.Align.CENTER)
        self._placeholder.set_vexpand(True)
        self._results.append(self._placeholder)
        scroll.set_child(self._results)
        self.append(scroll)

    def _on_lookup(self, _) -> None:
        ip = self._ip_entry.get_text().strip()
        from meli.utils.helpers import is_valid_ip
        if not is_valid_ip(ip):
            self._show_error(f"'{ip}' is not a valid IP address")
            return

        child = self._results.get_first_child()
        while child:
            nxt = child.get_next_sibling()
            self._results.remove(child)
            child = nxt

        spinner = Gtk.Spinner()
        spinner.start()
        spinner.set_vexpand(True)
        spinner.set_valign(Gtk.Align.CENTER)
        self._results.append(spinner)

        def _run():
            from meli.enrichment import enrich_ip
            result = enrich_ip(ip)
            GLib.idle_add(self._display_result, ip, result)

        threading.Thread(target=_run, daemon=True).start()

    def _display_result(self, ip: str, result: dict) -> bool:
        child = self._results.get_first_child()
        while child:
            nxt = child.get_next_sibling()
            self._results.remove(child)
            child = nxt

        title = Gtk.Label(label=f"Results for {ip}")
        title.add_css_class("title-2")
        title.add_css_class("monospace")
        self._results.append(title)

        geo = result.get("geo") or {}
        geo_grp = Adw.PreferencesGroup(title="Geolocation (Offline GeoIP)")
        for k, v in [("Country", geo.get("country_name")), ("City", geo.get("city")),
                     ("ASN", geo.get("asn")), ("Organization", geo.get("organization")),
                     ("Coordinates", f"{geo.get('latitude', '?')}, {geo.get('longitude', '?')}")]:
            geo_grp.add(Adw.ActionRow(title=k, subtitle=str(v or "—")))
        self._results.append(geo_grp)

        abuse = result.get("abuseipdb")
        if abuse:
            grp = Adw.PreferencesGroup(title="AbuseIPDB")
            grp.add(Adw.ActionRow(title="Abuse Score", subtitle=f"{abuse.get('abuse_score', '—')}%"))
            grp.add(Adw.ActionRow(title="Total Reports", subtitle=str(abuse.get("total_reports", "—"))))
            grp.add(Adw.ActionRow(title="Last Reported", subtitle=str(abuse.get("last_reported", "—"))[:19]))
            grp.add(Adw.ActionRow(title="ISP", subtitle=str(abuse.get("isp", "—"))))
            grp.add(Adw.ActionRow(title="Tor Exit", subtitle="Yes" if abuse.get("is_tor") else "No"))
            self._results.append(grp)

        gn = result.get("greynoise")
        if gn:
            grp = Adw.PreferencesGroup(title="GreyNoise")
            grp.add(Adw.ActionRow(title="Classification", subtitle=str(gn.get("classification", "—"))))
            grp.add(Adw.ActionRow(title="Noise", subtitle="Yes" if gn.get("noise") else "No"))
            grp.add(Adw.ActionRow(title="RIOT", subtitle="Yes" if gn.get("riot") else "No"))
            self._results.append(grp)

        vt = result.get("virustotal")
        if vt:
            grp = Adw.PreferencesGroup(title="VirusTotal")
            grp.add(Adw.ActionRow(title="Malicious Votes", subtitle=str(vt.get("malicious", "—"))))
            grp.add(Adw.ActionRow(title="Suspicious", subtitle=str(vt.get("suspicious", "—"))))
            self._results.append(grp)

        sh = result.get("shodan")
        if sh:
            grp = Adw.PreferencesGroup(title="Shodan")
            grp.add(Adw.ActionRow(title="Open Ports", subtitle=", ".join(str(p) for p in (sh.get("ports") or [])) or "—"))
            grp.add(Adw.ActionRow(title="Vulnerabilities", subtitle=", ".join(sh.get("vulns") or []) or "None found"))
            self._results.append(grp)

        btn_box = Gtk.Box(spacing=8)
        btn_box.set_margin_top(8)
        for label, url in [
            ("AbuseIPDB ↗", f"https://www.abuseipdb.com/check/{ip}"),
            ("GreyNoise ↗", f"https://viz.greynoise.io/ip/{ip}"),
            ("VirusTotal ↗", f"https://www.virustotal.com/gui/ip-address/{ip}"),
            ("Shodan ↗", f"https://www.shodan.io/host/{ip}"),
        ]:
            btn = Gtk.Button(label=label)
            btn.connect("clicked", lambda _, u=url: __import__("subprocess").Popen(["xdg-open", u]))
            btn_box.append(btn)
        self._results.append(btn_box)
        return False

    def _show_error(self, msg: str) -> None:
        child = self._results.get_first_child()
        while child:
            nxt = child.get_next_sibling()
            self._results.remove(child)
            child = nxt
        lbl = Gtk.Label(label=msg)
        lbl.add_css_class("error")
        self._results.append(lbl)

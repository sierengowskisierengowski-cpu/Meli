"""Payloads / Malware view — captured files with VT lookup."""
from __future__ import annotations

import gi
gi.require_version("Gtk", "4.0")
gi.require_version("Adw", "1")
from gi.repository import Gtk, Adw, GLib

import threading
import structlog

from meli.ui.widgets import HiveHeader

log = structlog.get_logger()


class PayloadsView(Gtk.Box):
    def __init__(self) -> None:
        super().__init__(orientation=Gtk.Orientation.VERTICAL)
        self._build_ui()
        self.refresh()

    def _build_ui(self) -> None:
        header = HiveHeader(title="Payloads / Malware",

                           status_label="LIVE",

                           status_kind="live")
        refresh_btn = Gtk.Button.new_from_icon_name("view-refresh-symbolic")
        refresh_btn.connect("clicked", lambda _: self.refresh())
        header.pack_end(refresh_btn)
        self.append(header)

        self._paned = Gtk.Paned(orientation=Gtk.Orientation.HORIZONTAL)
        self._paned.set_vexpand(True)

        scroll = Gtk.ScrolledWindow()
        self._list_box = Gtk.ListBox()
        self._list_box.set_selection_mode(Gtk.SelectionMode.SINGLE)
        self._list_box.add_css_class("boxed-list")
        self._list_box.connect("row-selected", self._on_selected)
        scroll.set_child(self._list_box)
        self._paned.set_start_child(scroll)

        self._detail = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=12)
        self._detail.set_margin_all(16)
        empty = Gtk.Label(label="Select a payload to see details")
        empty.set_opacity(0.5)
        empty.set_valign(Gtk.Align.CENTER)
        empty.set_vexpand(True)
        self._detail.append(empty)
        detail_scroll = Gtk.ScrolledWindow()
        detail_scroll.set_child(self._detail)
        self._paned.set_end_child(detail_scroll)
        self._paned.set_position(500)
        self.append(self._paned)

    def refresh(self) -> None:
        threading.Thread(target=self._load, daemon=True).start()

    def _load(self) -> None:
        try:
            from meli.database import get_db
            from meli.database.models import Payload
            from sqlalchemy import select
            with get_db() as db:
                payloads = db.execute(
                    select(Payload).order_by(Payload.captured_at.desc()).limit(200)
                ).scalars().all()
                data = [(p.id, p.sha256, p.file_type, p.file_size, p.source_ip,
                         p.virustotal_status, p.virustotal_score,
                         str(p.captured_at)[:19]) for p in payloads]
            GLib.idle_add(self._populate, data)
        except Exception as e:
            log.error("Payloads load failed", error=str(e))

    def _populate(self, data: list) -> bool:
        child = self._list_box.get_first_child()
        while child:
            nxt = child.get_next_sibling()
            self._list_box.remove(child)
            child = nxt

        for pid, sha256, ftype, size, src_ip, vt_status, vt_score, captured in data:
            row = Gtk.ListBoxRow()
            row._payload_id = pid
            row._sha256 = sha256
            box = Gtk.Box(spacing=8)
            box.set_margin_all(8)
            hash_lbl = Gtk.Label(label=(sha256 or "—")[:16] + "…")
            hash_lbl.add_css_class("monospace")
            hash_lbl.set_size_request(140, -1)
            type_lbl = Gtk.Label(label=ftype or "unknown")
            type_lbl.set_size_request(100, -1)
            from meli.utils.helpers import format_bytes
            size_lbl = Gtk.Label(label=format_bytes(size) if size else "—")
            size_lbl.set_size_request(70, -1)
            vt_lbl = Gtk.Label(label=f"VT: {vt_score or vt_status or 'unchecked'}")
            if vt_status == "malicious":
                vt_lbl.add_css_class("severity-critical")
            vt_lbl.set_hexpand(True)
            for w in [hash_lbl, type_lbl, size_lbl, vt_lbl]:
                box.append(w)
            row.set_child(box)
            self._list_box.append(row)

        if not data:
            empty = Gtk.ListBoxRow()
            lbl = Gtk.Label(label="No payloads captured yet")
            lbl.set_margin_all(16)
            empty.set_child(lbl)
            self._list_box.append(empty)
        return False

    def _on_selected(self, lb, row) -> None:
        if not row or not hasattr(row, "_sha256"):
            return
        sha256 = row._sha256

        child = self._detail.get_first_child()
        while child:
            nxt = child.get_next_sibling()
            self._detail.remove(child)
            child = nxt

        grp = Adw.PreferencesGroup(title=f"SHA256: {sha256 or '—'}")

        vt_btn = Gtk.Button(label="Check VirusTotal")
        vt_btn.add_css_class("suggested-action")
        vt_btn.connect("clicked", lambda _: self._vt_lookup(sha256))

        copy_btn = Gtk.Button(label="Copy Hash")
        copy_btn.connect("clicked", lambda _: self._copy(sha256))

        btn_box = Gtk.Box(spacing=8)
        btn_box.append(vt_btn)
        btn_box.append(copy_btn)

        self._vt_result = Gtk.Label(label="")
        self._vt_result.set_wrap(True)
        self._vt_result.add_css_class("monospace")

        self._detail.append(grp)
        self._detail.append(btn_box)
        self._detail.append(self._vt_result)

    def _vt_lookup(self, sha256: str) -> None:
        def _run():
            from meli.enrichment.virustotal import query_virustotal_hash
            result = query_virustotal_hash(sha256)
            import json
            GLib.idle_add(self._vt_result.set_text,
                          json.dumps(result, indent=2) if result else "No results (API key required)")
        threading.Thread(target=_run, daemon=True).start()

    def _copy(self, text: str) -> None:
        display = self.get_display()
        if display:
            display.get_clipboard().set(text)

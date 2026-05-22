"""Credentials view — top username/password pairs."""
from __future__ import annotations

import gi
gi.require_version("Gtk", "4.0")
gi.require_version("Adw", "1")
from gi.repository import Gtk, Adw, GLib

import threading
import structlog

log = structlog.get_logger()


class CredentialsView(Gtk.Box):
    def __init__(self) -> None:
        super().__init__(orientation=Gtk.Orientation.VERTICAL)
        self._tab = "combined"
        self._build_ui()
        self.refresh()

    def _build_ui(self) -> None:
        header = Adw.HeaderBar()
        header.set_title_widget(Gtk.Label(label="Top Credentials"))
        refresh_btn = Gtk.Button.new_from_icon_name("view-refresh-symbolic")
        refresh_btn.connect("clicked", lambda _: self.refresh())
        header.pack_end(refresh_btn)

        export_btn = Gtk.Button(label="Export Wordlist")
        export_btn.connect("clicked", self._on_export)
        header.pack_end(export_btn)
        self.append(header)

        tabs = Gtk.Box(spacing=4)
        tabs.set_margin_all(8)
        for label, key in [("Username + Password", "combined"), ("Usernames", "usernames"), ("Passwords", "passwords")]:
            btn = Gtk.ToggleButton(label=label)
            btn.set_active(key == "combined")
            btn.connect("toggled", self._on_tab, key)
            tabs.append(btn)
        self.append(tabs)

        scroll = Gtk.ScrolledWindow()
        scroll.set_vexpand(True)
        self._list_box = Gtk.ListBox()
        self._list_box.set_selection_mode(Gtk.SelectionMode.NONE)
        self._list_box.add_css_class("boxed-list")
        scroll.set_child(self._list_box)
        self.append(scroll)

    def refresh(self) -> None:
        threading.Thread(target=self._load_data, daemon=True).start()

    def _load_data(self) -> None:
        try:
            from meli.database import get_db
            from meli.database.models import Credential
            from sqlalchemy import select
            with get_db() as db:
                creds = db.execute(
                    select(Credential).order_by(Credential.attempt_count.desc()).limit(500)
                ).scalars().all()
                data = [(c.username, c.password, c.attempt_count, str(c.first_seen)[:19], str(c.last_seen)[:19])
                        for c in creds]
            GLib.idle_add(self._populate, data)
        except Exception as e:
            log.error("Credentials load failed", error=str(e))

    def _populate(self, data: list) -> bool:
        child = self._list_box.get_first_child()
        while child:
            nxt = child.get_next_sibling()
            self._list_box.remove(child)
            child = nxt

        for user, pwd, cnt, first, last in data:
            row = Adw.ActionRow(
                title=f"{user} : {pwd}",
                subtitle=f"{cnt:,} attempts — first: {first} — last: {last}",
            )
            row.add_css_class("monospace")
            self._list_box.append(row)

        if not data:
            row = Adw.ActionRow(title="No credentials captured yet",
                                subtitle="Credential data appears when attackers attempt logins on SSH/Telnet/FTP honeypots")
            self._list_box.append(row)
        return False

    def _on_tab(self, btn: Gtk.ToggleButton, tab: str) -> None:
        if btn.get_active():
            self._tab = tab

    def _on_export(self, _) -> None:
        from meli.database import get_db
        from meli.database.models import Credential
        from sqlalchemy import select
        from pathlib import Path
        from meli.config import get_config
        from datetime import datetime, timezone
        try:
            with get_db() as db:
                creds = db.execute(select(Credential).order_by(Credential.attempt_count.desc())).scalars().all()
            cfg = get_config()
            ts = datetime.now(timezone.utc).strftime("%Y%m%d_%H%M%S")
            out = Path(cfg.data_dir) / "exports" / f"credentials_{ts}.txt"
            out.parent.mkdir(parents=True, exist_ok=True)
            with open(out, "w") as f:
                for c in creds:
                    f.write(f"{c.username}:{c.password}\n")
            dialog = Adw.MessageDialog(heading="Wordlist Exported", body=f"Saved to:\n{out}")
            dialog.add_response("ok", "OK")
            top = self.get_root()
            if top: dialog.set_transient_for(top)
            dialog.present()
        except Exception as e:
            log.error("Export failed", error=str(e))

"""Command Analysis view — post-auth commands from Cowrie sessions."""
from __future__ import annotations

import gi
gi.require_version("Gtk", "4.0")
gi.require_version("Adw", "1")
from gi.repository import Gtk, Adw, GLib

import threading
import structlog

from meli.ui.widgets import HiveHeader

log = structlog.get_logger()

_INTENTS = {
    "download": ("wget", "curl", "tftp", "ftp", "scp", "rsync"),
    "persistence": ("crontab", "rc.local", "init.d", "authorized_keys", "useradd"),
    "recon": ("uname", "ifconfig", "ip addr", "ps aux", "cat /etc/passwd", "id", "whoami"),
    "escalation": ("sudo", "su -", "chmod +s", "setuid"),
    "mining": ("xmrig", "minerd", "stratum", "pool."),
    "evasion": ("history -c", "shred", "unset HISTFILE", "rm -rf /tmp"),
}


def classify_intent(cmd: str) -> str:
    cmd_lower = cmd.lower()
    for intent, patterns in _INTENTS.items():
        if any(p in cmd_lower for p in patterns):
            return intent
    return "unknown"


class CommandsView(Gtk.Box):
    def __init__(self) -> None:
        super().__init__(orientation=Gtk.Orientation.VERTICAL)
        self._build_ui()
        self.refresh()

    def _build_ui(self) -> None:
        header = HiveHeader(title="Command Analysis",

                           status_label="LIVE",

                           status_kind="live")
        refresh_btn = Gtk.Button.new_from_icon_name("view-refresh-symbolic")
        refresh_btn.connect("clicked", lambda _: self.refresh())
        header.pack_end(refresh_btn)
        self.append(header)

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
            from meli.database.models import Command
            from sqlalchemy import select
            with get_db() as db:
                cmds = db.execute(
                    select(Command).order_by(Command.execution_count.desc()).limit(200)
                ).scalars().all()
                data = [(c.command_text, c.execution_count, c.detected_intent or classify_intent(c.command_text),
                         str(c.first_seen)[:19], str(c.last_seen)[:19]) for c in cmds]
            GLib.idle_add(self._populate, data)
        except Exception as e:
            log.error("Commands load failed", error=str(e))

    def _populate(self, data: list) -> bool:
        child = self._list_box.get_first_child()
        while child:
            nxt = child.get_next_sibling()
            self._list_box.remove(child)
            child = nxt

        for cmd, cnt, intent, first, last in data:
            row = Adw.ActionRow(
                title=cmd[:120] if cmd else "—",
                subtitle=f"Intent: {intent} — {cnt:,}× — last: {last}",
            )
            row.add_css_class("monospace")
            self._list_box.append(row)

        if not data:
            row = Adw.ActionRow(
                title="No commands captured yet",
                subtitle="Commands appear when attackers successfully authenticate to Cowrie SSH/Telnet honeypot",
            )
            self._list_box.append(row)
        return False

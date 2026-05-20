"""Change master password dialog."""
from __future__ import annotations

import gi
gi.require_version("Gtk", "4.0")
gi.require_version("Adw", "1")
from gi.repository import Gtk, Adw

from meli.auth import change_master_password


class ChangePasswordDialog(Adw.Window):
    def __init__(self, **kwargs) -> None:
        super().__init__(title="Change Master Password", default_width=400,
                         default_height=300, modal=True, **kwargs)
        self._build_ui()

    def _build_ui(self) -> None:
        box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=16)
        box.set_margin_all(16)

        grp = Adw.PreferencesGroup()
        self._current = Adw.PasswordEntryRow(title="Current Password")
        self._new1 = Adw.PasswordEntryRow(title="New Password (min 12 chars)")
        self._new2 = Adw.PasswordEntryRow(title="Confirm New Password")
        for r in [self._current, self._new1, self._new2]:
            grp.add(r)

        self._error = Gtk.Label(label="")
        self._error.add_css_class("error")
        self._error.set_visible(False)

        save_btn = Gtk.Button(label="Change Password")
        save_btn.add_css_class("suggested-action")
        save_btn.connect("clicked", self._on_save)
        cancel_btn = Gtk.Button(label="Cancel")
        cancel_btn.connect("clicked", lambda _: self.close())

        btn_box = Gtk.Box(spacing=8)
        btn_box.set_halign(Gtk.Align.END)
        btn_box.append(cancel_btn)
        btn_box.append(save_btn)

        box.append(grp)
        box.append(self._error)
        box.append(btn_box)
        self.set_content(box)

    def _on_save(self, _) -> None:
        current = self._current.get_text()
        new1 = self._new1.get_text()
        new2 = self._new2.get_text()

        if len(new1) < 12:
            self._error.set_text("New password must be at least 12 characters")
            self._error.set_visible(True)
            return
        if new1 != new2:
            self._error.set_text("New passwords do not match")
            self._error.set_visible(True)
            return

        if change_master_password(current, new1):
            self.close()
        else:
            self._error.set_text("Current password is incorrect")
            self._error.set_visible(True)

"""
Meli lock screen — shown on launch and after idle timeout.
Emits 'unlocked' signal on successful authentication.
"""
from __future__ import annotations

import gi
gi.require_version("Gtk", "4.0")
gi.require_version("Adw", "1")

from gi.repository import Gtk, Adw, GLib, GObject  # noqa: E402

import structlog
from meli.auth import attempt_login, is_totp_enabled

log = structlog.get_logger()


class LockScreen(Gtk.Box):
    __gsignals__ = {
        "unlocked": (GObject.SignalFlags.RUN_FIRST, None, ()),
    }

    _CSS_INSTALLED = False

    def __init__(self) -> None:
        super().__init__(orientation=Gtk.Orientation.VERTICAL)
        # Fully opaque veil — without this the main window's content
        # (dashboard data, hit feeds, etc.) shows through the overlay
        # before the user has authenticated.
        self.add_css_class("background")
        self.add_css_class("meli-lock-veil")
        self.set_hexpand(True)
        self.set_vexpand(True)
        self.set_halign(Gtk.Align.FILL)
        self.set_valign(Gtk.Align.FILL)
        # Block all pointer/keyboard interaction with widgets behind.
        self.set_can_target(True)
        self.set_focusable(True)

        if not LockScreen._CSS_INSTALLED:
            provider = Gtk.CssProvider()
            provider.load_from_data(
                b".meli-lock-veil { background-color: #0b0b10; }"
            )
            display = self.get_display() if hasattr(self, "get_display") else None
            try:
                from gi.repository import Gdk
                Gtk.StyleContext.add_provider_for_display(
                    Gdk.Display.get_default(),
                    provider,
                    Gtk.STYLE_PROVIDER_PRIORITY_APPLICATION,
                )
                LockScreen._CSS_INSTALLED = True
            except Exception as e:
                log.debug("Could not install lock-veil CSS", error=str(e))

        self._totp_required = is_totp_enabled()
        self._shake_pending = False
        self._build_ui()

    def _build_ui(self) -> None:
        # Center everything
        center = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=24)
        center.set_halign(Gtk.Align.CENTER)
        center.set_valign(Gtk.Align.CENTER)
        center.set_hexpand(True)
        center.set_vexpand(True)
        center.set_margin_all(40)

        # Logo / branding
        logo_label = Gtk.Label(label="M")
        logo_label.add_css_class("display")
        logo_label.add_css_class("amber-accent")
        logo_label.set_opacity(0.9)

        title = Gtk.Label(label="MELI")
        title.add_css_class("title-1")

        subtitle = Gtk.Label(label="Honeypot Command Center")
        subtitle.add_css_class("body")
        subtitle.set_opacity(0.6)

        center.append(logo_label)
        center.append(title)
        center.append(subtitle)

        # Form card
        card = Adw.PreferencesGroup()
        card.set_title("Authentication Required")
        card.set_description("Enter your master password to continue")

        self._password_row = Adw.PasswordEntryRow(title="Master Password")
        self._password_row.connect("entry-activated", self._on_unlock_clicked)
        card.add(self._password_row)

        if self._totp_required:
            self._totp_row = Adw.EntryRow(title="2FA Code (TOTP)")
            self._totp_row.connect("entry-activated", self._on_unlock_clicked)
            card.add(self._totp_row)
        else:
            self._totp_row = None

        center.append(card)

        # Error label
        self._error_label = Gtk.Label(label="")
        self._error_label.add_css_class("error")
        self._error_label.set_visible(False)
        center.append(self._error_label)

        # Unlock button
        unlock_btn = Gtk.Button(label="Unlock")
        unlock_btn.add_css_class("suggested-action")
        unlock_btn.add_css_class("pill")
        unlock_btn.set_halign(Gtk.Align.CENTER)
        unlock_btn.set_size_request(200, -1)
        unlock_btn.connect("clicked", self._on_unlock_clicked)
        center.append(unlock_btn)

        self.append(center)

    def _on_unlock_clicked(self, *_) -> None:
        password = self._password_row.get_text()
        totp = self._totp_row.get_text() if self._totp_row else ""

        success, message = attempt_login(password, totp)

        if success:
            self.emit("unlocked")
        else:
            self._show_error(message)
            self._shake()
            self._password_row.set_text("")
            if self._totp_row:
                self._totp_row.set_text("")

    def _show_error(self, message: str) -> None:
        self._error_label.set_text(message)
        self._error_label.set_visible(True)

    def _shake(self) -> None:
        """Quick shake animation on wrong password."""
        if self._shake_pending:
            return
        self._shake_pending = True
        original_margin = self._password_row.get_margin_start()

        def step(n: int) -> bool:
            offsets = [10, -10, 8, -8, 5, -5, 0]
            if n < len(offsets):
                self._password_row.set_margin_start(original_margin + offsets[n])
                self._password_row.set_margin_end(original_margin - offsets[n])
                GLib.timeout_add(40, step, n + 1)
                return False
            self._shake_pending = False
            return False

        GLib.timeout_add(40, step, 0)

"""
Meli GTK4 Application entry point.
Initialises the database, starts the GTK app, and shows either
the setup wizard (first launch) or the lock screen.
"""
from __future__ import annotations

import gi
gi.require_version("Gtk", "4.0")
gi.require_version("Adw", "1")

from gi.repository import Gtk, Adw, GLib, Gio, Gdk  # noqa: E402


# GTK4 compatibility shim
def _set_margin_all(widget, margin):
    widget.set_margin_top(margin)
    widget.set_margin_bottom(margin)
    widget.set_margin_start(margin)
    widget.set_margin_end(margin)
Gtk.Widget.set_margin_all = _set_margin_all
import structlog
from meli.config import get_config
from meli.database import init_db
from meli.auth import is_setup_complete

log = structlog.get_logger()

APP_ID = "io.github.sierengowski.meli"


class MeliApplication(Adw.Application):
    def __init__(self) -> None:
        super().__init__(
            application_id=APP_ID,
            flags=Gio.ApplicationFlags.DEFAULT_FLAGS,
        )
        self.connect("activate", self._on_activate)
        self._main_window = None

    def _on_activate(self, app: Adw.Application) -> None:
        from meli.ui.main_window import MeliMainWindow

        if self._main_window is None:
            self._main_window = MeliMainWindow(application=app)
            self._main_window.present()

            if not is_setup_complete():
                log.info("First launch — showing setup wizard")
                GLib.idle_add(self._show_setup_wizard)
            else:
                log.info("Setup complete — showing lock screen")
                GLib.idle_add(self._main_window.show_lock_screen)
        else:
            self._main_window.present()

    def _show_setup_wizard(self) -> bool:
        from meli.ui.setup_wizard import SetupWizard
        wizard = SetupWizard(transient_for=self._main_window)
        wizard.connect("wizard-complete", self._on_wizard_complete)
        wizard.present()
        return False

    def _on_wizard_complete(self, wizard) -> None:
        log.info("Setup wizard complete")
        self._main_window.show_lock_screen()

    def do_startup(self) -> None:
        Adw.Application.do_startup(self)
        self._init_app()
        self._setup_actions()
        self._load_css()

    def _init_app(self) -> None:
        try:
            init_db()
            log.info("Database initialised")
        except Exception as e:
            log.error("Database init failed", error=str(e))

    def _setup_actions(self) -> None:
        # Quit action
        quit_action = Gio.SimpleAction.new("quit", None)
        quit_action.connect("activate", lambda *_: self.quit())
        self.add_action(quit_action)
        self.set_accels_for_action("app.quit", ["<Control>q"])

    def _load_css(self) -> None:
        css = Gtk.CssProvider()
        css.load_from_string("""
            .meli-sidebar {
                background-color: alpha(@card_bg_color, 0.95);
                border-right: 1px solid alpha(@borders, 0.5);
            }
            .meli-header {
                background-color: alpha(@headerbar_bg_color, 0.97);
                border-bottom: 1px solid alpha(@borders, 0.6);
            }
            .severity-info     { color: #94a3b8; }
            .severity-low      { color: #60a5fa; }
            .severity-medium   { color: #f59e0b; }
            .severity-high     { color: #f97316; }
            .severity-critical { color: #ef4444; font-weight: bold; }
            .monospace { font-family: "JetBrains Mono", "Fira Code", monospace; }
            .stat-card {
                border-radius: 12px;
                padding: 16px;
                background-color: alpha(@card_bg_color, 0.8);
                border: 1px solid alpha(@borders, 0.4);
            }
            .event-row:hover { background-color: alpha(@accent_color, 0.08); }
            .amber-accent { color: #f59e0b; }
        """)
        Gtk.StyleContext.add_provider_for_display(
            Gdk.Display.get_default(),
            css,
            Gtk.STYLE_PROVIDER_PRIORITY_APPLICATION,
        )

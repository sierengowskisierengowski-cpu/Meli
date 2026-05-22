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

import structlog
from meli.config import get_config
from meli.database import init_db
from meli.auth import is_setup_complete

log = structlog.get_logger()

APP_ID = "io.github.sierengowski.meli"


class MeliApplication(Adw.Application):
    def __init__(self, *, kiosk: bool = False) -> None:
        super().__init__(
            application_id=APP_ID,
            flags=Gio.ApplicationFlags.DEFAULT_FLAGS,
        )
        self.connect("activate", self._on_activate)
        self._main_window = None
        self._atrium_window = None
        self._kiosk_launch = bool(kiosk)
        self._kiosk_pending_after_unlock = False

    def _on_activate(self, app: Adw.Application) -> None:
        from meli.ui.main_window import MeliMainWindow
        from meli.config import get_config

        # Kiosk fast-path: launch straight into the Atrium with no
        # splash, no main window, optionally no lock screen. Designed
        # for Pi-on-a-wall installs where the box reboots into the
        # display unattended.
        if self._kiosk_launch and self._main_window is None:
            cfg = get_config()
            if cfg.get("atrium", "bypass_lock_in_kiosk_mode", default=False):
                log.info("Kiosk launch — opening Atrium directly")
                self._open_atrium(parent_app=app, fullscreen=True)
                return
            # Otherwise fall through to normal flow but auto-open
            # the atrium right after the lock screen clears. The flag
            # is consumed by on_post_unlock() below, which the main
            # window calls from its _on_unlocked handler.
            self._kiosk_pending_after_unlock = True
            log.info("Kiosk launch queued behind lock screen")

        if self._main_window is None:
            self._main_window = MeliMainWindow(application=app)

            # Put the lock screen / wizard in place BEFORE the main
            # window paints for the first time. Otherwise the dashboard,
            # live feed, geo map, etc. flash visible behind the splash
            # and continue to be visible behind the lock screen on
            # compositors where overlay transparency leaks through.
            if is_setup_complete():
                self._main_window.show_lock_screen()
            # First-launch (wizard) path: nothing sensitive to hide
            # because the DB is empty. Wizard opens after splash.

            # Now present the main window so the compositor has a
            # parent surface to anchor the modal splash to. Without
            # this the splash can appear unparented on Wayland and
            # lose focus / z-order to other windows.
            self._main_window.present()

            cfg = get_config()
            splash_enabled = cfg.get("splash", "enabled", default=True)

            if splash_enabled:
                from meli.ui.splash_screen import SplashScreen
                splash = SplashScreen(
                    application=app,
                    transient_for=self._main_window,
                )
                splash.connect("splash-finished", lambda *_: self._after_splash())
                splash.present()
            else:
                self._post_splash_flow()
        else:
            self._main_window.present()

    def _after_splash(self) -> None:
        """Called once the splash animation completes."""
        if self._main_window is None:
            return
        # Lock screen was already installed before the splash; only
        # the first-launch wizard path still has work to do here.
        if not is_setup_complete():
            self._post_splash_flow()

    def _post_splash_flow(self) -> None:
        """Show setup wizard on first launch, otherwise the lock screen."""
        if self._main_window is None:
            return
        if not is_setup_complete():
            log.info("First launch — showing setup wizard")
            GLib.idle_add(self._show_setup_wizard)
        else:
            log.info("Setup complete — showing lock screen")
            GLib.idle_add(self._main_window.show_lock_screen)

    def _show_setup_wizard(self) -> bool:
        from meli.ui.setup_wizard import SetupWizard
        wizard = SetupWizard(transient_for=self._main_window)
        wizard.connect("wizard-complete", self._on_wizard_complete)
        wizard.present()
        return False

    def _on_wizard_complete(self, wizard) -> None:
        log.info("Setup wizard complete")
        self._main_window.show_lock_screen()

    def on_post_unlock(self) -> None:
        """Hook called by MeliMainWindow after the lock screen clears.
        Honors a pending --kiosk launch by opening the Atrium kiosk
        window once the user has authenticated."""
        if not self._kiosk_pending_after_unlock:
            return
        self._kiosk_pending_after_unlock = False
        log.info("Lock cleared — opening Atrium for kiosk launch")
        # Defer one tick so the main window has finished its unlock
        # transition before we present a fullscreen child window.
        GLib.idle_add(lambda: (self._open_atrium(fullscreen=True), False)[1])

    def do_startup(self) -> None:
        Adw.Application.do_startup(self)
        self._init_app()
        self._setup_actions()
        self._load_css()
        self._start_labyrinth()

    def do_shutdown(self) -> None:
        try:
            self._stop_labyrinth()
        finally:
            Adw.Application.do_shutdown(self)

    def _init_app(self) -> None:
        try:
            init_db()
            log.info("Database initialised")
        except Exception as e:
            log.error("Database init failed", error=str(e))

    # ---- Labyrinth tarpit (opt-in) -----------------------------------

    _labyrinth = None  # type: ignore[var-annotated]

    def _start_labyrinth(self) -> None:
        """Start the Labyrinth tarpit daemon if enabled in config.

        Opt-in by design (labyrinth.enabled defaults to False) — running
        a public-facing tarpit must always be a deliberate decision.
        """
        from meli.config import get_config
        cfg = get_config()
        if not cfg.get("labyrinth", "enabled", default=False):
            return
        try:
            # Load persisted sticky-IP roster before any session can fire.
            from meli.labyrinth import sticky as _sticky
            loaded = _sticky.load()
            if loaded:
                log.info("Labyrinth sticky-IP roster loaded", count=loaded)
        except Exception as e:
            log.warning("Labyrinth sticky load failed", error=str(e))
        try:
            from meli.labyrinth import LabyrinthDaemon
            self._labyrinth = LabyrinthDaemon(
                host=cfg.get("labyrinth", "bind_host", default="0.0.0.0"),
                port=int(cfg.get("labyrinth", "bind_port", default=2323)),
                max_sessions=int(cfg.get("labyrinth", "max_sessions", default=200)),
                taunt_intensity=str(cfg.get("labyrinth", "taunt_intensity", default="full")),
                ssh_enabled=bool(cfg.get("labyrinth", "ssh_enabled", default=False)),
                ssh_port=int(cfg.get("labyrinth", "ssh_bind_port", default=2222)),
            )
            ok = self._labyrinth.start()
            if ok:
                log.info("Labyrinth tarpit started",
                         port=int(cfg.get("labyrinth", "bind_port", default=2323)))
            else:
                log.error("Labyrinth tarpit failed to bind — check port + perms",
                          port=int(cfg.get("labyrinth", "bind_port", default=2323)))
                self._labyrinth = None
        except Exception as e:
            log.error("Labyrinth start failed", error=str(e))
            self._labyrinth = None

    def _stop_labyrinth(self) -> None:
        if self._labyrinth is None:
            return
        # Flush sticky-IP roster to disk before tearing down the daemon
        # so a fresh restart doesn't lose returning-attacker history.
        try:
            from meli.labyrinth import sticky as _sticky
            _sticky.save()
        except Exception as e:
            log.warning("Labyrinth sticky save on shutdown failed", error=str(e))
        try:
            clean = self._labyrinth.stop(timeout=5.0)
            if clean:
                log.info("Labyrinth tarpit stopped")
            else:
                # Thread did not exit within the timeout — the asyncio
                # server is still unwinding. The daemon is set daemon=True
                # at the OS thread level, so Python will tear it down on
                # process exit, but the operator should know.
                log.warning("Labyrinth tarpit stop timed out — thread still alive")
        except Exception as e:
            log.warning("Labyrinth stop error", error=str(e))
        self._labyrinth = None

    def _setup_actions(self) -> None:
        # Quit action
        quit_action = Gio.SimpleAction.new("quit", None)
        quit_action.connect("activate", lambda *_: self.quit())
        self.add_action(quit_action)
        self.set_accels_for_action("app.quit", ["<Control>q"])

        # Labyrinth Atrium kiosk display (F12 from anywhere)
        atrium_action = Gio.SimpleAction.new("atrium", None)
        atrium_action.connect("activate", lambda *_: self._open_atrium())
        self.add_action(atrium_action)
        self.set_accels_for_action("app.atrium", ["F12"])

    def _open_atrium(self, *, parent_app=None, fullscreen: bool = True) -> None:
        """Open (or re-present) the Atrium kiosk window."""
        from meli.ui.atrium import AtriumWindow
        app = parent_app or self
        if self._atrium_window is not None:
            try:
                self._atrium_window.present()
                return
            except Exception:
                self._atrium_window = None
        win = AtriumWindow(application=app, fullscreen=fullscreen)
        self._atrium_window = win

        def _on_close(*_):
            self._atrium_window = None
            return False

        win.connect("close-request", _on_close)
        win.present()

    def _load_css(self) -> None:
        """Load the Honey Trap theme from resources/css/style.css.

        Falls back to a minimal inline stylesheet if the file is missing
        (e.g. running from an old install that pre-dates the resource).
        """
        from pathlib import Path

        css = Gtk.CssProvider()
        css_path = Path(__file__).parent / "resources" / "css" / "style.css"
        try:
            if css_path.is_file():
                css.load_from_path(str(css_path))
                log.info("Loaded Honey Trap theme", path=str(css_path))
            else:
                raise FileNotFoundError(css_path)
        except Exception as e:
            log.warning("Falling back to inline CSS", error=str(e))
            css.load_from_string("""
                .meli-sidebar { background-color: alpha(@card_bg_color, 0.95); }
                .meli-header  { background-color: alpha(@headerbar_bg_color, 0.97); }
                .severity-critical { color: #dc2626; font-weight: bold; }
                .severity-high     { color: #ea7f1c; }
                .severity-medium   { color: #d4a017; }
                .severity-low      { color: #fde68a; }
                .severity-info     { color: #c2b8a3; }
                .amber-accent { color: #f59e0b; }
                .honey-accent { color: #d4a017; }
                .monospace { font-family: "JetBrains Mono", monospace; }
                .stat-card { border-radius: 14px; padding: 18px; }
            """)

        display = Gdk.Display.get_default()
        if display is not None:
            Gtk.StyleContext.add_provider_for_display(
                display,
                css,
                Gtk.STYLE_PROVIDER_PRIORITY_APPLICATION,
            )
        else:
            log.warning("No default display available for CSS provider")

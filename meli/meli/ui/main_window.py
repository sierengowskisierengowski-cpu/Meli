"""
Meli main application window.
Left sidebar + content stack. Keyboard shortcuts registered here.
"""
from __future__ import annotations

import gi
gi.require_version("Gtk", "4.0")
gi.require_version("Adw", "1")

from gi.repository import Gtk, Adw, GLib, Gdk  # noqa: E402

import structlog
from meli.auth import lock_session, is_authenticated
from meli.config import get_config

log = structlog.get_logger()

# View registry: (label, icon_name, view_module, view_class)
_VIEWS = [
    ("Dashboard",    "view-grid-symbolic",          "meli.ui.views.dashboard",      "DashboardView"),
    ("Live Feed",    "media-record-symbolic",        "meli.ui.views.live_feed",      "LiveFeedView"),
    ("Map",          "find-location-symbolic",       "meli.ui.views.geographic_map", "GeographicMapView"),
    ("Attackers",    "security-high-symbolic",       "meli.ui.views.attackers",      "AttackersView"),
    ("Credentials",  "dialog-password-symbolic",     "meli.ui.views.credentials",    "CredentialsView"),
    ("Commands",     "utilities-terminal-symbolic",  "meli.ui.views.commands",       "CommandsView"),
    ("Payloads",     "emblem-danger-symbolic",        "meli.ui.views.payloads",      "PayloadsView"),
    ("Services",     "network-server-symbolic",      "meli.ui.views.service_stats",  "ServiceStatsView"),
    ("Timeline",     "office-calendar-symbolic",     "meli.ui.views.timeline",       "TimelineView"),
    ("IP Reputation","network-wired-symbolic",       "meli.ui.views.ip_reputation",  "IpReputationView"),
    ("Botnets",      "network-workgroup-symbolic",   "meli.ui.views.botnet_detection","BotnetView"),
    ("Alerts",       "notification-symbolic",        "meli.ui.views.alert_rules",    "AlertRulesView"),
    ("Reports",      "document-send-symbolic",       "meli.ui.views.reports",        "ReportsView"),
    ("Labyrinth",    "drive-multidisk-symbolic",     "meli.ui.views.labyrinth_sessions", "LabyrinthSessionsView"),
    ("Replay",       "media-playback-start-symbolic","meli.ui.views.labyrinth_replay",   "LabyrinthReplayView"),
    ("Settings",     "preferences-system-symbolic",  "meli.ui.views.settings",       "SettingsView"),
]


class MeliMainWindow(Adw.ApplicationWindow):
    def __init__(self, **kwargs) -> None:
        super().__init__(
            title="Meli — Honeypot Command Center",
            default_width=1440,
            default_height=900,
            **kwargs,
        )
        cfg = get_config()
        self.set_default_size(
            cfg.get("ui", "window_width", default=1440),
            cfg.get("ui", "window_height", default=900),
        )
        if cfg.get("ui", "window_maximized", default=False):
            self.maximize()

        self._view_instances: dict[str, Gtk.Widget] = {}
        self._lock_overlay: Gtk.Widget | None = None
        self._idle_timer: int | None = None

        self._build_ui()
        self._register_shortcuts()
        self._start_idle_timer()

    # ── UI construction ───────────────────────────────────────────────────────

    def _build_ui(self) -> None:
        # Root: overlay to allow lock screen on top
        self._overlay = Gtk.Overlay()

        # Main layout: sidebar + content
        self._split = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL)

        # Sidebar
        self._sidebar = self._build_sidebar()
        self._split.append(self._sidebar)

        # Content stack
        self._stack = Gtk.Stack()
        self._stack.set_transition_type(Gtk.StackTransitionType.CROSSFADE)
        self._stack.set_transition_duration(150)
        self._stack.set_hexpand(True)
        self._stack.set_vexpand(True)
        self._split.append(self._stack)

        self._overlay.set_child(self._split)
        self.set_content(self._overlay)

        # Load first view
        self._navigate_to(0)

    def _build_sidebar(self) -> Gtk.Widget:
        sidebar = Gtk.Box(orientation=Gtk.Orientation.VERTICAL)
        sidebar.add_css_class("meli-sidebar")
        sidebar.set_size_request(220, -1)

        # Branding
        brand_box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=2)
        brand_box.set_margin_top(20)
        brand_box.set_margin_bottom(12)
        brand_box.set_margin_start(16)
        brand_box.set_margin_end(16)

        title = Gtk.Label(label="MELI")
        title.add_css_class("title-2")
        title.add_css_class("amber-accent")
        title.set_halign(Gtk.Align.START)

        subtitle = Gtk.Label(label="Honeypot Command Center")
        subtitle.add_css_class("caption")
        subtitle.set_halign(Gtk.Align.START)
        subtitle.set_opacity(0.6)

        brand_box.append(title)
        brand_box.append(subtitle)
        sidebar.append(brand_box)

        sep = Gtk.Separator()
        sep.set_margin_bottom(8)
        sidebar.append(sep)

        # Nav buttons
        self._nav_buttons: list[Gtk.ToggleButton] = []
        scroll = Gtk.ScrolledWindow()
        scroll.set_policy(Gtk.PolicyType.NEVER, Gtk.PolicyType.AUTOMATIC)
        scroll.set_vexpand(True)

        nav_box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=2)
        nav_box.set_margin_start(8)
        nav_box.set_margin_end(8)

        for i, (label, icon, *_) in enumerate(_VIEWS):
            btn = Gtk.ToggleButton()
            btn.add_css_class("flat")

            row = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=10)
            row.set_margin_start(8)
            row.set_margin_top(4)
            row.set_margin_bottom(4)
            img = Gtk.Image.new_from_icon_name(icon)
            lbl = Gtk.Label(label=label)
            lbl.set_halign(Gtk.Align.START)
            lbl.set_hexpand(True)
            row.append(img)
            row.append(lbl)
            btn.set_child(row)

            idx = i
            btn.connect("toggled", self._on_nav_toggled, idx)
            nav_box.append(btn)
            self._nav_buttons.append(btn)

        scroll.set_child(nav_box)
        sidebar.append(scroll)

        # Lock button at bottom
        sep2 = Gtk.Separator()
        sep2.set_margin_top(8)
        sidebar.append(sep2)

        # Atrium kiosk display — prominent gold button so it's
        # discoverable. Same action as F12 / `meli --kiosk`.
        atrium_btn = Gtk.Button(label="⚡  Launch Atrium")
        atrium_btn.add_css_class("suggested-action")
        atrium_btn.add_css_class("honey-accent")
        atrium_btn.set_tooltip_text(
            "Full-screen Labyrinth Atrium kiosk display  (F12)")
        atrium_btn.set_margin_start(12)
        atrium_btn.set_margin_end(12)
        atrium_btn.set_margin_top(8)
        atrium_btn.connect("clicked", lambda _: self._launch_atrium())
        sidebar.append(atrium_btn)

        lock_btn = Gtk.Button(label="Lock")
        lock_btn.set_margin_all(12)
        lock_btn.connect("clicked", lambda _: self.show_lock_screen())
        sidebar.append(lock_btn)

        return sidebar

    def _launch_atrium(self) -> None:
        """Open the Atrium kiosk window via the app-level action."""
        app = self.get_application()
        if app is None:
            return
        try:
            # Prefer the app's own helper so window-lifecycle tracking
            # stays single-sourced. Fall back to direct construction
            # if the app isn't a MeliApplication (e.g. tests).
            opener = getattr(app, "_open_atrium", None)
            if callable(opener):
                opener()
                return
            from meli.ui.atrium import AtriumWindow
            AtriumWindow(application=app, fullscreen=True).present()
        except Exception as e:
            log.error("Atrium launch failed", error=str(e))

    # ── Navigation ────────────────────────────────────────────────────────────

    def _on_nav_toggled(self, btn: Gtk.ToggleButton, idx: int) -> None:
        if not btn.get_active():
            return
        # Deactivate others
        for i, b in enumerate(self._nav_buttons):
            if i != idx:
                b.handler_block_by_func(self._on_nav_toggled)
                b.set_active(False)
                b.handler_unblock_by_func(self._on_nav_toggled)
        self._navigate_to(idx)

    def _navigate_to(self, idx: int) -> None:
        if idx < 0 or idx >= len(_VIEWS):
            return
        label, _, module_path, class_name = _VIEWS[idx]

        # Activate sidebar button
        self._nav_buttons[idx].handler_block_by_func(self._on_nav_toggled)
        self._nav_buttons[idx].set_active(True)
        self._nav_buttons[idx].handler_unblock_by_func(self._on_nav_toggled)

        key = f"{module_path}.{class_name}"
        if key not in self._view_instances:
            try:
                import importlib
                mod = importlib.import_module(module_path)
                cls = getattr(mod, class_name)
                view = cls()
                self._view_instances[key] = view
                self._stack.add_named(view, key)
            except Exception as e:
                log.error("Failed to load view", view=class_name, error=str(e))
                err = Gtk.Label(label=f"Error loading {label}: {e}")
                self._view_instances[key] = err
                self._stack.add_named(err, key)

        self._stack.set_visible_child_name(key)
        self._reset_idle_timer()

    # ── Lock screen ───────────────────────────────────────────────────────────

    def show_lock_screen(self) -> None:
        from meli.ui.lock_screen import LockScreen
        if self._lock_overlay:
            return
        lock = LockScreen()
        lock.connect("unlocked", self._on_unlocked)
        self._overlay.add_overlay(lock)
        self._lock_overlay = lock
        lock_session()
        log.info("Lock screen shown")

    def _on_unlocked(self, lock_screen: Gtk.Widget) -> None:
        self._overlay.remove_overlay(lock_screen)
        self._lock_overlay = None
        self._reset_idle_timer()
        log.info("Session unlocked")
        # Notify the application so it can honor a pending --kiosk launch.
        try:
            app = self.get_application()
            hook = getattr(app, "on_post_unlock", None)
            if callable(hook):
                hook()
        except Exception as e:
            log.warning("post-unlock hook failed", error=str(e))

    # ── Idle timer (auto-lock) ────────────────────────────────────────────────

    def _start_idle_timer(self) -> None:
        cfg = get_config()
        minutes = cfg.get("auth", "auto_lock_minutes", default=10)
        self._idle_minutes = minutes
        self._reset_idle_timer()

    def _reset_idle_timer(self) -> None:
        if self._idle_timer:
            GLib.source_remove(self._idle_timer)
        if self._idle_minutes > 0:
            ms = self._idle_minutes * 60 * 1000
            self._idle_timer = GLib.timeout_add(ms, self._on_idle_timeout)

    def _on_idle_timeout(self) -> bool:
        if is_authenticated():
            log.info("Idle timeout — locking session")
            GLib.idle_add(self.show_lock_screen)
        return False  # don't repeat

    # ── Keyboard shortcuts ────────────────────────────────────────────────────

    def _register_shortcuts(self) -> None:
        ctrl = Gtk.EventControllerKey()
        ctrl.connect("key-pressed", self._on_key_pressed)
        self.add_controller(ctrl)

    def _on_key_pressed(self, ctrl, keyval, keycode, state) -> bool:
        ctrl_mask = Gdk.ModifierType.CONTROL_MASK
        has_ctrl = bool(state & ctrl_mask)

        if has_ctrl and keyval == Gdk.KEY_l:
            self.show_lock_screen()
            return True
        if has_ctrl and keyval == Gdk.KEY_comma:
            self._navigate_to(13)  # Settings
            return True
        if has_ctrl and keyval == Gdk.KEY_f:
            # TODO: focus search in current view
            return True
        if has_ctrl and keyval == Gdk.KEY_r:
            self._refresh_current_view()
            return True

        # Number shortcuts 1-9 → views 0-8
        if Gdk.KEY_1 <= keyval <= Gdk.KEY_9:
            idx = keyval - Gdk.KEY_1
            self._navigate_to(idx)
            return True
        if keyval == Gdk.KEY_0:
            self._navigate_to(0)
            return True

        return False

    def _refresh_current_view(self) -> None:
        child = self._stack.get_visible_child()
        if child and hasattr(child, "refresh"):
            child.refresh()

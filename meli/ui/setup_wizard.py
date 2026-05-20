"""
Meli first-run setup wizard.
Steps: Welcome → Password → 2FA → Honeypot → API Keys → GeoIP → Complete
"""
from __future__ import annotations

import gi
gi.require_version("Gtk", "4.0")
gi.require_version("Adw", "1")

from gi.repository import Gtk, Adw, GLib, GObject  # noqa: E402

import structlog
from meli.auth import set_master_password, setup_totp, confirm_totp_setup
from meli.config import get_config

log = structlog.get_logger()

_STEPS = ["Welcome", "Password", "2FA (Optional)", "First Honeypot",
          "API Keys (Optional)", "GeoIP", "Complete"]


class SetupWizard(Adw.Window):
    __gsignals__ = {
        "wizard-complete": (GObject.SignalFlags.RUN_FIRST, None, ()),
    }

    def __init__(self, **kwargs) -> None:
        super().__init__(
            title="Meli Setup",
            default_width=600,
            default_height=500,
            modal=True,
            **kwargs,
        )
        self._step = 0
        self._totp_secret = None
        self._build_ui()
        self._show_step(0)

    def _build_ui(self) -> None:
        self._carousel = Adw.Carousel()
        self._carousel.set_allow_scroll_wheel(False)
        self._carousel.set_interactive(False)

        # Build all pages
        self._pages = [
            self._page_welcome(),
            self._page_password(),
            self._page_2fa(),
            self._page_honeypot(),
            self._page_api_keys(),
            self._page_geoip(),
            self._page_complete(),
        ]
        for page in self._pages:
            self._carousel.append(page)

        nav = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=12)
        nav.set_margin_all(16)
        nav.set_halign(Gtk.Align.END)

        self._back_btn = Gtk.Button(label="Back")
        self._back_btn.connect("clicked", self._on_back)
        self._back_btn.set_visible(False)

        self._next_btn = Gtk.Button(label="Next")
        self._next_btn.add_css_class("suggested-action")
        self._next_btn.connect("clicked", self._on_next)

        nav.append(self._back_btn)
        nav.append(self._next_btn)

        # Progress dots
        dots = Adw.CarouselIndicatorDots()
        dots.set_carousel(self._carousel)

        box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL)
        box.append(self._carousel)
        box.append(dots)
        box.append(nav)
        self.set_content(box)

    # ── Steps ─────────────────────────────────────────────────────────────────

    def _page_welcome(self) -> Gtk.Widget:
        box = self._centered_box()
        title = Gtk.Label(label="Welcome to Meli")
        title.add_css_class("title-1")
        title.add_css_class("amber-accent")
        desc = Gtk.Label(label=(
            "Meli is your personal honeypot command center.\n"
            "This wizard will help you set up authentication,\n"
            "connect your first honeypot, and configure enrichment APIs.\n\n"
            "Author: Joseph Sierengowski  |  MIT License"
        ))
        desc.set_justify(Gtk.Justification.CENTER)
        desc.set_wrap(True)
        box.append(title)
        box.append(desc)
        return box

    def _page_password(self) -> Gtk.Widget:
        box = self._centered_box()
        title = Gtk.Label(label="Set Master Password")
        title.add_css_class("title-2")

        self._pw1 = Adw.PasswordEntryRow(title="Password (min 12 characters)")
        self._pw2 = Adw.PasswordEntryRow(title="Confirm Password")
        self._pw_error = Gtk.Label(label="")
        self._pw_error.add_css_class("error")
        self._pw_error.set_visible(False)

        grp = Adw.PreferencesGroup()
        grp.add(self._pw1)
        grp.add(self._pw2)

        box.append(title)
        box.append(grp)
        box.append(self._pw_error)
        return box

    def _page_2fa(self) -> Gtk.Widget:
        box = self._centered_box()
        title = Gtk.Label(label="Two-Factor Authentication")
        title.add_css_class("title-2")
        desc = Gtk.Label(label="Optional: Enable TOTP 2FA for added security.\nScan the QR code with your authenticator app.")
        desc.set_wrap(True)
        desc.set_justify(Gtk.Justification.CENTER)

        self._enable_2fa = Gtk.CheckButton(label="Enable TOTP 2FA")
        self._enable_2fa.connect("toggled", self._on_2fa_toggled)

        self._qr_label = Gtk.Label(label="(Enable 2FA above to see QR code)")
        self._qr_label.add_css_class("monospace")
        self._qr_label.set_wrap(True)
        self._qr_label.set_selectable(True)

        self._totp_verify_row = Adw.EntryRow(title="Enter first 2FA code to confirm")
        self._totp_verify_row.set_visible(False)

        box.append(title)
        box.append(desc)
        box.append(self._enable_2fa)
        box.append(self._qr_label)
        box.append(self._totp_verify_row)
        return box

    def _page_honeypot(self) -> Gtk.Widget:
        box = self._centered_box()
        title = Gtk.Label(label="Add Your First Honeypot")
        title.add_css_class("title-2")
        desc = Gtk.Label(label="Connect at least one honeypot data source.\nYou can add more in Settings → Honeypot Sources.")
        desc.set_wrap(True)

        grp = Adw.PreferencesGroup()
        self._hp_name = Adw.EntryRow(title="Honeypot Name (e.g. cowrie-vps1)")
        self._hp_type = Adw.ComboRow(title="Type")
        model = Gtk.StringList.new(["cowrie", "heralding", "dionaea", "http", "glastopf", "mailoney", "generic_json"])
        self._hp_type.set_model(model)
        self._hp_method = Adw.ComboRow(title="Ingestion Method")
        method_model = Gtk.StringList.new(["MQTT", "Log File", "HTTP POST"])
        self._hp_method.set_model(method_model)
        grp.add(self._hp_name)
        grp.add(self._hp_type)
        grp.add(self._hp_method)

        skip_label = Gtk.Label(label="You can skip this step and add honeypots later.")
        skip_label.add_css_class("caption")
        skip_label.set_opacity(0.6)

        box.append(title)
        box.append(desc)
        box.append(grp)
        box.append(skip_label)
        return box

    def _page_api_keys(self) -> Gtk.Widget:
        box = self._centered_box()
        title = Gtk.Label(label="Enrichment API Keys")
        title.add_css_class("title-2")
        desc = Gtk.Label(label="Optional: Enter API keys for IP enrichment.\nAll keys are optional and can be added in Settings later.")
        desc.set_wrap(True)

        grp = Adw.PreferencesGroup()
        self._api_abuse = Adw.PasswordEntryRow(title="AbuseIPDB API Key")
        self._api_gn = Adw.PasswordEntryRow(title="GreyNoise API Key")
        self._api_vt = Adw.PasswordEntryRow(title="VirusTotal API Key")
        self._api_shodan = Adw.PasswordEntryRow(title="Shodan API Key")
        for row in [self._api_abuse, self._api_gn, self._api_vt, self._api_shodan]:
            grp.add(row)

        box.append(title)
        box.append(desc)
        box.append(grp)
        return box

    def _page_geoip(self) -> Gtk.Widget:
        box = self._centered_box()
        title = Gtk.Label(label="GeoIP Database")
        title.add_css_class("title-2")
        desc = Gtk.Label(label=(
            "Meli uses MaxMind GeoLite2 databases for offline IP geolocation.\n"
            "Enter your MaxMind license key to download automatically.\n"
            "(Free account at maxmind.com — no credit card required)"
        ))
        desc.set_wrap(True)
        desc.set_justify(Gtk.Justification.CENTER)

        grp = Adw.PreferencesGroup()
        self._maxmind_key = Adw.PasswordEntryRow(title="MaxMind License Key")
        grp.add(self._maxmind_key)

        self._geoip_download_btn = Gtk.Button(label="Download GeoLite2 Databases")
        self._geoip_download_btn.add_css_class("suggested-action")
        self._geoip_download_btn.connect("clicked", self._on_download_geoip)

        self._geoip_status = Gtk.Label(label="Not downloaded — geolocation will be unavailable until downloaded")
        self._geoip_status.add_css_class("caption")
        self._geoip_status.set_opacity(0.7)

        box.append(title)
        box.append(desc)
        box.append(grp)
        box.append(self._geoip_download_btn)
        box.append(self._geoip_status)
        return box

    def _page_complete(self) -> Gtk.Widget:
        box = self._centered_box()
        title = Gtk.Label(label="Setup Complete!")
        title.add_css_class("title-1")
        title.add_css_class("amber-accent")
        desc = Gtk.Label(label=(
            "Meli is ready.\n\n"
            "Your first honeypot events will appear in the Live Feed\n"
            "as soon as your honeypot starts sending data.\n\n"
            "Keyboard shortcuts:\n"
            "  Ctrl+L — Lock  |  Ctrl+, — Settings  |  1-9 — Switch views"
        ))
        desc.set_wrap(True)
        desc.set_justify(Gtk.Justification.CENTER)
        box.append(title)
        box.append(desc)
        return box

    # ── Navigation ────────────────────────────────────────────────────────────

    def _show_step(self, step: int) -> None:
        self._step = step
        self._carousel.scroll_to(self._pages[step], True)
        self._back_btn.set_visible(step > 0)
        is_last = step == len(_STEPS) - 1
        self._next_btn.set_label("Launch Meli" if is_last else "Next")

    def _on_next(self, _) -> None:
        if not self._validate_current_step():
            return
        self._save_current_step()

        if self._step == len(_STEPS) - 1:
            self.emit("wizard-complete")
            self.close()
        else:
            self._show_step(self._step + 1)

    def _on_back(self, _) -> None:
        if self._step > 0:
            self._show_step(self._step - 1)

    def _validate_current_step(self) -> bool:
        if self._step == 1:  # Password
            pw1 = self._pw1.get_text()
            pw2 = self._pw2.get_text()
            if len(pw1) < 12:
                self._pw_error.set_text("Password must be at least 12 characters")
                self._pw_error.set_visible(True)
                return False
            if pw1 != pw2:
                self._pw_error.set_text("Passwords do not match")
                self._pw_error.set_visible(True)
                return False
            self._pw_error.set_visible(False)
        return True

    def _save_current_step(self) -> None:
        cfg = get_config()
        if self._step == 1:
            set_master_password(self._pw1.get_text())

        elif self._step == 2 and self._enable_2fa.get_active():
            code = self._totp_verify_row.get_text()
            if code:
                confirm_totp_setup(code)

        elif self._step == 3:
            hp_name = self._hp_name.get_text()
            if hp_name:
                hp_type_idx = self._hp_type.get_selected()
                types = ["cowrie", "heralding", "dionaea", "http", "glastopf", "mailoney", "generic_json"]
                methods = ["mqtt", "logfile", "http"]
                hp_type = types[hp_type_idx] if hp_type_idx < len(types) else "cowrie"
                method = methods[self._hp_method.get_selected()]
                from meli.utils.helpers import generate_token
                from meli.database import get_db
                from meli.database.models import Honeypot
                with get_db() as db:
                    db.add(Honeypot(name=hp_name, honeypot_type=hp_type,
                                    ingest_method=method, ingest_token=generate_token()))

        elif self._step == 4:
            for key_name, row in [
                ("abuseipdb", self._api_abuse), ("greynoise", self._api_gn),
                ("virustotal", self._api_vt), ("shodan", self._api_shodan),
            ]:
                val = row.get_text()
                if val:
                    cfg.set("enrichment", "services", key_name, "api_key", val)
                    cfg.set("enrichment", "services", key_name, "enabled", True)

        elif self._step == 5:
            key = self._maxmind_key.get_text()
            if key:
                cfg.set("enrichment", "maxmind_license_key", key)

    def _on_2fa_toggled(self, btn: Gtk.CheckButton) -> None:
        enabled = btn.get_active()
        if enabled:
            secret, uri = setup_totp()
            self._totp_secret = secret
            self._qr_label.set_text(f"OTPAuth URI (paste into authenticator):\n{uri}")
            self._totp_verify_row.set_visible(True)
        else:
            self._qr_label.set_text("(Enable 2FA above to see QR code)")
            self._totp_verify_row.set_visible(False)

    def _on_download_geoip(self, _) -> None:
        key = self._maxmind_key.get_text()
        if not key:
            self._geoip_status.set_text("Enter your MaxMind license key first")
            return
        self._geoip_download_btn.set_sensitive(False)
        self._geoip_status.set_text("Downloading... this may take a minute")
        import threading
        cfg = get_config()
        output_dir = str(cfg.data_dir / "geoip")
        def _download():
            from meli.enrichment.geolocation import download_geolite2
            ok = download_geolite2(key, output_dir)
            GLib.idle_add(self._geoip_download_done, ok)
        threading.Thread(target=_download, daemon=True).start()

    def _geoip_download_done(self, success: bool) -> None:
        self._geoip_download_btn.set_sensitive(True)
        if success:
            self._geoip_status.set_text("GeoLite2 databases downloaded successfully")
        else:
            self._geoip_status.set_text("Download failed — check your license key and internet connection")

    @staticmethod
    def _centered_box() -> Gtk.Box:
        box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=16)
        box.set_halign(Gtk.Align.CENTER)
        box.set_valign(Gtk.Align.CENTER)
        box.set_hexpand(True)
        box.set_vexpand(True)
        box.set_margin_all(40)
        box.set_size_request(500, -1)
        return box

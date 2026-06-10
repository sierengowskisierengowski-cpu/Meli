"""Live Feed view — real-time honeypot event stream (v2.7.1 hive look).

Visual contract: matches the mockup's panel + ticker styling — gold
section-bar header, amber-on-black ticker rows with severity-coloured
left border, hive pills for severity filter."""
from __future__ import annotations

import gi
gi.require_version("Gtk", "4.0")
gi.require_version("Adw", "1")
from gi.repository import Gtk, Adw, GLib

import json
import threading
import structlog

from meli.ui.widgets import HiveHeader, CairoPanel
from collections import deque
from datetime import datetime, timezone

log = structlog.get_logger()
MAX_EVENTS = 500
SEV_LEVELS = ["ALL", "CRITICAL", "HIGH", "MEDIUM", "LOW", "INFO"]


def _section_header(title: str, accent: str | None = None,
                    right_widget: Gtk.Widget | None = None) -> Gtk.Box:
    bar = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=10)
    stripe = Gtk.Box()
    stripe.add_css_class("hive-section-bar")
    stripe.set_size_request(5, 18)
    bar.append(stripe)
    t = Gtk.Label(label=title.upper())
    t.add_css_class("hive-section-title")
    t.set_xalign(0)
    bar.append(t)
    if accent:
        pill = Gtk.Label(label=accent)
        pill.add_css_class("hive-section-accent")
        bar.append(pill)
    spacer = Gtk.Box()
    spacer.set_hexpand(True)
    bar.append(spacer)
    if right_widget is not None:
        bar.append(right_widget)
    return bar


class LiveFeedView(Gtk.Box):
    def __init__(self) -> None:
        super().__init__(orientation=Gtk.Orientation.VERTICAL)
        self._paused = False
        self._events: deque = deque(maxlen=MAX_EVENTS)
        self._severity_filter = "ALL"
        self._filter_buttons: dict[str, Gtk.ToggleButton] = {}
        self._build_ui()
        self._subscribe_mqtt()

    # ── UI build ─────────────────────────────────────────────────────

    def _build_ui(self) -> None:
        # Hive header
        self._header = HiveHeader(title="Live Feed",
                                  status_label="STREAMING",
                                  status_kind="live")
        # Export icon on the right of the header
        export_btn = Gtk.Button.new_from_icon_name("document-save-symbolic")
        export_btn.set_tooltip_text("Export visible events")
        export_btn.add_css_class("flat")
        export_btn.connect("clicked", self._on_export)
        self._header.pack_end(export_btn)
        self.append(self._header)

        # Outer scrollable content with margins
        scroll = Gtk.ScrolledWindow()
        scroll.set_policy(Gtk.PolicyType.NEVER, Gtk.PolicyType.AUTOMATIC)
        scroll.set_vexpand(True)
        content = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=12)
        content.set_margin_top(16)
        content.set_margin_bottom(16)
        content.set_margin_start(16)
        content.set_margin_end(16)

        # ── Control bar panel (Pause / Clear + severity pills + count)
        ctl_panel = CairoPanel(orientation=Gtk.Orientation.VERTICAL, spacing=10)

        ctl_panel.append(_section_header("Stream Controls", accent="LIVE"))

        ctl_row = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=8)

        # Pause toggle
        self._pause_btn = Gtk.ToggleButton(label="❚❚  Pause")
        self._pause_btn.add_css_class("hive-action")
        self._pause_btn.set_tooltip_text("Spacebar to pause/resume")
        self._pause_btn.connect("toggled", self._on_pause_toggled)
        ctl_row.append(self._pause_btn)

        # Clear button
        clear_btn = Gtk.Button(label="⌫  Clear")
        clear_btn.add_css_class("hive-action")
        clear_btn.connect("clicked", self._on_clear)
        ctl_row.append(clear_btn)

        # Spacer
        spacer = Gtk.Box()
        spacer.set_hexpand(True)
        ctl_row.append(spacer)

        # Severity filter pills (mutually exclusive)
        pill_box = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=6)
        for sev in SEV_LEVELS:
            btn = Gtk.ToggleButton(label=sev)
            btn.add_css_class("hive-pill-filter")
            btn.add_css_class(f"sev-{sev.lower()}")
            if sev == "ALL":
                btn.set_active(True)
                btn.add_css_class("active")
            btn.connect("toggled", self._on_filter_toggled, sev)
            self._filter_buttons[sev] = btn
            pill_box.append(btn)
        ctl_row.append(pill_box)

        ctl_panel.append(ctl_row)

        # Status line — count + follow indicator
        status_row = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=8)
        self._count_label = Gtk.Label(label="0 events captured")
        self._count_label.add_css_class("text-muted")
        self._count_label.set_xalign(0)
        self._count_label.set_hexpand(True)
        status_row.append(self._count_label)
        self._follow_lbl = Gtk.Label(label="▼ FOLLOWING")
        self._follow_lbl.add_css_class("text-amber")
        self._follow_lbl.add_css_class("mono")
        status_row.append(self._follow_lbl)
        ctl_panel.append(status_row)

        content.append(ctl_panel)

        # ── Stream panel (ticker rows) ──────────────────────────────
        stream_panel = CairoPanel(orientation=Gtk.Orientation.VERTICAL, spacing=8)
        stream_panel.set_vexpand(True)
        stream_panel.append(_section_header("Event Stream", accent="LAST 500"))

        # Empty state stays in the panel until first event arrives
        self._empty = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=8)
        self._empty.set_valign(Gtk.Align.CENTER)
        self._empty.set_halign(Gtk.Align.CENTER)
        self._empty.set_vexpand(True)
        big = Gtk.Label(label="◇  WAITING FOR EVENTS")
        big.add_css_class("text-amber")
        big.add_css_class("mono")
        sub = Gtk.Label(label=(
            "Start a honeypot and ingest into Meli via\n"
            "MQTT  topic  meli/events/ingest\n"
            "HTTP  POST   http://127.0.0.1:17654/api/v1/events/ingest"
        ))
        sub.add_css_class("text-muted")
        sub.set_justify(Gtk.Justification.CENTER)
        self._empty.append(big)
        self._empty.append(sub)
        stream_panel.append(self._empty)

        # The actual event list (Gtk.Box of ticker rows, prepended)
        self._stream_holder = Gtk.Box(orientation=Gtk.Orientation.VERTICAL,
                                      spacing=4)
        self._stream_holder.set_vexpand(True)
        self._stream_holder.set_visible(False)
        stream_panel.append(self._stream_holder)

        content.append(stream_panel)

        scroll.set_child(content)
        self.append(scroll)

    # ── MQTT subscription ────────────────────────────────────────────

    def _subscribe_mqtt(self) -> None:
        def _run():
            try:
                import paho.mqtt.client as mqtt
                from meli.config import get_config
                cfg = get_config()
                client = mqtt.Client(
                    client_id="meli-live-feed",
                    callback_api_version=mqtt.CallbackAPIVersion.VERSION2,
                )

                def on_message(_c, _u, msg):
                    if self._paused:
                        return
                    try:
                        event = json.loads(msg.payload.decode())
                        GLib.idle_add(self._add_event, event)
                    except Exception:
                        pass

                client.on_message = on_message
                client.connect(cfg.get("mqtt", "host", default="127.0.0.1"),
                               cfg.get("mqtt", "port", default=1883))
                client.subscribe(cfg.get("mqtt", "topic_processed",
                                         default="meli/events/processed"))
                client.loop_forever()
            except Exception as e:
                log.debug("Live feed MQTT subscribe failed", error=str(e))

        threading.Thread(target=_run, daemon=True).start()

    # ── Event handling ───────────────────────────────────────────────

    def _add_event(self, event: dict) -> bool:
        sev = (event.get("severity") or "INFO").upper()
        if self._severity_filter != "ALL" and sev != self._severity_filter:
            return False

        self._events.appendleft(event)
        row = self._make_event_row(event)
        first = self._stream_holder.get_first_child()
        if first is not None:
            self._stream_holder.insert_child_after(row, None)
        else:
            self._stream_holder.append(row)

        # Trim
        count = 0
        child = self._stream_holder.get_first_child()
        rows = []
        while child:
            count += 1
            rows.append(child)
            child = child.get_next_sibling()
        if count > MAX_EVENTS:
            for extra in rows[MAX_EVENTS:]:
                self._stream_holder.remove(extra)
            count = MAX_EVENTS

        self._count_label.set_text(f"{count:,} events captured · {sev.lower()} stream")
        if self._empty.get_visible():
            self._empty.set_visible(False)
            self._stream_holder.set_visible(True)

        # CRITICAL → audio alert
        if sev == "CRITICAL":
            threading.Thread(
                target=lambda: __import__("meli.alerts.sound",
                                          fromlist=["play_alert_sound"])
                .play_alert_sound("CRITICAL"),
                daemon=True,
            ).start()

        return False

    def _make_event_row(self, event: dict) -> Gtk.Box:
        sev = (event.get("severity") or "INFO").upper()
        sev_cls = sev.lower()

        row = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=10)
        row.add_css_class("ticker-row")
        row.add_css_class(sev_cls)

        ts = event.get("timestamp", "")
        ts_str = str(ts)[11:19] if len(str(ts)) >= 19 else (str(ts) or "--:--:--")
        ts_lbl = Gtk.Label(label=ts_str)
        ts_lbl.add_css_class("ticker-time")
        ts_lbl.set_size_request(70, -1)
        ts_lbl.set_xalign(0)
        row.append(ts_lbl)

        sev_pill = Gtk.Label(label=sev)
        sev_pill.add_css_class("ticker-sev-pill")
        sev_pill.add_css_class(f"ticker-sev-{sev_cls}")
        row.append(sev_pill)

        country = (event.get("country_code")
                   or (event.get("geo") or {}).get("country_code", ""))
        if country:
            try:
                from meli.utils.helpers import country_flag_emoji
                flag_lbl = Gtk.Label(
                    label=f"{country_flag_emoji(country)} {country}")
                flag_lbl.add_css_class("ticker-svc")
                row.append(flag_lbl)
            except Exception:
                pass

        ip_lbl = Gtk.Label(label=event.get("source_ip") or "—")
        ip_lbl.add_css_class("ticker-ip")
        ip_lbl.set_size_request(130, -1)
        ip_lbl.set_xalign(0)
        row.append(ip_lbl)

        svc_lbl = Gtk.Label(label=event.get("honeypot_service") or "—")
        svc_lbl.add_css_class("ticker-svc")
        svc_lbl.set_size_request(90, -1)
        svc_lbl.set_xalign(0)
        row.append(svc_lbl)

        msg = (event.get("action_type")
               or (event.get("event_data") or {}).get("message", "")
               if isinstance(event.get("event_data"), dict)
               else event.get("action_type") or "")
        msg_lbl = Gtk.Label(label=str(msg)[:120])
        msg_lbl.add_css_class("ticker-msg")
        msg_lbl.set_xalign(0)
        msg_lbl.set_hexpand(True)
        msg_lbl.set_ellipsize(3)
        row.append(msg_lbl)

        # Click → detail dialog
        click = Gtk.GestureClick()
        click.connect("released", lambda *_args, e=event:
                      self._show_event_detail(e))
        row.add_controller(click)
        return row

    def _show_event_detail(self, event: dict) -> None:
        dialog = Adw.MessageDialog(
            heading=f"Event Detail — {event.get('source_ip', 'unknown')}",
            body=json.dumps(event, indent=2, default=str),
        )
        dialog.add_response("close", "Close")
        dialog.set_default_response("close")
        top = self.get_root()
        if top:
            dialog.set_transient_for(top)
        dialog.present()

    # ── Toolbar callbacks ────────────────────────────────────────────

    def _on_pause_toggled(self, btn: Gtk.ToggleButton) -> None:
        self._paused = btn.get_active()
        btn.set_label("▶  Resume" if self._paused else "❚❚  Pause")
        try:
            if self._paused:
                self._header.set_status("PAUSED", "warn")
            else:
                self._header.set_status("STREAMING", "live")
        except Exception:
            pass

    def _on_filter_toggled(self, btn: Gtk.ToggleButton, severity: str) -> None:
        if btn.get_active():
            self._severity_filter = severity
            for sev, b in self._filter_buttons.items():
                if sev != severity and b.get_active():
                    b.handler_block_by_func(self._on_filter_toggled)
                    b.set_active(False)
                    b.handler_unblock_by_func(self._on_filter_toggled)
                if sev == severity:
                    b.add_css_class("active")
                else:
                    b.remove_css_class("active")
        else:
            # Don't allow no-pill state — re-activate ALL
            if not any(b.get_active() for b in self._filter_buttons.values()):
                all_btn = self._filter_buttons["ALL"]
                all_btn.handler_block_by_func(self._on_filter_toggled)
                all_btn.set_active(True)
                all_btn.handler_unblock_by_func(self._on_filter_toggled)
                all_btn.add_css_class("active")
                self._severity_filter = "ALL"

    def _on_clear(self, _) -> None:
        self._events.clear()
        child = self._stream_holder.get_first_child()
        while child:
            nxt = child.get_next_sibling()
            self._stream_holder.remove(child)
            child = nxt
        self._count_label.set_text("0 events captured")
        self._stream_holder.set_visible(False)
        self._empty.set_visible(True)

    def _on_export(self, _) -> None:
        data = list(self._events)
        from pathlib import Path
        from meli.config import get_config
        cfg = get_config()
        ts = datetime.now(timezone.utc).strftime("%Y%m%d_%H%M%S")
        out = Path(cfg.data_dir) / "exports" / f"live_feed_{ts}.json"
        out.parent.mkdir(parents=True, exist_ok=True)
        out.write_text(json.dumps(data, indent=2, default=str))
        dialog = Adw.MessageDialog(
            heading="Export Complete",
            body=f"Saved {len(data)} events to:\n{out}",
        )
        dialog.add_response("ok", "OK")
        top = self.get_root()
        if top:
            dialog.set_transient_for(top)
        dialog.present()

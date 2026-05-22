"""Live Feed view — real-time MQTT event stream."""
from __future__ import annotations

import gi
gi.require_version("Gtk", "4.0")
gi.require_version("Adw", "1")
from gi.repository import Gtk, Adw, GLib

import json
import threading
import structlog
from collections import deque
from datetime import datetime, timezone

log = structlog.get_logger()
MAX_EVENTS = 500


class LiveFeedView(Gtk.Box):
    def __init__(self) -> None:
        super().__init__(orientation=Gtk.Orientation.VERTICAL)
        self._paused = False
        self._events: deque = deque(maxlen=MAX_EVENTS)
        self._severity_filter = "ALL"
        self._build_ui()
        self._subscribe_mqtt()

    def _build_ui(self) -> None:
        header = Adw.HeaderBar()
        header.set_title_widget(Gtk.Label(label="Live Feed"))

        # Pause button
        self._pause_btn = Gtk.ToggleButton(label="Pause")
        self._pause_btn.connect("toggled", self._on_pause_toggled)
        self._pause_btn.set_tooltip_text("Spacebar to pause/resume")
        header.pack_start(self._pause_btn)

        # Severity filter
        sev_box = Gtk.Box(spacing=4)
        for sev in ["ALL", "CRITICAL", "HIGH", "MEDIUM", "LOW", "INFO"]:
            btn = Gtk.ToggleButton(label=sev)
            if sev == "ALL":
                btn.set_active(True)
            btn.connect("toggled", self._on_filter_toggled, sev)
            sev_box.append(btn)
        header.pack_end(sev_box)

        # Export button
        export_btn = Gtk.Button.new_from_icon_name("document-save-symbolic")
        export_btn.set_tooltip_text("Export visible events")
        export_btn.connect("clicked", self._on_export)
        header.pack_end(export_btn)

        self.append(header)

        # Clear button + event count
        toolbar = Gtk.Box(spacing=8)
        toolbar.set_margin_start(12)
        toolbar.set_margin_end(12)
        toolbar.set_margin_top(8)
        self._count_label = Gtk.Label(label="0 events")
        self._count_label.set_hexpand(True)
        self._count_label.set_xalign(0)
        clear_btn = Gtk.Button(label="Clear")
        clear_btn.connect("clicked", self._on_clear)
        toolbar.append(self._count_label)
        toolbar.append(clear_btn)
        self.append(toolbar)

        # Event list
        scroll = Gtk.ScrolledWindow()
        scroll.set_policy(Gtk.PolicyType.NEVER, Gtk.PolicyType.AUTOMATIC)
        scroll.set_vexpand(True)
        self._list_box = Gtk.ListBox()
        self._list_box.set_selection_mode(Gtk.SelectionMode.SINGLE)
        self._list_box.add_css_class("boxed-list")
        self._list_box.connect("row-activated", self._on_row_activated)
        scroll.set_child(self._list_box)
        self.append(scroll)

        # Empty state
        self._empty = Gtk.Label(label=(
            "Waiting for events...\n\n"
            "Start your honeypot and ensure it is sending events to Meli\n"
            "via MQTT (meli/events/ingest) or HTTP POST (:17654/api/v1/events/ingest)"
        ))
        self._empty.set_justify(Gtk.Justification.CENTER)
        self._empty.set_opacity(0.6)
        self._empty.set_vexpand(True)
        self._empty.set_valign(Gtk.Align.CENTER)
        self.append(self._empty)
        self._empty.set_visible(True)

    def _subscribe_mqtt(self) -> None:
        """Subscribe to the processed events topic for live display."""
        def _run():
            try:
                import paho.mqtt.client as mqtt
                from meli.config import get_config
                cfg = get_config()

                client = mqtt.Client(
                    client_id="meli-live-feed",
                    callback_api_version=mqtt.CallbackAPIVersion.VERSION2,
                )

                def on_message(c, u, msg):
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

    def _add_event(self, event: dict) -> bool:
        sev = event.get("severity", "INFO").upper()
        if self._severity_filter != "ALL" and sev != self._severity_filter:
            return False

        self._events.appendleft(event)
        row = self._make_event_row(event)
        self._list_box.prepend(row)

        # Trim list if too long
        count = 0
        child = self._list_box.get_first_child()
        while child:
            count += 1
            child = child.get_next_sibling()
        if count > MAX_EVENTS:
            last = self._list_box.get_row_at_index(MAX_EVENTS)
            if last:
                self._list_box.remove(last)

        self._count_label.set_text(f"{min(count, MAX_EVENTS)} events")
        self._empty.set_visible(False)

        # Sound on CRITICAL
        if sev == "CRITICAL":
            threading.Thread(target=lambda: __import__("meli.alerts.sound", fromlist=["play_alert_sound"]).play_alert_sound("CRITICAL"), daemon=True).start()

        return False

    def _make_event_row(self, event: dict) -> Gtk.ListBoxRow:
        row = Gtk.ListBoxRow()
        row._event = event
        box = Gtk.Box(spacing=12)
        box.set_margin_all(8)

        ts = event.get("timestamp", "")
        ts_str = str(ts)[:19] if ts else "—"
        ts_lbl = Gtk.Label(label=ts_str)
        ts_lbl.add_css_class("monospace")
        ts_lbl.set_size_request(160, -1)

        sev = event.get("severity", "INFO")
        sev_lbl = Gtk.Label(label=sev)
        sev_lbl.add_css_class(f"severity-{sev.lower()}")
        sev_lbl.set_size_request(80, -1)

        ip_lbl = Gtk.Label(label=event.get("source_ip", "—"))
        ip_lbl.add_css_class("monospace")
        ip_lbl.set_size_request(140, -1)

        svc_lbl = Gtk.Label(label=event.get("honeypot_service", "—"))
        svc_lbl.set_size_request(90, -1)

        action_lbl = Gtk.Label(label=event.get("action_type", "—"))
        action_lbl.set_hexpand(True)
        action_lbl.set_xalign(0)

        country = event.get("country_code") or event.get("geo", {}).get("country_code", "")
        if country:
            from meli.utils.helpers import country_flag_emoji
            flag_lbl = Gtk.Label(label=f"{country_flag_emoji(country)} {country}")
            box.append(flag_lbl)

        for w in [ts_lbl, sev_lbl, ip_lbl, svc_lbl, action_lbl]:
            box.append(w)
        row.set_child(box)
        return row

    def _on_row_activated(self, list_box, row) -> None:
        event = getattr(row, "_event", {})
        self._show_event_detail(event)

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

    def _on_pause_toggled(self, btn: Gtk.ToggleButton) -> None:
        self._paused = btn.get_active()
        btn.set_label("Resume" if self._paused else "Pause")

    def _on_filter_toggled(self, btn: Gtk.ToggleButton, severity: str) -> None:
        if btn.get_active():
            self._severity_filter = severity

    def _on_clear(self, _) -> None:
        self._events.clear()
        child = self._list_box.get_first_child()
        while child:
            nxt = child.get_next_sibling()
            self._list_box.remove(child)
            child = nxt
        self._count_label.set_text("0 events")
        self._empty.set_visible(True)

    def _on_export(self, _) -> None:
        data = list(self._events)
        import json
        from pathlib import Path
        from meli.config import get_config
        cfg = get_config()
        ts = datetime.now(timezone.utc).strftime("%Y%m%d_%H%M%S")
        out = Path(cfg.data_dir) / "exports" / f"live_feed_{ts}.json"
        out.parent.mkdir(parents=True, exist_ok=True)
        out.write_text(json.dumps(data, indent=2, default=str))
        dialog = Adw.MessageDialog(heading="Export Complete",
                                   body=f"Saved {len(data)} events to:\n{out}")
        dialog.add_response("ok", "OK")
        top = self.get_root()
        if top:
            dialog.set_transient_for(top)
        dialog.present()

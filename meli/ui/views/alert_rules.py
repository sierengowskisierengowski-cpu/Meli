"""Alert Rules view — CRUD for rules + alert history."""
from __future__ import annotations

import gi
gi.require_version("Gtk", "4.0")
gi.require_version("Adw", "1")
from gi.repository import Gtk, Adw, GLib

import json
import threading
import structlog

from meli.ui.widgets import HiveHeader, HivePrefsGroup

log = structlog.get_logger()


class AlertRulesView(Gtk.Box):
    def __init__(self) -> None:
        super().__init__(orientation=Gtk.Orientation.VERTICAL)
        self._build_ui()
        self.refresh()

    def _build_ui(self) -> None:
        header = HiveHeader(title="Alert Rules",

                           status_label="ARMED",

                           status_kind="configured")
        add_btn = Gtk.Button(label="New Rule")
        add_btn.add_css_class("suggested-action")
        add_btn.connect("clicked", self._on_add_rule)
        header.pack_start(add_btn)
        refresh_btn = Gtk.Button.new_from_icon_name("view-refresh-symbolic")
        refresh_btn.connect("clicked", lambda _: self.refresh())
        header.pack_end(refresh_btn)
        self.append(header)

        # Tabs: Rules | History
        self._stack = Gtk.Stack()
        self._stack.set_transition_type(Gtk.StackTransitionType.SLIDE_LEFT_RIGHT)
        self._stack.set_vexpand(True)

        switcher = Gtk.StackSwitcher()
        switcher.set_stack(self._stack)
        switcher.set_halign(Gtk.Align.CENTER)
        switcher.set_margin_top(8)
        switcher.set_margin_bottom(8)
        self.append(switcher)

        # Rules tab
        rules_scroll = Gtk.ScrolledWindow()
        self._rules_list = Gtk.ListBox()
        self._rules_list.set_selection_mode(Gtk.SelectionMode.NONE)
        self._rules_list.add_css_class("boxed-list")
        self._rules_list.set_margin_all(12)
        rules_scroll.set_child(self._rules_list)
        self._stack.add_titled(rules_scroll, "rules", "Alert Rules")

        # History tab
        hist_scroll = Gtk.ScrolledWindow()
        self._hist_list = Gtk.ListBox()
        self._hist_list.set_selection_mode(Gtk.SelectionMode.NONE)
        self._hist_list.add_css_class("boxed-list")
        self._hist_list.set_margin_all(12)
        hist_scroll.set_child(self._hist_list)
        self._stack.add_titled(hist_scroll, "history", "Alert History")

        self.append(self._stack)

    def refresh(self) -> None:
        threading.Thread(target=self._load_rules, daemon=True).start()
        threading.Thread(target=self._load_history, daemon=True).start()

    def _load_rules(self) -> None:
        try:
            from meli.database import get_db
            from meli.database.models import AlertRule
            from sqlalchemy import select
            with get_db() as db:
                rules = db.execute(select(AlertRule).order_by(AlertRule.id)).scalars().all()
                data = [(r.id, r.name, r.severity_threshold, r.enabled,
                         r.fire_count, str(r.last_triggered)[:19] if r.last_triggered else "Never")
                        for r in rules]
            GLib.idle_add(self._populate_rules, data)
        except Exception as e:
            log.error("Alert rules load failed", error=str(e))

    def _load_history(self) -> None:
        try:
            from meli.database import get_db
            from meli.database.models import Alert
            from sqlalchemy import select
            with get_db() as db:
                alerts = db.execute(
                    select(Alert).order_by(Alert.triggered_at.desc()).limit(200)
                ).scalars().all()
                data = [(a.id, a.rule_name, a.severity, a.summary,
                         str(a.triggered_at)[:19], a.acknowledged) for a in alerts]
            GLib.idle_add(self._populate_history, data)
        except Exception as e:
            log.error("Alert history load failed", error=str(e))

    def _populate_rules(self, data: list) -> bool:
        child = self._rules_list.get_first_child()
        while child:
            nxt = child.get_next_sibling()
            self._rules_list.remove(child)
            child = nxt

        for rid, name, severity, enabled, fire_count, last_fired in data:
            row = Adw.ActionRow(
                title=name,
                subtitle=f"Threshold: {severity} — Fired: {fire_count}× — Last: {last_fired}"
            )
            toggle = Gtk.Switch()
            toggle.set_active(enabled)
            toggle.set_valign(Gtk.Align.CENTER)
            rule_id = rid
            toggle.connect("state-set", self._on_toggle_rule, rule_id)
            row.add_suffix(toggle)

            delete_btn = Gtk.Button.new_from_icon_name("user-trash-symbolic")
            delete_btn.add_css_class("flat")
            delete_btn.connect("clicked", self._on_delete_rule, rule_id, name)
            row.add_suffix(delete_btn)

            self._rules_list.append(row)

        if not data:
            empty = Adw.ActionRow(
                title="No alert rules configured",
                subtitle="Click 'New Rule' to create your first alert"
            )
            self._rules_list.append(empty)
        return False

    def _populate_history(self, data: list) -> bool:
        child = self._hist_list.get_first_child()
        while child:
            nxt = child.get_next_sibling()
            self._hist_list.remove(child)
            child = nxt

        for aid, rule_name, severity, summary, triggered, acknowledged in data:
            row = Adw.ActionRow(
                title=f"[{severity}] {rule_name}",
                subtitle=f"{triggered} — {(summary or '')[:100]}"
            )
            if not acknowledged:
                ack_btn = Gtk.Button(label="Acknowledge")
                ack_btn.set_valign(Gtk.Align.CENTER)
                alert_id = aid
                ack_btn.connect("clicked", self._on_ack, alert_id)
                row.add_suffix(ack_btn)
            else:
                ack_lbl = Gtk.Label(label="✓ Acked")
                ack_lbl.set_opacity(0.5)
                row.add_suffix(ack_lbl)
            self._hist_list.append(row)

        if not data:
            empty = Adw.ActionRow(title="No alerts fired yet", subtitle="Alert history will appear here when rules trigger")
            self._hist_list.append(empty)
        return False

    def _on_add_rule(self, _) -> None:
        self._show_rule_dialog()

    def _show_rule_dialog(self, rule_id: int | None = None) -> None:
        dialog = Adw.Window(title="New Alert Rule", default_width=500, default_height=400, modal=True)
        top = self.get_root()
        if top:
            dialog.set_transient_for(top)

        box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=12)
        box.set_margin_all(16)

        grp = HivePrefsGroup(title="Rule Definition")
        name_row = Adw.EntryRow(title="Rule Name")
        sev_row = Adw.ComboRow(title="Minimum Severity")
        sev_model = Gtk.StringList.new(["INFO", "LOW", "MEDIUM", "HIGH", "CRITICAL"])
        sev_row.set_model(sev_model)
        sev_row.set_selected(3)  # HIGH
        channels_row = Adw.EntryRow(title="Notification Channels (desktop,discord,slack)")
        cooldown_row = Adw.SpinRow.new_with_range(0, 3600, 60)
        cooldown_row.set_title("Cooldown (seconds)")
        cooldown_row.set_value(300)
        grp.add(name_row)
        grp.add(sev_row)
        grp.add(channels_row)
        grp.add(cooldown_row)

        save_btn = Gtk.Button(label="Save Rule")
        save_btn.add_css_class("suggested-action")

        def _save(_):
            name = name_row.get_text()
            if not name:
                return
            severities = ["INFO", "LOW", "MEDIUM", "HIGH", "CRITICAL"]
            sev = severities[sev_row.get_selected()]
            channels = [c.strip() for c in channels_row.get_text().split(",") if c.strip()]
            cooldown = int(cooldown_row.get_value())
            threading.Thread(target=_create_rule,
                             args=(name, sev, channels, cooldown),
                             daemon=True).start()
            dialog.close()
            GLib.timeout_add(500, self.refresh)

        def _create_rule(name, sev, channels, cooldown):
            from meli.database import get_db
            from meli.database.models import AlertRule
            with get_db() as db:
                db.add(AlertRule(
                    name=name,
                    severity_threshold=sev,
                    notification_channels=json.dumps(channels),
                    cooldown_seconds=cooldown,
                    enabled=True,
                ))

        save_btn.connect("clicked", _save)
        cancel_btn = Gtk.Button(label="Cancel")
        cancel_btn.connect("clicked", lambda _: dialog.close())
        btn_box = Gtk.Box(spacing=8)
        btn_box.set_halign(Gtk.Align.END)
        btn_box.append(cancel_btn)
        btn_box.append(save_btn)

        box.append(grp)
        box.append(btn_box)
        dialog.set_content(box)
        dialog.present()

    def _on_toggle_rule(self, switch: Gtk.Switch, state: bool, rule_id: int) -> bool:
        def _update():
            from meli.database import get_db
            from meli.database.models import AlertRule
            with get_db() as db:
                rule = db.get(AlertRule, rule_id)
                if rule:
                    rule.enabled = state
        threading.Thread(target=_update, daemon=True).start()
        return False

    def _on_delete_rule(self, _, rule_id: int, name: str) -> None:
        dialog = Adw.MessageDialog(heading=f"Delete '{name}'?",
                                    body="This action cannot be undone.")
        dialog.add_response("cancel", "Cancel")
        dialog.add_response("delete", "Delete")
        dialog.set_response_appearance("delete", Adw.ResponseAppearance.DESTRUCTIVE)
        def _on_response(d, response):
            if response == "delete":
                def _del():
                    from meli.database import get_db
                    from meli.database.models import AlertRule
                    with get_db() as db:
                        rule = db.get(AlertRule, rule_id)
                        if rule: db.delete(rule)
                    GLib.idle_add(self.refresh)
                threading.Thread(target=_del, daemon=True).start()
        dialog.connect("response", _on_response)
        top = self.get_root()
        if top: dialog.set_transient_for(top)
        dialog.present()

    def _on_ack(self, _, alert_id: int) -> None:
        from datetime import datetime, timezone
        def _ack():
            from meli.database import get_db
            from meli.database.models import Alert
            with get_db() as db:
                alert = db.get(Alert, alert_id)
                if alert:
                    alert.acknowledged = True
                    alert.acknowledged_at = datetime.now(timezone.utc)
            GLib.idle_add(self._load_history)
        threading.Thread(target=_ack, daemon=True).start()

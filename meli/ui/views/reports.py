"""Reports view — generate and browse threat intelligence reports."""
from __future__ import annotations

import gi
gi.require_version("Gtk", "4.0")
gi.require_version("Adw", "1")
from gi.repository import Gtk, Adw, GLib

import subprocess
import threading
import structlog

from meli.ui.widgets import HiveHeader, HivePrefsGroup

log = structlog.get_logger()


class ReportsView(Gtk.Box):
    def __init__(self) -> None:
        super().__init__(orientation=Gtk.Orientation.VERTICAL)
        self._build_ui()
        self.refresh()

    def _build_ui(self) -> None:
        header = HiveHeader(title="Reports",

                           status_label="READY",

                           status_kind="configured")
        gen_btn = Gtk.Button(label="Generate Report")
        gen_btn.add_css_class("suggested-action")
        gen_btn.connect("clicked", self._on_generate)
        header.pack_start(gen_btn)
        refresh_btn = Gtk.Button.new_from_icon_name("view-refresh-symbolic")
        refresh_btn.connect("clicked", lambda _: self.refresh())
        header.pack_end(refresh_btn)
        self.append(header)

        scroll = Gtk.ScrolledWindow()
        scroll.set_vexpand(True)
        self._list_box = Gtk.ListBox()
        self._list_box.set_selection_mode(Gtk.SelectionMode.NONE)
        self._list_box.add_css_class("boxed-list")
        self._list_box.set_margin_all(12)
        scroll.set_child(self._list_box)
        self.append(scroll)

    def refresh(self) -> None:
        threading.Thread(target=self._load, daemon=True).start()

    def _load(self) -> None:
        try:
            from meli.database import get_db
            from meli.database.models import Report
            from sqlalchemy import select
            with get_db() as db:
                reports = db.execute(
                    select(Report).order_by(Report.generated_at.desc()).limit(100)
                ).scalars().all()
                data = [(r.id, r.report_type, r.report_format, r.file_path,
                         str(r.generated_at)[:19], r.summary) for r in reports]
            GLib.idle_add(self._populate, data)
        except Exception as e:
            log.error("Reports load failed", error=str(e))

    def _populate(self, data: list) -> bool:
        child = self._list_box.get_first_child()
        while child:
            nxt = child.get_next_sibling()
            self._list_box.remove(child)
            child = nxt

        for rid, rtype, fmt, path, generated, summary in data:
            row = Adw.ActionRow(
                title=f"{rtype.title()} Report ({fmt.upper()})",
                subtitle=f"{generated} — {summary or '—'}"
            )
            open_btn = Gtk.Button(label="Open")
            open_btn.set_valign(Gtk.Align.CENTER)
            file_path = path
            open_btn.connect("clicked", lambda _, p=file_path: subprocess.Popen(["xdg-open", p]))
            row.add_suffix(open_btn)
            self._list_box.append(row)

        if not data:
            empty = Adw.ActionRow(
                title="No reports generated yet",
                subtitle="Click 'Generate Report' to create your first report"
            )
            self._list_box.append(empty)
        return False

    def _on_generate(self, _) -> None:
        dialog = Adw.Window(title="Generate Report", default_width=400, default_height=300, modal=True)
        top = self.get_root()
        if top:
            dialog.set_transient_for(top)

        box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=12)
        box.set_margin_all(16)

        grp = HivePrefsGroup(title="Report Options")
        type_row = Adw.ComboRow(title="Type")
        type_model = Gtk.StringList.new(["daily", "weekly", "monthly", "custom"])
        type_row.set_model(type_model)
        type_row.set_selected(1)  # weekly
        fmt_row = Adw.ComboRow(title="Format")
        fmt_model = Gtk.StringList.new(["markdown", "pdf", "json", "csv"])
        fmt_row.set_model(fmt_model)
        grp.add(type_row)
        grp.add(fmt_row)

        self._gen_status = Gtk.Label(label="")
        gen_btn = Gtk.Button(label="Generate")
        gen_btn.add_css_class("suggested-action")

        def _gen(_):
            types = ["daily", "weekly", "monthly", "custom"]
            fmts = ["markdown", "pdf", "json", "csv"]
            rtype = types[type_row.get_selected()]
            fmt = fmts[fmt_row.get_selected()]
            gen_btn.set_sensitive(False)
            self._gen_status.set_text("Generating...")

            def _run():
                from meli.reports.generator import generate_report
                try:
                    path = generate_report(rtype, fmt)
                    GLib.idle_add(lambda: (
                        self._gen_status.set_text(f"Generated: {path.name}"),
                        gen_btn.set_sensitive(True),
                        GLib.timeout_add(1500, lambda: (dialog.close(), self.refresh(), False)),
                    ))
                except Exception as e:
                    GLib.idle_add(lambda: (
                        self._gen_status.set_text(f"Error: {e}"),
                        gen_btn.set_sensitive(True),
                    ))

            threading.Thread(target=_run, daemon=True).start()

        gen_btn.connect("clicked", _gen)
        cancel_btn = Gtk.Button(label="Cancel")
        cancel_btn.connect("clicked", lambda _: dialog.close())
        btn_box = Gtk.Box(spacing=8)
        btn_box.set_halign(Gtk.Align.END)
        btn_box.append(cancel_btn)
        btn_box.append(gen_btn)

        box.append(grp)
        box.append(self._gen_status)
        box.append(btn_box)
        dialog.set_content(box)
        dialog.present()

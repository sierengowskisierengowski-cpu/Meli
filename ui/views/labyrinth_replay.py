"""Labyrinth Replay — load a recorded session and play it back like a
terminal recording. Two-column layout: picker on the left (recent
session files, sorted by mtime), playback panel on the right (text view
+ transport controls + speed selector).

Playback uses GLib.timeout_add with a delay computed from the recorded
inter-event `t` deltas, scaled by the speed multiplier. The current
event index lives on the widget so pause / step / scrub all manipulate
the same cursor. Playback never blocks the GTK main loop — each timer
tick fires one event and schedules the next.
"""
from __future__ import annotations

import gi
gi.require_version("Gtk", "4.0")
gi.require_version("Adw", "1")
from gi.repository import Gtk, Adw, GLib, Gio, Pango  # noqa: E402

import time
import threading
from datetime import datetime, timezone

import structlog

from meli.ui.widgets import HiveHeader

log = structlog.get_logger()

SPEEDS = [("¼×", 0.25), ("1×", 1.0), ("2×", 2.0), ("8×", 8.0), ("Instant", 0.0)]


def _fmt_dur(sec: float) -> str:
    sec = int(sec)
    if sec < 60:
        return f"{sec}s"
    if sec < 3600:
        return f"{sec // 60}m {sec % 60}s"
    return f"{sec // 3600}h {(sec % 3600) // 60}m"


def _fmt_ago(ts: float) -> str:
    delta = max(0, int(time.time() - ts))
    if delta < 60:
        return f"{delta}s ago"
    if delta < 3600:
        return f"{delta // 60}m ago"
    if delta < 86400:
        return f"{delta // 3600}h ago"
    return f"{delta // 86400}d ago"


class LabyrinthReplayView(Gtk.Box):
    def __init__(self) -> None:
        super().__init__(orientation=Gtk.Orientation.VERTICAL)

        self._events: list[dict] = []
        self._cursor: int = 0
        self._timer_id: int | None = None
        self._playing: bool = False
        self._speed: float = 1.0
        self._sessions: list = []          # list[ReplayMeta]
        self._loaded_path = None
        self._list_inflight = False

        self._build_ui()
        self.connect("map", lambda *_: self._refresh_list_async())
        self.connect("unmap", lambda *_: self._stop_playback())
        self.connect("destroy", lambda *_: self._stop_playback())

    # ── UI ────────────────────────────────────────────────────────────

    def _build_ui(self) -> None:
        header = HiveHeader(title="Labyrinth Replay",

                           status_label="LIVE",

                           status_kind="live")
        refresh_btn = Gtk.Button.new_from_icon_name("view-refresh-symbolic")
        refresh_btn.set_tooltip_text("Reload session list")
        refresh_btn.connect("clicked", lambda *_: self._refresh_list_async())
        header.pack_end(refresh_btn)
        # v2.1: Export the currently loaded session as an asciinema .cast
        # file (watchable in asciinema CLI or embeddable on a webpage).
        # Disabled until a session has been picked + loaded.
        self._export_cast_btn = Gtk.Button(label="Export .cast")
        self._export_cast_btn.set_tooltip_text(
            "Export the loaded session as an asciinema cast file")
        self._export_cast_btn.set_sensitive(False)
        self._export_cast_btn.connect("clicked",
                                      lambda *_: self._export_cast())
        header.pack_end(self._export_cast_btn)
        # v2.1: Export the firewall blocklist generated from the sticky
        # roster + canary trips. Format picker is part of the save dialog.
        export_bl_btn = Gtk.Button(label="Export blocklist…")
        export_bl_btn.set_tooltip_text(
            "Generate a fail2ban / iptables / nftables / ufw / CIDR blocklist")
        export_bl_btn.connect("clicked",
                              lambda *_: self._export_blocklist_dialog())
        header.pack_end(export_bl_btn)
        self.append(header)

        paned = Gtk.Paned(orientation=Gtk.Orientation.HORIZONTAL)
        paned.set_vexpand(True)
        paned.set_position(360)
        self.append(paned)

        paned.set_start_child(self._build_picker())
        paned.set_end_child(self._build_player())

    def _build_picker(self) -> Gtk.Widget:
        scroll = Gtk.ScrolledWindow()
        scroll.set_policy(Gtk.PolicyType.NEVER, Gtk.PolicyType.AUTOMATIC)
        self._picker_list = Gtk.ListBox()
        self._picker_list.set_selection_mode(Gtk.SelectionMode.SINGLE)
        self._picker_list.connect("row-activated", self._on_pick)
        self._picker_list.add_css_class("navigation-sidebar")
        scroll.set_child(self._picker_list)
        return scroll

    def _build_player(self) -> Gtk.Widget:
        outer = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=0)

        # Top: session info
        self._info_label = Gtk.Label()
        self._info_label.set_xalign(0)
        self._info_label.set_wrap(True)
        self._info_label.set_margin_top(10)
        self._info_label.set_margin_start(14)
        self._info_label.set_margin_end(14)
        self._info_label.set_use_markup(True)
        self._info_label.set_markup("<i>Pick a session on the left.</i>")
        outer.append(self._info_label)

        # Terminal text area
        term_scroll = Gtk.ScrolledWindow()
        term_scroll.set_vexpand(True)
        term_scroll.set_margin_top(8)
        term_scroll.set_margin_bottom(8)
        term_scroll.set_margin_start(14)
        term_scroll.set_margin_end(14)
        self._term_view = Gtk.TextView()
        self._term_view.set_editable(False)
        self._term_view.set_cursor_visible(False)
        self._term_view.set_monospace(True)
        self._term_view.set_wrap_mode(Gtk.WrapMode.WORD_CHAR)
        self._term_buf = self._term_view.get_buffer()
        # Color tags
        self._tag_cmd = self._term_buf.create_tag("cmd", foreground="#a8d8ff",
                                                  weight=Pango.Weight.BOLD)
        self._tag_resp = self._term_buf.create_tag("resp", foreground="#cccccc")
        self._tag_meta = self._term_buf.create_tag("meta", foreground="#888888",
                                                   style=Pango.Style.ITALIC)
        self._tag_canary = self._term_buf.create_tag("canary", foreground="#ff6b6b",
                                                     weight=Pango.Weight.BOLD)
        self._tag_login = self._term_buf.create_tag("login", foreground="#ffe066")
        term_scroll.set_child(self._term_view)
        outer.append(term_scroll)

        # Transport controls
        controls = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=8)
        controls.set_margin_start(14)
        controls.set_margin_end(14)
        controls.set_margin_bottom(12)

        self._play_btn = Gtk.Button.new_from_icon_name("media-playback-start-symbolic")
        self._play_btn.set_tooltip_text("Play / Pause")
        self._play_btn.connect("clicked", self._on_play_pause)
        controls.append(self._play_btn)

        step_btn = Gtk.Button.new_from_icon_name("media-skip-forward-symbolic")
        step_btn.set_tooltip_text("Step one event")
        step_btn.connect("clicked", self._on_step)
        controls.append(step_btn)

        restart_btn = Gtk.Button.new_from_icon_name("media-playback-stop-symbolic")
        restart_btn.set_tooltip_text("Restart from beginning")
        restart_btn.connect("clicked", self._on_restart)
        controls.append(restart_btn)

        spacer = Gtk.Box()
        spacer.set_hexpand(True)
        controls.append(spacer)

        controls.append(Gtk.Label(label="Speed"))
        self._speed_dropdown = Gtk.DropDown.new_from_strings([s[0] for s in SPEEDS])
        self._speed_dropdown.set_selected(1)  # 1x default
        self._speed_dropdown.connect("notify::selected", self._on_speed_changed)
        controls.append(self._speed_dropdown)

        self._progress = Gtk.Label(label="0 / 0")
        self._progress.add_css_class("dim-label")
        self._progress.set_size_request(70, -1)
        self._progress.set_xalign(1)
        controls.append(self._progress)

        outer.append(controls)
        return outer

    # ── session list ───────────────────────────────────────────────────

    def _refresh_list_async(self) -> None:
        if self._list_inflight:
            return
        self._list_inflight = True

        def _worker():
            try:
                from meli.labyrinth import replay
                rows = replay.list_sessions(limit=200)
            except Exception as e:
                log.debug("replay list failed", error=str(e))
                rows = []
            GLib.idle_add(self._apply_list, rows)

        threading.Thread(target=_worker, name="meli-replay-list",
                         daemon=True).start()

    def _apply_list(self, rows) -> bool:
        self._list_inflight = False
        self._sessions = rows
        # Clear
        child = self._picker_list.get_first_child()
        while child:
            nxt = child.get_next_sibling()
            self._picker_list.remove(child)
            child = nxt
        if not rows:
            empty = Gtk.ListBoxRow()
            empty.set_selectable(False)
            empty.set_activatable(False)
            lbl = Gtk.Label(label="No recorded sessions yet.")
            lbl.add_css_class("dim-label")
            lbl.set_margin_all(14)
            empty.set_child(lbl)
            self._picker_list.append(empty)
            return False
        for idx, meta in enumerate(rows):
            self._picker_list.append(self._make_picker_row(idx, meta))
        return False

    def _make_picker_row(self, idx: int, meta) -> Gtk.ListBoxRow:
        row = Gtk.ListBoxRow()
        # Stash the index so the row-activated handler can find the meta
        row._meli_idx = idx  # type: ignore[attr-defined]
        box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=2)
        box.set_margin_all(8)
        line1 = Gtk.Box(spacing=8)
        ip = Gtk.Label(label=meta.peer_ip or "—")
        ip.add_css_class("monospace")
        ip.set_xalign(0)
        line1.append(ip)
        proto = Gtk.Label(label=meta.protocol or "?")
        proto.add_css_class("dim-label")
        line1.append(proto)
        spacer = Gtk.Box(); spacer.set_hexpand(True); line1.append(spacer)
        if meta.bot_score is not None:
            badge = Gtk.Label(label=f"bot {meta.bot_score}")
            cls = "error" if meta.bot_score >= 70 else "warning" if meta.bot_score >= 40 else "success"
            badge.add_css_class(cls)
            line1.append(badge)
        box.append(line1)

        line2 = Gtk.Box(spacing=8)
        meta_lbl = Gtk.Label(label=(
            f"{meta.event_count} events  ·  {_fmt_dur(meta.duration)}"
            + (f"  ·  {meta.canary_count} canary" if meta.canary_count else "")
            + ("  ·  truncated" if meta.truncated else "")
        ))
        meta_lbl.add_css_class("dim-label")
        meta_lbl.set_xalign(0)
        line2.append(meta_lbl)
        sp2 = Gtk.Box(); sp2.set_hexpand(True); line2.append(sp2)
        ago = Gtk.Label(label=_fmt_ago(meta.mtime))
        ago.add_css_class("dim-label")
        line2.append(ago)
        box.append(line2)
        row.set_child(box)
        return row

    def _on_pick(self, _list, row) -> None:
        idx = getattr(row, "_meli_idx", None)
        if idx is None or idx >= len(self._sessions):
            return
        meta = self._sessions[idx]
        self._load(meta)

    # ── load + render ──────────────────────────────────────────────────

    def _load(self, meta) -> None:
        self._stop_playback()
        from meli.labyrinth import replay
        self._events = list(replay.load_session(meta.path))
        self._cursor = 0
        self._loaded_path = meta.path
        self._term_buf.set_text("")
        try:
            ts = datetime.fromtimestamp(meta.mtime, tz=timezone.utc)
            when = ts.strftime("%Y-%m-%d %H:%M:%S UTC")
        except Exception:
            when = "—"
        score_str = (
            f"  ·  bot <b>{meta.bot_score}</b> ({meta.bot_confidence or '—'})"
            if meta.bot_score is not None else ""
        )
        self._info_label.set_markup(
            f"<b>{meta.peer_ip}</b>  ·  {meta.protocol}  ·  {when}  "
            f"·  {_fmt_dur(meta.duration)}  ·  {meta.event_count} events"
            f"{score_str}  ·  <small><tt>{meta.path.name}</tt></small>"
        )
        self._update_progress()
        # Enable .cast export now that a session is loaded.
        try:
            self._export_cast_btn.set_sensitive(True)
        except Exception:
            pass

    # ── v2.1: blocklist + cast export ─────────────────────────────────

    _BLOCKLIST_FORMATS = [
        ("fail2ban", "fail2ban", "meli-blocklist.conf"),
        ("iptables", "iptables", "meli-blocklist.iptables.sh"),
        ("nftables", "nftables", "meli-blocklist.nft"),
        ("ufw",      "ufw",      "meli-blocklist.ufw.sh"),
        ("cidr",     "cidr",     "meli-blocklist.txt"),
    ]

    def _export_blocklist_dialog(self) -> None:
        """Pop a small format-picker, then a FileDialog save prompt."""
        root = self.get_root()
        dlg = Adw.MessageDialog()
        if isinstance(root, Gtk.Window):
            dlg.set_transient_for(root)
        dlg.set_modal(True)
        dlg.set_heading("Export blocklist")
        dlg.set_body("Pick a firewall format. The blocklist is built from "
                     "the sticky roster + recent canary trips.")
        for code, label, _fn in self._BLOCKLIST_FORMATS:
            dlg.add_response(code, label)
        dlg.add_response("cancel", "Cancel")
        dlg.set_default_response("fail2ban")
        dlg.set_close_response("cancel")
        dlg.connect("response", self._on_blocklist_format_chosen)
        dlg.present()

    def _on_blocklist_format_chosen(self, dlg, response: str) -> None:
        if response == "cancel":
            return
        fmt = response
        # Find the suggested filename for this format
        suggested = "meli-blocklist.txt"
        for code, _label, fn in self._BLOCKLIST_FORMATS:
            if code == fmt:
                suggested = fn
                break
        fd = Gtk.FileDialog()
        fd.set_title(f"Save {fmt} blocklist")
        fd.set_initial_name(suggested)
        root = self.get_root()
        parent = root if isinstance(root, Gtk.Window) else None
        fd.save(parent, None, self._on_blocklist_save_done, fmt)

    def _on_blocklist_save_done(self, dialog, result, fmt: str) -> None:
        try:
            gfile = dialog.save_finish(result)
        except GLib.Error as e:
            # User cancelled or write target unavailable.
            log.debug("blocklist save cancelled", error=str(e))
            return
        path = gfile.get_path() if gfile else None
        if not path:
            return

        def _worker():
            err = None
            count = 0
            try:
                from meli.labyrinth import blocklist
                # generate() returns (rendered_text, entry_count).
                rendered, count = blocklist.generate(fmt)
                with open(path, "w", encoding="utf-8") as fh:
                    fh.write(rendered)
                log.info("blocklist exported", path=path, fmt=fmt,
                         bytes=len(rendered), entries=count)
            except Exception as e:
                err = str(e)
                log.warning("blocklist export failed", path=path, error=err)
            kind = f"Blocklist ({count} entr{'y' if count == 1 else 'ies'})"
            GLib.idle_add(self._show_export_result, kind, path, err)

        threading.Thread(target=_worker, name="meli-blocklist-export",
                         daemon=True).start()

    def _export_cast(self) -> None:
        if not self._loaded_path:
            return
        loaded_name = getattr(self._loaded_path, "stem", "session")
        fd = Gtk.FileDialog()
        fd.set_title("Save asciinema cast")
        fd.set_initial_name(f"{loaded_name}.cast")
        root = self.get_root()
        parent = root if isinstance(root, Gtk.Window) else None
        fd.save(parent, None, self._on_cast_save_done)

    def _on_cast_save_done(self, dialog, result) -> None:
        try:
            gfile = dialog.save_finish(result)
        except GLib.Error as e:
            log.debug("cast save cancelled", error=str(e))
            return
        out_path = gfile.get_path() if gfile else None
        if not out_path:
            return
        in_path = self._loaded_path
        if in_path is None:
            return

        def _worker():
            err = None
            try:
                from pathlib import Path as _P
                from meli.labyrinth import replay_export
                replay_export.export_file(_P(str(in_path)), _P(out_path))
                log.info("cast exported", path=out_path)
            except Exception as e:
                err = str(e)
                log.warning("cast export failed", path=out_path, error=err)
            GLib.idle_add(self._show_export_result,
                          "Asciinema cast", out_path, err)

        threading.Thread(target=_worker, name="meli-cast-export",
                         daemon=True).start()

    def _show_export_result(self, kind: str, path: str,
                            err: str | None) -> bool:
        root = self.get_root()
        dlg = Adw.MessageDialog()
        if isinstance(root, Gtk.Window):
            dlg.set_transient_for(root)
        dlg.set_modal(True)
        if err:
            dlg.set_heading(f"{kind} export failed")
            dlg.set_body(err)
        else:
            dlg.set_heading(f"{kind} exported")
            dlg.set_body(f"Saved to:\n{path}")
        dlg.add_response("ok", "OK")
        dlg.set_default_response("ok")
        dlg.set_close_response("ok")
        dlg.present()
        return False

    def _emit_to_view(self, ev: dict) -> None:
        kind = ev.get("kind", "")
        end = self._term_buf.get_end_iter()
        if kind == "connect":
            text = f"[connect] {ev.get('ip','')}:{ev.get('peer_port','')} ({ev.get('protocol','')})\n"
            self._term_buf.insert_with_tags(end, text, self._tag_meta)
        elif kind == "login_fail":
            self._term_buf.insert_with_tags(end,
                f"login: {ev.get('user','')}  password: {ev.get('password','')}  → FAILED\n",
                self._tag_login)
        elif kind == "login_ok":
            self._term_buf.insert_with_tags(end,
                f"login: {ev.get('user','')}  password: {ev.get('password','')}  → OK\n",
                self._tag_login)
        elif kind == "command":
            self._term_buf.insert_with_tags(end,
                f"$ {ev.get('text','')}\n", self._tag_cmd)
        elif kind == "response":
            self._term_buf.insert_with_tags(end,
                ev.get("text", "") + ("\n" if not ev.get("text","").endswith("\n") else ""),
                self._tag_resp)
        elif kind == "canary":
            self._term_buf.insert_with_tags(end,
                f"[!! CANARY TRIPPED: {ev.get('token_id','')} "
                f"({ev.get('severity','')}) — {ev.get('summary','')}]\n",
                self._tag_canary)
        elif kind == "disconnect":
            self._term_buf.insert_with_tags(end,
                f"[disconnect] duration={ev.get('duration',0):.1f}s  "
                f"commands={ev.get('commands',0)}  "
                f"bot={ev.get('bot_score','?')} ({ev.get('bot_confidence','?')})\n",
                self._tag_meta)
        elif kind == "truncated":
            self._term_buf.insert_with_tags(end,
                f"[... replay truncated: {ev.get('reason','cap')} ...]\n",
                self._tag_meta)
        else:
            self._term_buf.insert_with_tags(end,
                f"[{kind}] {ev}\n", self._tag_meta)
        # Autoscroll
        mark = self._term_buf.create_mark(None, self._term_buf.get_end_iter(), False)
        self._term_view.scroll_mark_onscreen(mark)
        self._term_buf.delete_mark(mark)

    # ── transport ──────────────────────────────────────────────────────

    def _on_play_pause(self, _btn) -> None:
        if self._playing:
            self._stop_playback()
        else:
            self._start_playback()

    def _on_step(self, _btn) -> None:
        self._stop_playback()
        self._advance_one()

    def _on_restart(self, _btn) -> None:
        self._stop_playback()
        self._cursor = 0
        self._term_buf.set_text("")
        self._update_progress()

    def _on_speed_changed(self, dropdown, _pspec) -> None:
        try:
            idx = int(dropdown.get_selected())
        except Exception:
            idx = 1
        self._speed = SPEEDS[idx][1] if 0 <= idx < len(SPEEDS) else 1.0
        if self._playing:
            # Restart the timer cadence under the new speed.
            self._stop_playback()
            self._start_playback()

    def _start_playback(self) -> None:
        if not self._events:
            return
        if self._cursor >= len(self._events):
            self._cursor = 0
            self._term_buf.set_text("")
        self._playing = True
        self._play_btn.set_icon_name("media-playback-pause-symbolic")
        if self._speed == 0.0:
            # Instant replay: dump everything synchronously, no timer needed.
            while self._cursor < len(self._events):
                self._emit_to_view(self._events[self._cursor])
                self._cursor += 1
            self._update_progress()
            self._stop_playback()
            return
        self._schedule_next(initial=True)

    def _stop_playback(self) -> None:
        if self._timer_id is not None:
            try:
                GLib.source_remove(self._timer_id)
            except Exception:
                pass
            self._timer_id = None
        self._playing = False
        self._play_btn.set_icon_name("media-playback-start-symbolic")

    def _advance_one(self) -> None:
        if self._cursor >= len(self._events):
            return
        self._emit_to_view(self._events[self._cursor])
        self._cursor += 1
        self._update_progress()

    def _schedule_next(self, initial: bool = False) -> None:
        if not self._playing or self._cursor >= len(self._events):
            self._stop_playback()
            return
        if initial:
            # Emit first frame immediately, then schedule following.
            self._advance_one()
            if self._cursor >= len(self._events):
                self._stop_playback()
                return
        # Delay until next event = (t[next] - t[prev]) / speed, in ms.
        prev = self._events[self._cursor - 1] if self._cursor > 0 else None
        nxt = self._events[self._cursor]
        try:
            t_prev = float(prev.get("t", 0.0)) if prev else 0.0
            t_next = float(nxt.get("t", 0.0))
            dt = max(0.0, t_next - t_prev)
        except Exception:
            dt = 0.0
        # Clamp delay so we never sleep > 10s between events (long
        # attacker silences would otherwise look broken). Also floor at
        # 5ms so we don't hammer the main loop.
        scaled_ms = int(min(10_000, max(5, (dt / max(0.01, self._speed)) * 1000)))
        self._timer_id = GLib.timeout_add(scaled_ms, self._on_tick)

    def _on_tick(self) -> bool:
        self._timer_id = None
        if not self._playing:
            return False
        self._advance_one()
        if self._cursor >= len(self._events):
            self._stop_playback()
            return False
        self._schedule_next()
        return False  # one-shot; _schedule_next sets the next

    def _update_progress(self) -> None:
        n = len(self._events)
        self._progress.set_text(f"{self._cursor} / {n}")

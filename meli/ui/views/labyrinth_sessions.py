"""Labyrinth Sessions view — live tarpit status + sticky-IP roster.

Three panels stacked vertically:
  1. STATUS HEADER — daemon running / telnet & ssh listening, live count
     of currently-trapped sessions, drop counter.
  2. STICKY IPs — table of every IP we've ever caught (loaded from
     sticky.json), sorted by last_seen.
  3. RECENT SESSIONS — most recent finalized session.closed events
     (joined from the DB), with bot-score badge.

Refreshes on a 2-second GLib timer; refresh pauses when the widget is
unmapped (Gtk.Stack hides it) so we don't poll the DB while the user
is on another view. DB query runs on a worker thread; result is marshalled
back via GLib.idle_add so the GTK main loop is never blocked.
"""
from __future__ import annotations

import gi
gi.require_version("Gtk", "4.0")
gi.require_version("Adw", "1")
from gi.repository import Gtk, Adw, GLib  # noqa: E402

import json
import threading
import time
from datetime import datetime, timezone

from gi.repository import Gio  # noqa: E402  (Gtk already required above)

import structlog

from meli.ui.widgets import HiveHeader, CairoPanel

log = structlog.get_logger()

REFRESH_MS = 2000
STICKY_LIMIT = 200
RECENT_LIMIT = 50


def _fmt_ago(ts: float) -> str:
    if ts <= 0:
        return "—"
    delta = max(0, int(time.time() - ts))
    if delta < 60:
        return f"{delta}s ago"
    if delta < 3600:
        return f"{delta // 60}m ago"
    if delta < 86400:
        return f"{delta // 3600}h ago"
    return f"{delta // 86400}d ago"


def _fmt_dur(sec: float) -> str:
    sec = int(sec)
    if sec < 60:
        return f"{sec}s"
    if sec < 3600:
        return f"{sec // 60}m {sec % 60}s"
    return f"{sec // 3600}h {(sec % 3600) // 60}m"


def _score_badge_class(score: int | None) -> str:
    if score is None:
        return "dim-label"
    if score >= 70:
        return "error"
    if score >= 40:
        return "warning"
    return "success"


class LabyrinthSessionsView(Gtk.Box):
    def __init__(self) -> None:
        super().__init__(orientation=Gtk.Orientation.VERTICAL)
        self._timer_id: int | None = None
        self._recent_fetch_inflight = False
        self._last_recent_rows: list[dict] = []
        self._build_ui()

        # Pause polling when the view is hidden (Gtk.Stack switches us
        # out via unmap), resume when shown. Saves CPU and avoids the
        # GTK main loop doing busy-work for an off-screen widget.
        self.connect("map", lambda *_: self._start_timer())
        self.connect("unmap", lambda *_: self._cancel_timer())
        self.connect("destroy", lambda *_: self._cancel_timer())

    # ── UI construction ────────────────────────────────────────────────

    # ── v2.1: Cohorts dialog ───────────────────────────────────────────

    def _open_cohorts_dialog(self) -> None:
        """Show a non-modal Adw.Window listing cohorts found by scanning
        the last 500 replay sessions. Heavy lifting runs in a worker
        thread so the dialog opens instantly with a spinner."""
        root = self.get_root()
        win = Adw.Window()
        win.set_title("Labyrinth — Cohorts")
        win.set_default_size(640, 520)
        if isinstance(root, Gtk.Window):
            win.set_transient_for(root)
            win.set_modal(False)

        outer = Gtk.Box(orientation=Gtk.Orientation.VERTICAL)
        bar = HiveHeader(title="Cohorts (last 500 sessions)",

                           status_label="ANALYTICS",

                           status_kind="configured")
        outer.append(bar)

        scroll = Gtk.ScrolledWindow()
        scroll.set_vexpand(True)
        scroll.set_policy(Gtk.PolicyType.NEVER, Gtk.PolicyType.AUTOMATIC)
        body = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=8)
        body.set_margin_top(14)
        body.set_margin_bottom(14)
        body.set_margin_start(16)
        body.set_margin_end(16)
        scroll.set_child(body)
        outer.append(scroll)
        win.set_content(outer)

        # Placeholder spinner row
        spinner_row = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=10)
        spinner = Gtk.Spinner()
        spinner.start()
        spinner_row.append(spinner)
        spinner_row.append(Gtk.Label(label="Scanning recent sessions…"))
        body.append(spinner_row)

        def _worker():
            err = None
            cohorts: list = []
            try:
                from meli.labyrinth import cohort
                cohorts = cohort.scan(limit=500)
            except Exception as e:
                err = str(e)
                log.warning("cohort scan failed", error=err)
            GLib.idle_add(_apply, cohorts, err)

        def _apply(cohorts, err):
            # Clear spinner
            child = body.get_first_child()
            while child:
                nxt = child.get_next_sibling()
                body.remove(child)
                child = nxt
            if err:
                err_title = Gtk.Label(label="Cohort scan failed")
                err_title.add_css_class("title-4")
                err_title.add_css_class("error")
                err_title.set_xalign(0)
                body.append(err_title)
                err_body = Gtk.Label(label=err)
                err_body.add_css_class("dim-label")
                err_body.add_css_class("monospace")
                err_body.set_wrap(True)
                err_body.set_xalign(0)
                err_body.set_selectable(True)
                body.append(err_body)
                return False
            if not cohorts:
                lbl = Gtk.Label(label="No cohorts found yet — Meli needs more recorded sessions.")
                lbl.add_css_class("dim-label")
                lbl.set_wrap(True)
                lbl.set_xalign(0)
                body.append(lbl)
                return False
            header = Gtk.Label(label=f"Found {len(cohorts)} cohort(s):")
            header.add_css_class("title-4")
            header.set_xalign(0)
            body.append(header)
            for c in cohorts:
                body.append(self._make_cohort_row(c))
            return False

        threading.Thread(target=_worker, name="meli-cohort-scan",
                         daemon=True).start()
        win.present()

    def _make_cohort_row(self, c) -> Gtk.Widget:
        # Cohort dataclass (meli/labyrinth/cohort.py):
        #   fp: str           # representative fingerprint
        #   members: list     # SessionFingerprint
        #   label: str        # human-readable summary
        #   size: int         # @property → len(members)
        frame = CairoPanel(padding=12, spacing=4)
        box = frame
        head = Gtk.Box(spacing=10)
        title = Gtk.Label()
        title.set_xalign(0)
        # Prefer human-readable label; fall back to the raw fingerprint.
        display = getattr(c, "label", "") or getattr(c, "fp", "") or "?"
        title.set_markup(
            f"<b><tt>{GLib.markup_escape_text(str(display))}</tt></b>")
        head.append(title)
        sp = Gtk.Box(); sp.set_hexpand(True); head.append(sp)
        try:
            size = int(c.size)        # @property
        except Exception:
            size = len(getattr(c, "members", []))
        badge = Gtk.Label(label=f"{size} session{'s' if size != 1 else ''}")
        badge.add_css_class("warning" if size >= 3 else "dim-label")
        head.append(badge)
        box.append(head)
        # Sample members
        members = list(getattr(c, "members", []))[:6]
        if members:
            sample_ips = sorted({getattr(m, "peer_ip", "?") for m in members})[:8]
            ips_lbl = Gtk.Label(label="IPs: " + ", ".join(sample_ips))
            ips_lbl.add_css_class("dim-label")
            ips_lbl.add_css_class("monospace")
            ips_lbl.set_xalign(0)
            ips_lbl.set_wrap(True)
            box.append(ips_lbl)
        return frame

    def _build_ui(self) -> None:
        header = HiveHeader(title="Labyrinth Sessions",

                           status_label="LIVE",

                           status_kind="live")
        refresh_btn = Gtk.Button.new_from_icon_name("view-refresh-symbolic")
        refresh_btn.set_tooltip_text("Refresh now")
        refresh_btn.connect("clicked", lambda *_: self._refresh())
        header.pack_end(refresh_btn)
        # v2.1: "Cohorts" → opens a dialog that clusters the recent
        # session roster by command-fingerprint so the operator can
        # see "these N sessions are the same botnet variant."
        cohorts_btn = Gtk.Button(label="Cohorts")
        cohorts_btn.set_tooltip_text("Group recent sessions by command-fingerprint")
        cohorts_btn.connect("clicked", lambda *_: self._open_cohorts_dialog())
        header.pack_end(cohorts_btn)
        self.append(header)

        scroll = Gtk.ScrolledWindow()
        scroll.set_policy(Gtk.PolicyType.NEVER, Gtk.PolicyType.AUTOMATIC)
        scroll.set_vexpand(True)
        outer = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=18)
        outer.set_margin_top(16)
        outer.set_margin_bottom(16)
        outer.set_margin_start(20)
        outer.set_margin_end(20)
        scroll.set_child(outer)
        self.append(scroll)

        self._status_card = self._make_status_card()
        outer.append(self._status_card)

        sticky_title = Gtk.Label(label="Sticky IPs (returning attackers)")
        sticky_title.add_css_class("title-3")
        sticky_title.set_halign(Gtk.Align.START)
        outer.append(sticky_title)

        self._sticky_list = Gtk.ListBox()
        self._sticky_list.set_selection_mode(Gtk.SelectionMode.NONE)
        self._sticky_list.add_css_class("boxed-list")
        outer.append(self._sticky_list)

        recent_title = Gtk.Label(label="Recent labyrinth sessions")
        recent_title.add_css_class("title-3")
        recent_title.set_halign(Gtk.Align.START)
        recent_title.set_margin_top(8)
        outer.append(recent_title)

        self._recent_list = Gtk.ListBox()
        self._recent_list.set_selection_mode(Gtk.SelectionMode.NONE)
        self._recent_list.add_css_class("boxed-list")
        outer.append(self._recent_list)

    def _make_status_card(self) -> Gtk.Widget:
        card = CairoPanel(padding=16, spacing=4)
        card.set_margin_top(4)
        self._status_label = Gtk.Label()
        self._status_label.set_xalign(0)
        self._status_label.add_css_class("title-2")
        card.append(self._status_label)
        self._detail_label = Gtk.Label()
        self._detail_label.set_xalign(0)
        self._detail_label.add_css_class("dim-label")
        self._detail_label.set_use_markup(True)
        self._detail_label.set_wrap(True)
        card.append(self._detail_label)
        return card

    # ── refresh ────────────────────────────────────────────────────────

    def _start_timer(self) -> None:
        if self._timer_id is not None:
            return
        self._refresh()
        self._timer_id = GLib.timeout_add(REFRESH_MS, self._refresh)

    def _refresh(self) -> bool:
        try:
            self._refresh_status()
            self._refresh_sticky()
            self._refresh_recent_async()
        except Exception as e:
            log.debug("labyrinth sessions refresh error", error=str(e))
        return True  # keep the timer running

    def _get_daemon(self):
        """Reach the active LabyrinthDaemon via GtkApplication.
        Returns None if the daemon isn't running."""
        try:
            root = self.get_root()
            if root is None:
                return None
            app = root.get_application()
            if app is None:
                return None
            return getattr(app, "_labyrinth", None)
        except Exception:
            return None

    def _refresh_status(self) -> None:
        d = self._get_daemon()
        if d is None or not getattr(d, "is_running", lambda: False)():
            self._status_label.set_text("⊘ Labyrinth tarpit is OFF")
            self._detail_label.set_markup(
                "<small>Enable it in <b>Settings → Labyrinth</b> "
                "(<tt>labyrinth.enabled = true</tt>) and restart Meli.</small>"
            )
            return

        telnet_n = d.telnet_session_count() if hasattr(d, "telnet_session_count") else 0
        ssh_n = d.ssh_session_count() if hasattr(d, "ssh_session_count") else 0
        total = telnet_n + ssh_n

        if total == 0:
            self._status_label.set_text("◉ Labyrinth listening — no attackers trapped right now")
        elif total == 1:
            self._status_label.set_text("⚡ 1 attacker trapped right now")
        else:
            self._status_label.set_text(f"⚡ {total} attackers trapped right now")

        try:
            from meli.labyrinth import sink, sticky
            dropped = sink.dropped_count()
            tracked = sticky.count()
        except Exception:
            dropped = 0
            tracked = 0

        ssh_state = "on" if getattr(d, "ssh_enabled", False) else "off"
        self._detail_label.set_markup(
            f"<small>"
            f"Telnet <b>{telnet_n}</b> live  ·  SSH <b>{ssh_n}</b> live ({ssh_state})  "
            f"·  Sticky IPs tracked: <b>{tracked}</b>  "
            f"·  Sink drops: <b>{dropped}</b>  "
            f"·  Bind: <tt>{d.host}:{d.port}</tt>"
            + (f" + <tt>:{d.ssh_port}</tt>" if getattr(d, "ssh_enabled", False) else "")
            + "</small>"
        )

    def _refresh_sticky(self) -> None:
        # Clear + repopulate. sticky.all() is in-memory, instant.
        child = self._sticky_list.get_first_child()
        while child:
            nxt = child.get_next_sibling()
            self._sticky_list.remove(child)
            child = nxt
        try:
            from meli.labyrinth import sticky
            rows = sticky.all()[:STICKY_LIMIT]
        except Exception:
            rows = []
        if not rows:
            empty = Gtk.ListBoxRow()
            empty.set_selectable(False)
            empty.set_activatable(False)
            lbl = Gtk.Label(label="No sticky IPs yet — once an attacker connects, they'll appear here.")
            lbl.set_xalign(0)
            lbl.add_css_class("dim-label")
            lbl.set_margin_all(12)
            empty.set_child(lbl)
            self._sticky_list.append(empty)
            return
        for st in rows:
            self._sticky_list.append(self._make_sticky_row(st))

    def _make_sticky_row(self, st) -> Gtk.ListBoxRow:
        row = Gtk.ListBoxRow()
        row.set_selectable(False)
        row.set_activatable(False)
        box = Gtk.Box(spacing=12)
        box.set_margin_all(10)

        ip = Gtk.Label(label=st.ip)
        ip.add_css_class("monospace")
        ip.set_xalign(0)
        ip.set_size_request(160, -1)
        box.append(ip)

        visits = Gtk.Label(label=f"{st.visits} visits")
        visits.set_size_request(90, -1)
        visits.set_xalign(0)
        if st.returning:
            visits.add_css_class("accent")
        box.append(visits)

        cmds = Gtk.Label(label=f"{st.commands} cmds")
        cmds.set_size_request(90, -1)
        cmds.set_xalign(0)
        cmds.add_css_class("dim-label")
        box.append(cmds)

        protos = Gtk.Label(label="·".join(st.protocols) or "—")
        protos.add_css_class("dim-label")
        protos.set_size_request(80, -1)
        protos.set_xalign(0)
        box.append(protos)

        spacer = Gtk.Box()
        spacer.set_hexpand(True)
        box.append(spacer)

        if st.last_bot_score is not None:
            badge = Gtk.Label(label=f"bot {st.last_bot_score}")
            badge.add_css_class(_score_badge_class(st.last_bot_score))
            box.append(badge)

        ago = Gtk.Label(label=_fmt_ago(st.last_seen))
        ago.add_css_class("dim-label")
        ago.set_size_request(80, -1)
        ago.set_xalign(1)
        box.append(ago)

        row.set_child(box)
        return row

    # ── async DB-backed recent sessions ────────────────────────────────

    def _refresh_recent_async(self) -> None:
        """Dispatch the DB query to a worker thread; the worker marshals
        the result back to the GTK main loop via idle_add. We never block
        the UI on disk IO."""
        if self._recent_fetch_inflight:
            return
        self._recent_fetch_inflight = True

        def _worker():
            rows = self._fetch_recent_sessions()
            GLib.idle_add(self._apply_recent_rows, rows)

        threading.Thread(target=_worker, name="meli-labyrinth-recent",
                         daemon=True).start()

    def _apply_recent_rows(self, rows: list[dict]) -> bool:
        self._recent_fetch_inflight = False
        self._last_recent_rows = rows

        child = self._recent_list.get_first_child()
        while child:
            nxt = child.get_next_sibling()
            self._recent_list.remove(child)
            child = nxt

        if not rows:
            empty = Gtk.ListBoxRow()
            empty.set_selectable(False)
            empty.set_activatable(False)
            lbl = Gtk.Label(label="No completed Labyrinth sessions in the database yet.")
            lbl.set_xalign(0)
            lbl.add_css_class("dim-label")
            lbl.set_margin_all(12)
            empty.set_child(lbl)
            self._recent_list.append(empty)
            return False
        for r in rows:
            self._recent_list.append(self._make_recent_row(r))
        return False

    def _fetch_recent_sessions(self) -> list[dict]:
        """Pull recent labyrinth session.closed events. eventid + bot_score
        + duration + command_count all live inside parsed_data JSON (the
        ingest processor stores the normalized event dict there)."""
        try:
            from meli.database import get_db
            from meli.database.models import Event
            out: list[dict] = []
            with get_db() as session:
                # Pull more than we need then filter by parsed eventid —
                # we don't have a dedicated column for that and a LIKE on
                # an arbitrary JSON substring isn't reliable cross-DB.
                q = (session.query(Event)
                     .filter(Event.honeypot_service == "labyrinth")
                     .order_by(Event.id.desc())
                     .limit(RECENT_LIMIT * 6))
                for ev in q:
                    try:
                        parsed = json.loads(ev.parsed_data) if ev.parsed_data else {}
                    except Exception:
                        parsed = {}
                    if parsed.get("eventid") != "cowrie.session.closed":
                        continue
                    out.append({
                        "session_id": ev.session_id,
                        "src_ip": ev.source_ip,
                        "protocol": ev.protocol or parsed.get("protocol") or "telnet",
                        "dst_port": ev.destination_port,
                        "timestamp": ev.timestamp,
                        "duration": float(parsed.get("duration", 0.0) or 0.0),
                        "command_count": int(parsed.get("command_count", 0) or 0),
                        "bot_score": parsed.get("bot_score"),
                        "bot_confidence": parsed.get("bot_confidence"),
                    })
                    if len(out) >= RECENT_LIMIT:
                        break
            return out
        except Exception as e:
            log.debug("labyrinth recent fetch failed", error=str(e))
            return []

    def _make_recent_row(self, r: dict) -> Gtk.ListBoxRow:
        row = Gtk.ListBoxRow()
        row.set_selectable(False)
        row.set_activatable(False)
        box = Gtk.Box(spacing=12)
        box.set_margin_all(10)

        ip = Gtk.Label(label=str(r.get("src_ip", "—")))
        ip.add_css_class("monospace")
        ip.set_xalign(0)
        ip.set_size_request(150, -1)
        box.append(ip)

        proto = Gtk.Label(label=str(r.get("protocol", "—")))
        proto.add_css_class("dim-label")
        proto.set_size_request(60, -1)
        proto.set_xalign(0)
        box.append(proto)

        dur = Gtk.Label(label=_fmt_dur(float(r.get("duration", 0.0))))
        dur.set_size_request(80, -1)
        dur.set_xalign(0)
        box.append(dur)

        cmds = Gtk.Label(label=f"{int(r.get('command_count', 0))} cmds")
        cmds.add_css_class("dim-label")
        cmds.set_size_request(80, -1)
        cmds.set_xalign(0)
        box.append(cmds)

        spacer = Gtk.Box()
        spacer.set_hexpand(True)
        box.append(spacer)

        bot_score = r.get("bot_score")
        if bot_score is not None:
            badge = Gtk.Label(label=f"bot {bot_score}")
            badge.add_css_class(_score_badge_class(int(bot_score)))
            box.append(badge)

        ts_raw = r.get("timestamp")
        ts_str = "—"
        try:
            if hasattr(ts_raw, "timestamp"):
                # datetime object from SQLAlchemy. Assume UTC if naive.
                if ts_raw.tzinfo is None:
                    ts_str = _fmt_ago(ts_raw.replace(tzinfo=timezone.utc).timestamp())
                else:
                    ts_str = _fmt_ago(ts_raw.timestamp())
            elif isinstance(ts_raw, (int, float)):
                ts_str = _fmt_ago(float(ts_raw))
            elif isinstance(ts_raw, str):
                dt = datetime.fromisoformat(ts_raw.replace("Z", "+00:00"))
                ts_str = _fmt_ago(dt.timestamp())
        except Exception:
            pass
        ago = Gtk.Label(label=ts_str)
        ago.add_css_class("dim-label")
        ago.set_size_request(80, -1)
        ago.set_xalign(1)
        box.append(ago)

        row.set_child(box)
        return row

    # ── lifecycle ──────────────────────────────────────────────────────

    def _cancel_timer(self) -> None:
        if self._timer_id is not None:
            try:
                GLib.source_remove(self._timer_id)
            except Exception:
                pass
            self._timer_id = None

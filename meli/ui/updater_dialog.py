"""Updater dialog for Meli — surfaces ``UpdateInfo`` and runs install.

Three states:
  - idle              → "Check for updates" button
  - up-to-date        → "You're on the latest version."
  - update-available  → release notes + Install / Skip this version

While installing, a pulsing progress bar tracks the subprocess and the
tail of ``install.log`` streams into a scrollable text view.

Author: Joseph Sierengowski.
License: MIT.
"""
from __future__ import annotations

import threading
from typing import Optional

import gi

gi.require_version("Gtk", "4.0")
gi.require_version("Adw", "1")

from gi.repository import Adw, GLib, Gtk  # noqa: E402

import structlog

from meli import __version__
from meli import updater as updater_core

log = structlog.get_logger(__name__)


def _fmt_bytes(n: int) -> str:
    nf = float(max(0, n))
    for unit in ("B", "KB", "MB", "GB"):
        if nf < 1024 or unit == "GB":
            return f"{nf:.1f} {unit}" if unit != "B" else f"{int(nf)} B"
        nf /= 1024.0
    return f"{nf:.1f} GB"


class UpdaterDialog(Adw.Window):
    """Modal window that walks the user through a check → install cycle."""

    def __init__(
        self,
        parent: Optional[Gtk.Window] = None,
        *,
        preloaded: Optional[updater_core.CheckResult] = None,
    ) -> None:
        super().__init__()
        self.set_title("Meli updates")
        if parent is not None:
            self.set_transient_for(parent)
            self.set_modal(True)
        self.set_default_size(640, 540)
        self.add_css_class("updater-dialog")

        self._result: Optional[updater_core.CheckResult] = preloaded
        self._install: Optional[updater_core.InstallProcess] = None
        self._poll_source: Optional[int] = None
        self._closed = False
        self.connect("close-request", self._on_close_request)

        header = Adw.HeaderBar()
        toolbar = Adw.ToolbarView()
        toolbar.add_top_bar(header)

        self._toaster = Adw.ToastOverlay()
        self._stack = Gtk.Stack(
            transition_type=Gtk.StackTransitionType.CROSSFADE,
            vexpand=True,
            hexpand=True,
        )
        self._toaster.set_child(self._stack)
        toolbar.set_content(self._toaster)
        self.set_content(toolbar)

        self._build_idle_page()
        self._build_available_page()
        self._build_installing_page()
        self._build_done_page()

        if self._result and self._result.info:
            self._show_available(self._result)
        elif self._result and self._result.error:
            self._stack.set_visible_child_name("idle")
            self._idle_status.set_label(self._result.error)
        else:
            self._stack.set_visible_child_name("idle")

    # ── pages ─────────────────────────────────────────────────────────
    def _build_idle_page(self) -> None:
        box = Gtk.Box(
            orientation=Gtk.Orientation.VERTICAL,
            spacing=18,
            margin_top=36, margin_bottom=36,
            margin_start=36, margin_end=36,
            halign=Gtk.Align.CENTER, valign=Gtk.Align.CENTER,
        )
        title = Gtk.Label(label="Check for updates")
        title.add_css_class("title-2")
        sub = Gtk.Label(
            label=f"You are running Meli {__version__}.",
        )
        sub.add_css_class("dim-label")
        self._idle_status = Gtk.Label(label="")
        self._idle_status.add_css_class("dim-label")
        self._idle_status.set_wrap(True)
        btn = Gtk.Button(label="Check now")
        btn.add_css_class("suggested-action")
        btn.add_css_class("pill")
        btn.connect("clicked", lambda *_: self._kickoff_check())
        for w in (title, sub, self._idle_status, btn):
            box.append(w)
        self._stack.add_named(box, "idle")

    def _build_available_page(self) -> None:
        outer = Gtk.Box(
            orientation=Gtk.Orientation.VERTICAL,
            spacing=12,
            margin_top=20, margin_bottom=20,
            margin_start=24, margin_end=24,
        )
        self._avail_title = Gtk.Label(label="", xalign=0)
        self._avail_title.add_css_class("title-2")
        self._avail_meta = Gtk.Label(label="", xalign=0)
        self._avail_meta.add_css_class("dim-label")

        scroller = Gtk.ScrolledWindow(vexpand=True)
        scroller.set_policy(Gtk.PolicyType.AUTOMATIC, Gtk.PolicyType.AUTOMATIC)
        self._avail_notes = Gtk.TextView(
            editable=False, cursor_visible=False, monospace=False, wrap_mode=Gtk.WrapMode.WORD,
        )
        self._avail_notes.add_css_class("card")
        scroller.set_child(self._avail_notes)

        actions = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=8,
                          halign=Gtk.Align.END)
        skip_btn = Gtk.Button(label="Skip this version")
        skip_btn.connect("clicked", lambda *_: self._on_skip())
        later_btn = Gtk.Button(label="Later")
        later_btn.connect("clicked", lambda *_: self.close())
        install_btn = Gtk.Button(label="Install update")
        install_btn.add_css_class("suggested-action")
        install_btn.connect("clicked", lambda *_: self._begin_install())
        for w in (skip_btn, later_btn, install_btn):
            actions.append(w)

        for w in (self._avail_title, self._avail_meta, scroller, actions):
            outer.append(w)
        self._stack.add_named(outer, "available")

    def _build_installing_page(self) -> None:
        outer = Gtk.Box(
            orientation=Gtk.Orientation.VERTICAL,
            spacing=12,
            margin_top=24, margin_bottom=24,
            margin_start=24, margin_end=24,
        )
        self._inst_title = Gtk.Label(label="Installing update…", xalign=0)
        self._inst_title.add_css_class("title-2")
        self._inst_message = Gtk.Label(label="", xalign=0)
        self._inst_message.add_css_class("dim-label")
        self._progress = Gtk.ProgressBar(show_text=True, text="Starting…")
        self._progress.set_pulse_step(0.08)

        scroller = Gtk.ScrolledWindow(vexpand=True)
        scroller.set_policy(Gtk.PolicyType.AUTOMATIC, Gtk.PolicyType.AUTOMATIC)
        self._log_view = Gtk.TextView(
            editable=False, cursor_visible=False, monospace=True,
            wrap_mode=Gtk.WrapMode.WORD_CHAR,
        )
        self._log_view.add_css_class("card")
        scroller.set_child(self._log_view)

        actions = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=8,
                          halign=Gtk.Align.END)
        self._cancel_btn = Gtk.Button(label="Cancel")
        self._cancel_btn.connect("clicked", lambda *_: self._cancel_install())
        actions.append(self._cancel_btn)

        for w in (self._inst_title, self._inst_message, self._progress,
                  scroller, actions):
            outer.append(w)
        self._stack.add_named(outer, "installing")

    def _build_done_page(self) -> None:
        box = Gtk.Box(
            orientation=Gtk.Orientation.VERTICAL,
            spacing=18,
            margin_top=36, margin_bottom=36,
            margin_start=36, margin_end=36,
            halign=Gtk.Align.CENTER, valign=Gtk.Align.CENTER,
        )
        self._done_title = Gtk.Label(label="Update installed")
        self._done_title.add_css_class("title-2")
        self._done_sub = Gtk.Label(label="")
        self._done_sub.add_css_class("dim-label")
        self._done_sub.set_wrap(True)
        close_btn = Gtk.Button(label="Close")
        close_btn.add_css_class("suggested-action")
        close_btn.add_css_class("pill")
        close_btn.connect("clicked", lambda *_: self.close())
        for w in (self._done_title, self._done_sub, close_btn):
            box.append(w)
        self._stack.add_named(box, "done")

    # ── check flow ────────────────────────────────────────────────────
    def _kickoff_check(self) -> None:
        self._idle_status.set_label("Checking GitHub Releases…")

        def worker() -> None:
            result = updater_core.check_for_update()
            GLib.idle_add(self._on_check_done, result)

        threading.Thread(target=worker, daemon=True).start()

    def _on_check_done(self, result: updater_core.CheckResult) -> bool:
        if self._closed:
            return False
        self._result = result
        if result.info:
            self._show_available(result)
        elif result.error:
            self._idle_status.set_label(f"Could not check: {result.error}")
        else:
            self._idle_status.set_label(
                f"You're on the latest version (Meli {__version__})."
            )
        return False

    def _show_available(self, result: updater_core.CheckResult) -> None:
        info = result.info
        assert info is not None
        self._avail_title.set_label(f"Meli {info.version} is available")
        meta_parts = [f"Current: {__version__}"]
        if info.asset_size:
            meta_parts.append(f"Download: {_fmt_bytes(info.asset_size)}")
        if info.prerelease:
            meta_parts.append("pre-release")
        if info.published_at:
            meta_parts.append(info.published_at.split("T")[0])
        self._avail_meta.set_label(" · ".join(meta_parts))
        buf = self._avail_notes.get_buffer()
        buf.set_text(info.notes or "(no release notes)")
        self._stack.set_visible_child_name("available")

    # ── install flow ──────────────────────────────────────────────────
    def _begin_install(self) -> None:
        if not self._result or not self._result.info:
            return
        info = self._result.info
        self._inst_title.set_label(f"Installing Meli {info.version}…")
        self._inst_message.set_label("Preparing download…")
        self._stack.set_visible_child_name("installing")

        def progress_cb(p: updater_core._Progress) -> None:
            def update() -> bool:
                if self._closed:
                    return False
                self._inst_message.set_label(p.message or p.stage)
                if p.stage == "downloading" and p.bytes_total > 0:
                    frac = min(1.0, p.bytes_done / p.bytes_total)
                    self._progress.set_fraction(frac)
                    self._progress.set_text(
                        f"{_fmt_bytes(p.bytes_done)} / {_fmt_bytes(p.bytes_total)}"
                    )
                else:
                    self._progress.pulse()
                    self._progress.set_text(p.stage.title())
                return False
            GLib.idle_add(update)

        def worker() -> None:
            try:
                handle = updater_core.download_and_install(
                    info, progress_cb=progress_cb,
                )
            except Exception as e:
                log.exception("update install failed to start")
                GLib.idle_add(self._on_install_error, str(e))
                return
            GLib.idle_add(self._on_install_started, handle)

        threading.Thread(target=worker, daemon=True).start()

    def _on_install_started(self, handle: updater_core.InstallProcess) -> bool:
        if self._closed:
            handle.cancel()
            return False
        self._install = handle
        self._poll_source = GLib.timeout_add(500, self._poll_install)
        return False

    def _poll_install(self) -> bool:
        if self._closed or self._install is None:
            return False
        rc = self._install.poll()
        # Stream the install log tail.
        try:
            tail = self._install.tail(8192)
            buf = self._log_view.get_buffer()
            if tail and buf.get_char_count() != len(tail):
                buf.set_text(tail)
                end_iter = buf.get_end_iter()
                self._log_view.scroll_to_iter(end_iter, 0.0, False, 0.0, 0.0)
        except Exception:
            pass
        if rc is None:
            self._progress.pulse()
            return True
        self._on_install_finished(rc)
        return False

    def _on_install_finished(self, rc: int) -> None:
        info = self._result.info if self._result else None
        ver = info.version if info else "?"
        if rc == 0:
            self._done_title.set_label(f"Meli {ver} installed")
            self._done_sub.set_label(
                "Restart Meli (and run "
                "`systemctl --user restart meli.service meli-ingest.service`) "
                "to pick up the new version."
            )
        else:
            self._done_title.set_label("Install failed")
            tail = self._install.tail(2048) if self._install else ""
            self._done_sub.set_label(
                f"install.sh exited with code {rc}.\n\n"
                f"Last lines:\n{tail[-1200:]}"
            )
        self._stack.set_visible_child_name("done")

    def _on_install_error(self, msg: str) -> bool:
        self._done_title.set_label("Install failed")
        self._done_sub.set_label(msg)
        self._stack.set_visible_child_name("done")
        return False

    def _cancel_install(self) -> None:
        if self._install is not None:
            self._install.cancel()
        self.close()

    # ── skip / close ──────────────────────────────────────────────────
    def _on_skip(self) -> None:
        if self._result and self._result.info:
            updater_core.skip_version(self._result.info.version)
            self._toaster.add_toast(
                Adw.Toast(
                    title=f"Skipped Meli {self._result.info.version}",
                    timeout=2,
                )
            )
        GLib.timeout_add(700, lambda: (self.close(), False)[1])

    def _on_close_request(self, *_a) -> bool:
        self._closed = True
        if self._poll_source is not None:
            try:
                GLib.source_remove(self._poll_source)
            except Exception:
                pass
            self._poll_source = None
        if self._install is not None:
            self._install.cancel()
        return False  # allow close

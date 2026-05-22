"""HiveHeader — universal top header bar shared across every view.

Renders the 'M' brand badge + page title + status pill + live UPTIME /
INGEST / DB stats + JS-style avatar. Drop-in replacement for
``Adw.HeaderBar`` so every view feels like one cohesive command
center instead of a generic Adwaita window.

Layout (left → right):

    [M] <Title>   [● STATUS PILL]                UPTIME  INGEST  DB  [JS]  <actions>

The stats panel auto-refreshes every 5s. INGEST is computed from a
rolling 60-second window of ``event_bus`` ``event.ingested`` signals,
so it reflects actual live throughput. UPTIME is monotonic since
process start. DB is the on-disk size of ``meli.db``.
"""
from __future__ import annotations

import time
from collections import deque
from pathlib import Path

import gi
gi.require_version("Gtk", "4.0")
from gi.repository import Gtk, GLib

from meli import event_bus

# ── Module-level state (process-wide) ────────────────────────────────
_APP_START = time.monotonic()
_INGEST_WINDOW: deque[float] = deque(maxlen=4000)


def _record_ingest(_topic, _payload) -> None:
    _INGEST_WINDOW.append(time.monotonic())


# Subscribe once at import time so every HiveHeader instance shares
# the same rolling counter (ingest rate is a process-wide metric).
event_bus.subscribe("event.ingested", _record_ingest)


def _format_uptime() -> str:
    secs = int(time.monotonic() - _APP_START)
    d, secs = divmod(secs, 86400)
    h, _ = divmod(secs, 3600)
    return f"{d}d {h:02d}h"


def _ingest_per_min() -> int:
    cutoff = time.monotonic() - 60
    while _INGEST_WINDOW and _INGEST_WINDOW[0] < cutoff:
        _INGEST_WINDOW.popleft()
    return len(_INGEST_WINDOW)


def _db_size() -> str:
    try:
        from meli.config import get_config
        cfg = get_config()
        # config.data_dir is a @property returning Path
        data_dir = cfg.data_dir if hasattr(cfg, "data_dir") else None
        if data_dir is None:
            return "—"
        p = Path(data_dir) / "meli.db"
        if not p.exists():
            return "—"
        b = p.stat().st_size
        if b < 1024:
            return f"{b}B"
        if b < 1024 * 1024:
            return f"{b/1024:.0f}KB"
        if b < 1024 * 1024 * 1024:
            return f"{b/(1024*1024):.0f}MB"
        return f"{b/(1024*1024*1024):.1f}GB"
    except Exception:
        return "—"


def _user_initials() -> str:
    try:
        import getpass
        u = (getpass.getuser() or "").strip()
        parts = [p for p in u.replace("_", " ").replace("-", " ").split() if p]
        if not parts:
            return "ME"
        if len(parts) == 1:
            return parts[0][:2].upper()
        return (parts[0][0] + parts[1][0]).upper()
    except Exception:
        return "ME"


class HiveHeader(Gtk.Box):
    """Universal hive-styled header bar.

    Usage::

        header = HiveHeader(title="Dashboard",
                            status_label="OPERATIONAL",
                            status_kind="operational")
        header.pack_end(refresh_btn)
        # Then append `header` as the first child of your view's
        # Gtk.Box(VERTICAL), in place of Adw.HeaderBar().
    """

    def __init__(self,
                 *,
                 title: str,
                 status_label: str = "OPERATIONAL",
                 status_kind: str = "operational") -> None:
        super().__init__(orientation=Gtk.Orientation.HORIZONTAL, spacing=14)
        self.add_css_class("hive-header")

        # Brand badge — small amber 'M' square that matches the sidebar
        brand = Gtk.Label(label="M")
        brand.add_css_class("rank-badge")
        brand.set_size_request(28, 28)
        self.append(brand)

        # Page title
        title_lbl = Gtk.Label(label=title)
        title_lbl.add_css_class("hive-title")
        title_lbl.set_xalign(0)
        self.append(title_lbl)

        # Status pill ( ● STATUS )
        pill = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=5)
        pill.add_css_class("hive-pill")
        pill.add_css_class(f"hive-pill-{status_kind}")
        pill.append(Gtk.Label(label="●"))
        pill.append(Gtk.Label(label=status_label))
        self.append(pill)
        self._pill = pill
        self._pill_kind = status_kind

        # Flex spacer
        spacer = Gtk.Box()
        spacer.set_hexpand(True)
        self.append(spacer)

        # Stats: UPTIME / INGEST / DB
        self._stats = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=14)
        self._uptime_v = self._stat("UPTIME", _format_uptime())
        self._ingest_v = self._stat("INGEST", f"{_ingest_per_min()}/min")
        self._db_v = self._stat("DB", _db_size())
        self.append(self._stats)

        # Avatar
        avatar = Gtk.Label(label=_user_initials())
        avatar.add_css_class("hive-avatar")
        avatar.set_size_request(30, 30)
        self.append(avatar)

        # Tail slot for action buttons (refresh, export, etc.)
        self._tail = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=6)
        self.append(self._tail)

        # Live tick
        self._tick_id = GLib.timeout_add_seconds(5, self._tick)
        self.connect("destroy", self._on_destroy)

    # ── Public API ───────────────────────────────────────────────────

    def pack_end(self, widget: Gtk.Widget) -> None:
        """Append a widget after the avatar (refresh buttons, etc.)."""
        self._tail.append(widget)

    def set_status(self, label: str, kind: str = "operational") -> None:
        """Update the status pill ('LIVE', 'SNIFFING', 'CONFIGURED', ...)."""
        for old in ("operational", "online", "live", "honey", "configured",
                    "guided", "sniffing", "warn", "critical"):
            self._pill.remove_css_class(f"hive-pill-{old}")
        self._pill.add_css_class(f"hive-pill-{kind}")
        # Replace the text label (last child of the pill box)
        child = self._pill.get_last_child()
        if isinstance(child, Gtk.Label):
            child.set_text(label)

    # ── Internals ────────────────────────────────────────────────────

    def _stat(self, label: str, value: str) -> Gtk.Label:
        box = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=5)
        lbl = Gtk.Label(label=label)
        lbl.add_css_class("hive-stat-label")
        val = Gtk.Label(label=value)
        val.add_css_class("hive-stat-value")
        box.append(lbl)
        box.append(val)
        self._stats.append(box)
        return val

    def _tick(self) -> bool:
        try:
            self._uptime_v.set_text(_format_uptime())
            self._ingest_v.set_text(f"{_ingest_per_min()}/min")
            self._db_v.set_text(_db_size())
        except Exception:
            pass
        return True

    def _on_destroy(self, *_a) -> None:
        try:
            GLib.source_remove(self._tick_id)
        except Exception:
            pass

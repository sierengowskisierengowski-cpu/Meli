"""
Meli — Honeypot Command Center
Author: Joseph Sierengowski
License: MIT
"""

__version__ = "2.7.3"
__author__ = "Joseph Sierengowski"
__license__ = "MIT"
__description__ = "Real-time threat intelligence dashboard for honeypot infrastructure"

# ── GTK4 compatibility shim ──────────────────────────────────────────
# Gtk.Widget.set_margin_all() existed in GTK3 / pygi but was removed in
# GTK4. Rather than rewrite ~30 call sites across the UI, we restore
# the convenience method by monkey-patching the base Widget class so
# every subclass (Button, Box, Label, ListView, …) picks it up.
try:
    import gi as _gi
    _gi.require_version("Gtk", "4.0")
    from gi.repository import Gtk as _Gtk
    if not hasattr(_Gtk.Widget, "set_margin_all"):
        def _set_margin_all(self, n: int) -> None:
            self.set_margin_top(n)
            self.set_margin_bottom(n)
            self.set_margin_start(n)
            self.set_margin_end(n)
        _Gtk.Widget.set_margin_all = _set_margin_all  # type: ignore[attr-defined]
except Exception:
    # Non-GUI contexts (tests, CLI tools) won't have GTK available.
    pass

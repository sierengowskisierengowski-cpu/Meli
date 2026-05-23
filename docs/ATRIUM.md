# Atrium — Kiosk / Wall-Monitor Mode

**v2.2.2**

Atrium is an opt-in fullscreen visualization mode designed for a wall-mounted display — a Raspberry Pi 5 with an HDMI monitor works well. It shows a live, ambient view of honeypot activity with no interaction required.

---

## Overview

Atrium is lazily imported at runtime. If you never invoke it, it is never loaded and adds zero overhead to normal Meli operation.

It is deliberately separate from the main window: opening or closing Atrium does not affect the ingest daemon, alert routing, enrichment, or any of the 16 main views.

---

## Launching Atrium

Three equivalent launch paths:

1. **Sidebar button** — click the monitor icon in the main window's sidebar
2. **F12 keyboard shortcut** — press F12 from anywhere in the main window
3. **Command-line flag** — start Meli directly in kiosk mode:
   ```bash
   meli --kiosk
   ```

---

## Display Layout

Target resolution: 1920×1080. Scales to any size.

```
┌─────────────────────────────────────────────────────────────────────┐
│  MELI — ACTIVE DECEPTION PLATFORM          [UTC time]  [session ct] │
├───────────────────────────────┬─────────────────────────────────────┤
│                               │                                     │
│      RADAR SCOPE              │           AMPHORA (3×)             │
│  animated sweep, blips        │   Cairo honey-pot fills & drips    │
│  for active sessions          │                                     │
│                               │                                     │
├───────────────────────────────┴─────────────────────────────────────┤
│   TERMINAL STREAM                                                    │
│   scrolling: CONNECT / AUTH / CMD / CANARY_TRIP events              │
├─────────────────────────────────────────────────────────────────────┤
│   24-HOUR HEATMAP  ████████░░░░████████████░░░░░░░░░░░░░░          │
│   15-minute bins, attack intensity                                   │
└─────────────────────────────────────────────────────────────────────┘
```

### Panels

| Panel | Description |
|-------|-------------|
| **Radar scope** | Animated sweep (30 fps). Each active session appears as a blip at a position derived from the session ID hash. New connections produce a brief ring flash. |
| **Amphora (3×)** | The same Cairo-drawn honey-pot widget as the dashboard, rendered at 3× size. Fills as the event count grows, pulses on new events, drips when overflowing. |
| **Terminal stream** | Scrolling feed of Labyrinth and external honeypot events. Shows connection, authentication, command, and canary trip events. Color-coded by severity. |
| **24-hour heatmap** | Horizontal bar chart in 15-minute bins. Intensity shown as block fill. Scrolls to always show the current time at the right edge. |
| **Clock bar** | UTC timestamp, live/idle status indicator, current session count (Labyrinth + ingest). |

### Visual effects

- **Aurora gradient background** — soft shifting colors at 5 fps. Synthesized in-process; no external image assets.
- **CRT scanline overlay** — subtle horizontal scanlines drawn over the entire surface for aesthetics.
- **Canary-trip flash** — when a canary token is triggered, the entire screen briefly flashes red with a `⚠ CANARY TRIP` overlay.
- **Audio cues** — short sine-wave tones synthesized from stdlib `wave`/`math` on first launch (written to `~/.local/share/meli/atrium/sounds/`). No binary audio files are bundled in the repository. Plays via `paplay`/`aplay` if available.

---

## Closing Atrium

Any of the following:
- **Esc**
- **F11**
- **Ctrl+W**
- Click the top-right corner (invisible 32×32 px hit area)

---

## Intended Use Case

Mount a Raspberry Pi 5 with a monitor in your server room, NOC, or home office. Run `meli --kiosk` and walk away. Atrium shows you at a glance whether your honeypot infrastructure is quiet, active, or under siege, without needing to interact with a mouse or keyboard.

Because the ingest daemon runs as a systemd service (`meli-ingest`), honeypot capture continues regardless of whether the Atrium window is open.

Recommended Pi 5 setup:
```bash
# In /home/pi/.config/autostart/meli-kiosk.desktop:
[Desktop Entry]
Type=Application
Exec=meli --kiosk
X-GNOME-Autostart-enabled=true
```

---

## Technical Notes

- Atrium is in `meli/ui/atrium.py` (or `meli/meli/atrium.py` in the package layout) and is imported only when the kiosk mode is first invoked.
- The aurora, radar, and heatmap update timers are removed on scene teardown to prevent GLib timer leaks.
- The `_bg` background-drawing reference is properly cleared on shutdown (fixed in v2.2.2).
- All drawing is done via Cairo `DrawingArea` callbacks; no external rendering library is required.
- Atrium reads the same SQLite database as the main UI, running queries on a background thread with `GLib.idle_add()` for results.

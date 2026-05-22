# Changelog

All notable changes to Meli are documented here.

## [2.6.1] — 2026-05-22

### Fixed — install.sh was silently loading the wrong code

Root cause of the v2.6.0 "stale copy" bug: the launcher
`/usr/local/bin/meli` was written as:

```sh
exec /opt/meli/venv/bin/python -m meli "$@"
```

with no `PYTHONPATH` and no `cd`. `python -m meli` therefore searched
`sys.path`, which on a fresh venv with `--system-site-packages` does
NOT contain `/opt/meli/app` — but it DOES contain the current working
directory. If the user ran `meli` from `~/meli-fresh` (which has a
`meli/` subdir), Python loaded the source tree instead of the
installed copy at `/opt/meli/app/meli`. The rsync to `/opt/meli/app`
was effectively dead code.

Combined with stale `__pycache__/*.pyc` files in the source tree,
this meant code edits could appear to "not take" even after
`git pull && sudo ./install.sh`.

Fixes in `install.sh`:

- **Launcher now pins `PYTHONPATH=/opt/meli/app`** so `meli` loads
  the installed package from any cwd, never from a sibling `meli/`
  directory.
- **Phase 4 wipes `__pycache__` and `*.pyc`** from both the source
  tree (`$APP_DIR`) and the install dir (`/opt/meli/app`) before
  copying, so yesterday's bytecode can't shadow today's source.
- **Phase 4 removes `/opt/meli/app/meli/` outright** before rsync so
  files deleted in a new release don't linger as zombies.
- **Phase 4 prints the installed `__version__`** from
  `/opt/meli/app/meli/__init__.py` so you can confirm at a glance
  which release actually landed.
- `MELI_VERSION` banner string updated to track the real release
  (was hardcoded at `1.0.0` since the original install.sh).

No code changes to the splash or lock screen — the v2.6.0 visuals
were already correct, they just weren't being loaded.

## [2.6.0] — 2026-05-22

### Changed — Splash screen v2: real gooey vertical drips

- **`meli/ui/splash_screen.py`** rewritten again after user feedback
  that the v2.5.0 drips read as stiff angled "matchsticks" rather
  than honey actually dripping. New animation:
    - 0.0–0.6s   Dark hold.
    - 0.4–1.6s   SPLAT: a wide irregular 18-lobe honey blob slams
                 into the top of the screen and spreads across ~72%
                 of the window width and the top third of the
                 window height, with a brief settling wobble.
    - 1.4–5.8s   Six **vertical** gooey strands ooze straight down
                 from the splat underside. Each strand is drawn as
                 a single closed Cairo path: widest at the
                 attachment, narrowing through the middle, swelling
                 into a heavy teardrop bulb at the tip. Per-strand
                 jitter in length, thickness, sway, and start time
                 keeps the cascade organic. Vertical honey gradient
                 fill + halo + rim highlight + specular sheen on
                 each strand.
    - 5.0–6.8s   MELI wordmark fades in centered below the drip
                 field (no longer anchored to individual drip tips —
                 letters and drips are independent now).
    - 6.5–7.4s   Subtitle fades in.
    - 7.4–8.4s   Hold; 8.4–9.0s fade to black.

### Changed — Lock screen: honeycomb backdrop instead of flat black

- **`meli/ui/lock_screen.py`** rewritten. The veil is no longer a
  solid `#0b0b10` rectangle. A Cairo `_HoneycombBackdrop`
  `DrawingArea` now fills the entire window with a tiled hexagon
  grid: dark-amber outlines on the hive-black/comb-panel gradient,
  with cells near the geometric center filled with a faint amber
  wash that **breathes** on a 4.2s sine pulse. A radial amber
  bloom sits behind the auth card and an edge vignette focuses
  the eye toward the center.
- The auth form moves into a translucent comb-panel card with a
  thin amber border and soft shadow, so it reads cleanly against
  the honeycomb without losing the theme.
- 12 fps redraw cadence on the backdrop — gentle pulse, negligible
  CPU.

## [2.5.0] — 2026-05-22

### Changed — Splash screen redesigned (fullscreen honey splat)

- **`meli/ui/splash_screen.py`** rewritten end-to-end. Animation now
  scales to fill the entire main window (previously a fixed
  640x420 canvas was letterboxed inside the window with black bars).
  Total duration extended from 6.5s to 9.0s for a less rushed feel.

  New phase sequence:
    - 0.0–0.8s   Dark hold (anticipation)
    - 0.6–1.4s   SPLAT: a huge irregular honey blob slams onto the top
                 of the screen, splatter droplets radiate outward; the
                 splat sound lands on the impact frame.
    - 1.0–4.5s   Four thick honey ropes drip down from the splat
                 underside, lengthening with gravity, accumulating
                 heavy teardrop bulbs at their tips.
    - 4.0–6.0s   MELI wordmark materializes directly beneath the four
                 drip tips (the drips "wrote" the name).
    - 6.0–7.0s   Subtitle ("honey trap command center") fades in.
    - 7.0–8.2s   Hold so the user can read it.
    - 8.2–9.0s   Fade to black, emit `splash-finished`.

  Visual primitives: 14-lobe Bezier splat ring with deterministic
  radial jitter and gooey wobble; radial vignette to focus the eye;
  22 splatter droplets with gravity-arc trajectories; 3-segment
  Bezier drip ropes with halo + gradient body + highlight stripe +
  pear-shaped teardrop bulb at the tip; wordmark scales with window
  (min 48px, up to 13% of `min(w, h)`) with amber glow + pale sheen.

  Contract unchanged: same `Gtk.Box` widget, same `splash-finished`
  GObject signal, same `splash.enabled` / `splash.sound_enabled`
  config knobs.

### Added — Multi-resolution PNG icons for desktop integration

- **`assets/icons/meli-{16,32,48,64,128,256,512}.png`** rendered from
  `meli.svg` at every size `install.sh` looks for. Previously only
  the SVG existed, so on most desktops the icon copy step in
  `install.sh` Phase 5 silently skipped every size, leaving the
  application launcher and taskbar showing a generic placeholder.
  With the PNGs in place, `install.sh` now installs them into
  `/usr/share/icons/hicolor/{size}x{size}/apps/meli.png`, the
  `meli.desktop` launcher picks them up automatically via
  `Icon=meli`, and `gtk-update-icon-cache` re-indexes them so the
  honey-pot icon appears in app menus, taskbars, and on the desktop.

## [2.4.0] — 2026-05-22

### Added — In-app auto-updater

- **`meli/updater.py`** — stdlib-only (urllib) check against the GitHub
  Releases feed for `sierengowskisierengowski-cpu/Meli`. Override via
  `updates.feed_url` for self-hosted mirrors. Picks the first non-draft
  release matching the channel (stable or include-prereleases). Prefers
  a `meli-X.Y.Z.tar.gz` release asset; falls back to GitHub's
  auto-generated source tarball (`tarball_url`) so the updater works
  even before any custom assets are uploaded. Optional sibling
  `.sha256` verification. Runs `install.sh` under `pkexec` (or
  `--user` when `updates.user_scope` is true). Pre-release-aware semver
  comparator (`is_newer`). `should_auto_check()` throttles checks by
  `check_interval_hours` (default 24h). `skip_version()` records a
  user-dismissed version so the toast doesn't re-prompt.

- **`meli/ui/updater_dialog.py`** — `Adw.Window` with four states
  (idle / available / installing / done). Worker thread does HTTP +
  tarball download + extraction + install spawn; main loop polls the
  subprocess every 500ms via `GLib.timeout_add` and pulses an
  `Adw.ProgressBar`. The install log tail streams into a scrollable
  text view. Closing the dialog cancels the install
  (`InstallProcess.cancel()`). Safe extraction refuses path-traversing
  tar entries.

- **App startup**: after the lock screen clears, a background thread
  hits the releases feed (throttled). If a newer non-skipped release
  exists, an `Adw.Toast` surfaces on the main window with an
  **"Update…"** button → opens the dialog with the result preloaded.

- **`GAction app.check-for-updates`** registered with `Ctrl+U` accel
  so the menu / palette / shortcut can trigger the dialog directly.

- **Config keys** under `updates.*` in `~/.config/meli/config.yaml`:
  `auto_check`, `check_interval_hours`, `include_prereleases`,
  `user_scope`, `feed_url`, plus read-only `last_check_at`,
  `last_seen_version`, `skipped_version`.

### Operator notes

- Release assets are picked by filename: ship `meli-2.4.0.tar.gz` (and
  optionally `meli-2.4.0.tar.gz.sha256`) on the GitHub release for
  fastest, smallest updates. Without a custom asset the updater
  downloads the full GitHub source archive — works fine, just larger.
- The installer is invoked with `pkexec` so the user authenticates
  once per update; the venv at `/opt/meli` is rebuilt cleanly.
- After install the dialog reminds the operator to restart the
  `meli.service` + `meli-ingest.service` user units to pick up the
  new code.

## [2.3.0] — 2026-05-22

### Added — Authorization & Intended Use

- **New mandatory wizard step: Authorization** (`meli/ui/setup_wizard.py`).
  Inserted between **Welcome** and **Password** so the operator must
  explicitly acknowledge `DISCLAIMER.md` before any data is ingested.
  The Next button (relabelled **I Agree →**) stays disabled until the
  checkbox is ticked. Acknowledgments are timestamped, recorded with
  the local user/host, and persisted to `~/.config/meli/eula.json`
  (mode 0600) by the new `meli.eula` module. Re-running the wizard
  pre-ticks the box and shows the prior acceptance timestamp.

- **Persistent authorization notice on the Labyrinth Atrium kiosk**
  (`meli/ui/atrium.py`). The `ClockBar` grew 48→66 px and now
  permanently renders **"⚠ Monitoring authorized infrastructure
  only — see DISCLAIMER.md"** beneath the title in a dim-white 11 px
  face. Designed to be readable from across a room so anyone walking
  past a wall-mounted Pi kiosk sees the operating context.

- **`meli.eula` module** (new, stdlib-only). API: `is_accepted()`,
  `accept(version)`, `get_record()`. Honors `MELI_CONFIG_DIR` for
  packaged/sandboxed installs.

### Changed — Visual polish

- **Honeycomb pattern tiled across the main window**
  (`meli/resources/css/style.css`). The same hex-cell SVG used on the
  splash now repeats over `window.meli-window` at 3.5% opacity so the
  hive motif reads at any zoom level. Zero perceptible perf cost —
  it's a single inline 56×48 data-URI SVG.

- **Wizard window size** bumped 600×500 → 640×560 to give the
  Authorization step's longer copy room to breathe without scrolling.

### Notes

- No DB migration required.
- `meli.auth` (master password + TOTP) is unchanged — `meli.eula` is
  intentionally a separate module: acceptance is a one-time
  legal/operational acknowledgment, not an authentication factor.
- Existing installs: the wizard re-runs only on first launch; for
  already-configured installs you can record acknowledgment manually
  by writing `~/.config/meli/eula.json` or simply re-running the
  wizard from Settings.

---

## [1.0.0] — 2025-05-20

### Initial Release

**Core**
- GTK4 + libadwaita native desktop application
- Master password authentication with Argon2id KDF
- TOTP 2FA (Google Authenticator, Authy compatible)
- Progressive lockout: 60s → 5min → app restart required
- Ctrl+L lock / configurable auto-lock idle timeout
- First-run setup wizard (7 steps)

**Event Ingestion**
- MQTT consumer (paho-mqtt 2.x, `meli/events/ingest` topic)
- HTTP POST ingest server on port 17654
- Per-honeypot ingest tokens (stored encrypted in DB)
- Runs as `meli-ingest.service` systemd user service

**Honeypot Parsers (7)**
- Cowrie SSH/Telnet — all event IDs (login, command, file_download, etc.)
- Heralding — multi-service credential capture
- Dionaea — malware capture (SMB, FTP, MySQL, SIP, TFTP)
- HTTP Honeypot — Snare/Tanner + custom nginx log format
- Glastopf — web application honeypot
- Mailoney — SMTP probe honeypot
- Generic JSON — canonical Meli format + heuristic fallback

**Classification Engine**
- 16 built-in rules (INFO through CRITICAL)
- YAML rule definition with conditions (eq, in, regex, exists, gte, lte)
- User-defined rules via the Alert Rules UI
- Context injection: attacker_event_count for threshold rules

**IP Enrichment (6 services)**
- MaxMind GeoLite2 — offline city + ASN (no API limit)
- AbuseIPDB — abuse confidence score
- GreyNoise — noise/malicious/benign classification
- VirusTotal — IP + file hash reputation
- Shodan — open ports, CVEs, banners
- IPInfo — ASN, org, VPN/proxy/Tor detection
- 24h result caching in SQLite (configurable TTL)

**Alert System**
- 7 notification channels: Desktop, Discord, Slack, Telegram, SMTP Email, HTTP Webhook, Sound
- Per-rule cooldown, active hours, severity threshold
- Alert sound per severity level (PipeWire/ALSA via paplay/aplay)
- Full alert history with acknowledge

**Reports**
- Types: daily, weekly, monthly, custom
- Formats: PDF (ReportLab), Markdown, JSON, CSV
- Jinja2 report templates

**Database**
- SQLite via SQLAlchemy 2.x
- WAL journal mode, foreign keys enabled
- 12 tables: events, attackers, credentials, commands, payloads, honeypots, alert_rules, alerts, api_keys, enrichment_cache, reports, audit_log
- Online backup via SQLite backup API
- VACUUM support

**GTK4 Views (14)**
1. Dashboard — stat cards, severity breakdown, top attackers, recent events, honeypot health
2. Live Feed — real-time MQTT event stream, pause/filter/export
3. Geographic Map — world map with Leaflet.js (WebKitGTK) + country table
4. Attackers — sortable IP table with enrichment profile drawer
5. Credentials — username/password pairs with wordlist export
6. Commands — post-auth command analysis with intent classification
7. Payloads — captured malware with VirusTotal hash lookup
8. Service Stats — per-honeypot breakdown with health status
9. Timeline — attack volume bars with configurable periods (1h/24h/7d/30d/90d)
10. IP Reputation — single-IP lookup across all enrichment services
11. Botnet Detection — coordinated attack cluster analysis
12. Alert Rules — CRUD editor + alert history with acknowledge
13. Reports — generate and browse reports
14. Settings — full configuration panel (categories sidebar)

**Security**
- Fernet encryption (AES-128-CBC) for API keys and sensitive data at rest
- bcrypt for master password hashing
- Database and config files: chmod 600 / 700
- API keys never logged or stored in config file plaintext

**Packaging**
- `install.sh` — Arch/Ubuntu/Fedora support, phased install
- `uninstall.sh` — preserves user data
- `PKGBUILD` — Arch Linux package
- `meli.desktop` + SVG icon
- `meli-ingest.service` — systemd user service

## [Unreleased / Roadmap]

### v1.1
- Log file watcher (inotify-based, no MQTT required)
- Network PCAP analysis mode
- Additional parsers: T-Pot, HoneyTrap, OpenCanary
- CIDR and geofence block lists

### v1.2
- YubiKey hardware 2FA
- PostgreSQL backend option
- Report scheduling UI
- Email delivery on scheduled reports

### v1.3
- Threat feed subscriptions (auto-update IoC lists)
- STIX 2.1 / TAXII 2.1 export
- Correlation rules (link events across honeypots)
- Heat map calendar view

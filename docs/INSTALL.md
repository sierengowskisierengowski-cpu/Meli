# Meli Installation Guide

**v2.2.2**

## Supported Distributions

| Distribution | Status |
|-------------|--------|
| Arch Linux / EndeavourOS / Manjaro | Fully supported |
| Pop!_OS 24.04 | Fully supported |
| Ubuntu 24.04 LTS | Fully supported |
| Fedora 40+ | Supported |
| Debian 12+ | Should work (manual dependency names) |
| NixOS | PKGBUILD not applicable — use flake (future) |

## Prerequisites

- GTK4 + libadwaita installed (handled by `install.sh`)
- Mosquitto MQTT broker (handled by `install.sh`)
- Python 3.11+
- Internet access for first-time pip install

## Step-by-step

### 1. Clone the repository

```bash
git clone https://github.com/sierengowskisierengowski-cpu/Meli
cd Meli
```

### 2. Install system dependencies

Run as your normal user (will prompt for sudo password):

```bash
sudo ./install.sh --phase 1
```

This installs:
- `gtk4` + `libadwaita` + `python3-gi` (GTK4 Python bindings)
- `mosquitto` (MQTT broker, auto-enabled as a system service)
- `python3-dev`, `cairo-dev`, `pkg-config` (build deps for PyGObject)
- System audio libraries for alert sounds

### 3. Run the full installer

```bash
./install.sh
```

This runs 9 phases:
1. System packages (if not already installed)
2. Python virtual environment (`/opt/meli/venv` with `--system-site-packages`)
3. Python dependencies (`pip install -r requirements.txt`)
4. Application files (copies the `meli/` package into the venv)
5. Desktop integration (`meli.desktop`, SVG icon)
6. systemd user service (`meli-ingest.service`)
7. Mosquitto configuration (creates `meli.conf` in `/etc/mosquitto/conf.d/`)
8. User data directories (`~/.local/share/meli/`, `~/.config/meli/`)
9. Database initialization (creates schema on first run)

Also installs the `meli` script to `/usr/local/bin/meli`.

### 4. Launch Meli

```bash
meli
```

The first-run setup wizard will appear automatically. Follow it to:
1. Set your master password (minimum 12 characters)
2. Optionally enable TOTP 2FA
3. Add your first honeypot source
4. Enter API keys for enrichment services (optional)
5. Download GeoLite2 databases (requires free MaxMind account)

### 5. Start the ingest daemon

The ingest daemon receives events from your honeypots and processes them even when the GUI is closed:

```bash
systemctl --user enable --now meli-ingest
```

Check its status:
```bash
systemctl --user status meli-ingest
journalctl --user -u meli-ingest -f
```

## GeoIP Database Setup

Meli uses MaxMind GeoLite2 for offline IP geolocation (no per-lookup API costs):

1. Create a free account at https://www.maxmind.com/
2. Generate a license key in your account dashboard
3. In Meli: Settings → Enrichment APIs → MaxMind License Key → enter key
4. Click "Download GeoLite2 Databases Now"

Databases download to `~/.local/share/meli/geoip/` (~60–70 MB total). MaxMind updates them weekly; re-download monthly for accuracy.

## Enrichment API Keys (Optional)

All enrichment services are optional. Configure them in Settings → Enrichment APIs:

| Service | Free tier | Purpose |
|---------|-----------|---------|
| AbuseIPDB | 1,000 checks/day | Abuse confidence score |
| GreyNoise | 1,000 checks/day | Mass scanner classification |
| VirusTotal | 500 checks/day | IP + file hash reputation |
| Shodan | 100 checks/month | Open ports and CVEs |
| IPInfo | 50,000 checks/month | ASN, org, VPN/Tor detection |

API keys are encrypted at rest using your master password.

## Labyrinth Tarpit (optional)

To start the Labyrinth SSH and Telnet tarpit:

```bash
# Enable via Settings → Labyrinth, then:
systemctl --user enable --now meli-ingest   # ingest daemon includes the tarpit
```

Or run a standalone test:
```bash
python -c "
from meli.labyrinth import LabyrinthDaemon
d = LabyrinthDaemon(host='127.0.0.1', port=2323, ssh_enabled=False)
d.start()
import time; time.sleep(60)
d.stop()
"
```

Note: SSH listener requires `paramiko` (`pip install paramiko`). The install script installs it by default.

## Arch Linux: AUR / PKGBUILD

```bash
cd Meli
makepkg -si
```

Or with an AUR helper once published:
```bash
paru -S meli
# or
yay -S meli
```

## Updating

```bash
cd Meli
git pull
./install.sh --update
```

## Uninstalling

```bash
./uninstall.sh
```

User data (`~/.local/share/meli`) and config (`~/.config/meli`) are preserved. Remove them manually if desired:

```bash
rm -rf ~/.local/share/meli ~/.config/meli
```

## Troubleshooting

### "No module named gi"

GTK4 Python bindings are not installed or the venv is not using `--system-site-packages`. Re-run the installer:
```bash
rm -rf /opt/meli/venv
./install.sh
```

### MQTT connection refused

Mosquitto is not running:
```bash
sudo systemctl start mosquitto
sudo systemctl enable mosquitto
```

### Lock screen appears but window is black

Known issue with some compositor configurations. Try:
```bash
meli --debug
```
Check logs for GTK errors.

### Permission denied on /opt/meli

The installer creates `/opt/meli` owned by your user. If it was created by root, fix:
```bash
sudo chown -R $USER:$USER /opt/meli
```


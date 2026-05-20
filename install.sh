#!/usr/bin/env bash
# ─────────────────────────────────────────────────────────────────────────────
# Meli — Honeypot Command Center
# Install Script — Phase 1: System dependencies + application setup
# Author: Joseph Sierengowski
# ─────────────────────────────────────────────────────────────────────────────
set -euo pipefail

MELI_VERSION="1.0.0"
INSTALL_DIR="/opt/meli"
BIN_LINK="/usr/local/bin/meli"
APP_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
VENV="$INSTALL_DIR/venv"
USER_CONFIG="$HOME/.config/meli"
USER_DATA="$HOME/.local/share/meli"
SYSTEMD_USER="$HOME/.config/systemd/user"

RED='\033[0;31m'
GREEN='\033[0;32m'
AMBER='\033[0;33m'
CYAN='\033[0;36m'
BOLD='\033[1m'
NC='\033[0m'

log()  { echo -e "${CYAN}[meli]${NC} $*"; }
ok()   { echo -e "${GREEN}[  ok ]${NC} $*"; }
warn() { echo -e "${AMBER}[ warn]${NC} $*"; }
err()  { echo -e "${RED}[error]${NC} $*" >&2; }
die()  { err "$*"; exit 1; }

banner() {
cat << 'EOF'

  ███╗   ███╗███████╗██╗     ██╗
  ████╗ ████║██╔════╝██║     ██║
  ██╔████╔██║█████╗  ██║     ██║
  ██║╚██╔╝██║██╔══╝  ██║     ██║
  ██║ ╚═╝ ██║███████╗███████╗██║
  ╚═╝     ╚═╝╚══════╝╚══════╝╚═╝
  Honeypot Command Center v1.0.0
  Author: Joseph Sierengowski

EOF
}

detect_distro() {
    if [ -f /etc/os-release ]; then
        . /etc/os-release
        echo "$ID"
    elif command -v lsb_release &>/dev/null; then
        lsb_release -si | tr '[:upper:]' '[:lower:]'
    else
        echo "unknown"
    fi
}

# ── Phase 1: System package installation ──────────────────────────────────────
install_system_deps() {
    local distro
    distro=$(detect_distro)
    log "Detected distro: $distro"
    log "Phase 1: Installing system dependencies..."

    case "$distro" in
        arch|manjaro|endeavouros|garuda)
            log "Using pacman..."
            sudo pacman -Sy --needed --noconfirm \
                python \
                python-gobject \
                gtk4 \
                libadwaita \
                gobject-introspection \
                mosquitto \
                sqlite \
                gnupg \
                libnotify \
                webkit2gtk-4.1 \
                cairo \
                pango \
                gdk-pixbuf2 \
                python-pip \
                python-setuptools \
                python-wheel \
                base-devel
            ;;
        ubuntu|pop|linuxmint|elementary)
            log "Using apt..."
            sudo apt-get update -qq
            sudo apt-get install -y \
                python3.12 \
                python3.12-venv \
                python3.12-dev \
                python3-gi \
                python3-gi-cairo \
                gir1.2-gtk-4.0 \
                gir1.2-adw-1 \
                libgtk-4-dev \
                libadwaita-1-dev \
                gobject-introspection \
                libgirepository1.0-dev \
                mosquitto \
                mosquitto-clients \
                sqlite3 \
                gnupg2 \
                libnotify-bin \
                gir1.2-notify-0.7 \
                libwebkit2gtk-4.1-dev \
                libcairo2-dev \
                libpango1.0-dev \
                libgdk-pixbuf2.0-dev \
                python3-pip \
                python3-setuptools \
                build-essential \
                pkg-config
            ;;
        fedora|rhel|centos|rocky)
            log "Using dnf..."
            sudo dnf install -y \
                python3.12 \
                python3-gobject \
                gtk4 \
                libadwaita \
                gobject-introspection \
                gobject-introspection-devel \
                mosquitto \
                sqlite \
                gnupg2 \
                libnotify \
                webkit2gtk4.1 \
                cairo-devel \
                pango-devel \
                gdk-pixbuf2-devel \
                python3-pip \
                python3-setuptools \
                gcc \
                make \
                pkg-config
            ;;
        *)
            warn "Unknown distro '$distro'. Please install system packages manually."
            warn "Required: python3.12, python3-gobject, gtk4, libadwaita, mosquitto, sqlite3, gnupg, libnotify"
            warn "Continuing with Python setup..."
            ;;
    esac

    ok "System packages installed."
}

# ── Phase 2: Python virtual environment ───────────────────────────────────────
setup_venv() {
    log "Phase 2: Setting up Python virtual environment at $VENV..."
    sudo mkdir -p "$INSTALL_DIR"
    sudo chown "$USER":"$USER" "$INSTALL_DIR"

    if [ ! -d "$VENV" ]; then
        python3 -m venv --system-site-packages "$VENV"
        ok "Virtual environment created."
    else
        warn "Virtual environment already exists — skipping creation."
    fi

    log "Upgrading pip..."
    "$VENV/bin/pip" install --upgrade pip setuptools wheel -q
}

# ── Phase 3: Python dependencies ──────────────────────────────────────────────
install_python_deps() {
    log "Phase 3: Installing Python dependencies..."
    "$VENV/bin/pip" install -r "$APP_DIR/requirements.txt" -q
    ok "Python dependencies installed."
}

# ── Phase 4: Application files ────────────────────────────────────────────────
install_app_files() {
    log "Phase 4: Copying application files to $INSTALL_DIR..."
    rsync -a --exclude=".git" --exclude="__pycache__" --exclude="*.pyc" \
        --exclude=".venv" --exclude="venv" --exclude="dist" --exclude="build" \
        "$APP_DIR/" "$INSTALL_DIR/app/"
    ok "Application files copied."

    log "Creating launcher script..."
    sudo tee "$BIN_LINK" > /dev/null << EOF
#!/usr/bin/env bash
exec "$VENV/bin/python" -m meli "\$@"
EOF
    sudo chmod +x "$BIN_LINK"
    ok "Launcher created at $BIN_LINK."
}

# ── Phase 5: Desktop integration ─────────────────────────────────────────────
install_desktop() {
    log "Phase 5: Installing desktop integration..."

    # Install icons
    for size in 16 32 48 64 128 256 512; do
        local icon_src="$APP_DIR/assets/icons/meli-${size}.png"
        local icon_dir="/usr/share/icons/hicolor/${size}x${size}/apps"
        if [ -f "$icon_src" ]; then
            sudo mkdir -p "$icon_dir"
            sudo cp "$icon_src" "$icon_dir/meli.png"
        fi
    done

    if [ -f "$APP_DIR/assets/icons/meli.svg" ]; then
        sudo mkdir -p /usr/share/icons/hicolor/scalable/apps
        sudo cp "$APP_DIR/assets/icons/meli.svg" /usr/share/icons/hicolor/scalable/apps/meli.svg
    fi

    # Install desktop file
    if [ -f "$APP_DIR/meli.desktop" ]; then
        sudo cp "$APP_DIR/meli.desktop" /usr/share/applications/meli.desktop
    fi

    # Update caches
    if command -v update-desktop-database &>/dev/null; then
        sudo update-desktop-database /usr/share/applications/ &>/dev/null || true
    fi
    if command -v gtk-update-icon-cache &>/dev/null; then
        sudo gtk-update-icon-cache /usr/share/icons/hicolor/ -f &>/dev/null || true
    fi

    ok "Desktop integration installed."
}

# ── Phase 6: Systemd user services ───────────────────────────────────────────
install_services() {
    log "Phase 6: Installing systemd user services..."
    mkdir -p "$SYSTEMD_USER"

    if [ -f "$APP_DIR/meli.service" ]; then
        cp "$APP_DIR/meli.service" "$SYSTEMD_USER/meli.service"
    fi
    if [ -f "$APP_DIR/meli-ingest.service" ]; then
        cp "$APP_DIR/meli-ingest.service" "$SYSTEMD_USER/meli-ingest.service"
    fi

    systemctl --user daemon-reload 2>/dev/null || true

    # Enable and start ingest daemon (runs without display)
    systemctl --user enable meli-ingest.service 2>/dev/null || warn "Could not enable meli-ingest.service (systemd user session may not be active yet)"
    systemctl --user start meli-ingest.service 2>/dev/null || warn "Could not start meli-ingest.service — start it manually: systemctl --user start meli-ingest"

    ok "Systemd user services installed."
}

# ── Phase 7: Mosquitto setup ──────────────────────────────────────────────────
configure_mosquitto() {
    log "Phase 7: Configuring Mosquitto MQTT broker..."

    local mqtt_conf="$USER_CONFIG/mosquitto.conf"
    mkdir -p "$USER_CONFIG"

    if [ ! -f "$mqtt_conf" ]; then
        cat > "$mqtt_conf" << 'MQTTCONF'
# Meli local MQTT broker configuration
listener 1883 127.0.0.1
allow_anonymous true
log_type error
log_type warning
persistence true
persistence_location /tmp/meli-mqtt/
MQTTCONF
        ok "Mosquitto config written to $mqtt_conf"
    else
        warn "Mosquitto config already exists — skipping."
    fi

    if command -v systemctl &>/dev/null; then
        sudo systemctl enable mosquitto 2>/dev/null || true
        sudo systemctl start mosquitto 2>/dev/null || warn "Could not start mosquitto system service. You may need to start it manually."
    fi
}

# ── Phase 8: User directories ─────────────────────────────────────────────────
create_user_dirs() {
    log "Phase 8: Creating user data directories..."

    mkdir -p \
        "$USER_CONFIG" \
        "$USER_DATA/geoip" \
        "$USER_DATA/cache/enrichment" \
        "$USER_DATA/reports/daily" \
        "$USER_DATA/reports/weekly" \
        "$USER_DATA/reports/monthly" \
        "$USER_DATA/exports" \
        "$USER_DATA/logs" \
        "$USER_DATA/payloads"

    chmod 700 "$USER_CONFIG"
    chmod 700 "$USER_DATA"

    ok "User directories created."
}

# ── Phase 9: Database initialization ─────────────────────────────────────────
init_database() {
    log "Phase 9: Initializing Meli database..."
    cd "$INSTALL_DIR/app"
    "$VENV/bin/python" -c "
from meli.database import init_db
init_db()
print('Database initialized successfully.')
" 2>/dev/null || warn "Database init will complete on first launch."
    ok "Database ready."
}

# ── Summary ───────────────────────────────────────────────────────────────────
print_summary() {
    echo ""
    echo -e "${GREEN}${BOLD}━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━${NC}"
    echo -e "${GREEN}${BOLD}  Meli v${MELI_VERSION} installed successfully!${NC}"
    echo -e "${GREEN}${BOLD}━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━${NC}"
    echo ""
    echo "  Launch:        ${BOLD}meli${NC}"
    echo "  Or from menu:  Look for Meli in your application launcher"
    echo ""
    echo "  First launch will open the Setup Wizard to:"
    echo "    • Set your master password"
    echo "    • Configure optional 2FA"
    echo "    • Add your first honeypot source"
    echo "    • Enter optional enrichment API keys"
    echo "    • Download GeoIP databases"
    echo ""
    echo "  Ingest daemon:  systemctl --user status meli-ingest"
    echo "  Logs:           $USER_DATA/logs/meli.log"
    echo ""
    echo -e "  ${AMBER}If Meli doesn't appear in your launcher, log out and back in.${NC}"
    echo ""
}

# ── Main ──────────────────────────────────────────────────────────────────────
main() {
    banner
    log "Starting Meli installation..."
    echo ""

    local skip_system=false
    local phase_only=""

    while [[ $# -gt 0 ]]; do
        case "$1" in
            --skip-system-deps) skip_system=true ;;
            --phase) phase_only="$2"; shift ;;
            --help|-h)
                echo "Usage: $0 [--skip-system-deps] [--phase 1-9]"
                exit 0
                ;;
        esac
        shift
    done

    if [ "$phase_only" = "1" ]; then
        install_system_deps
        ok "Phase 1 complete."
        exit 0
    fi

    if [ "$skip_system" = false ]; then
        install_system_deps
    else
        warn "Skipping system package installation (--skip-system-deps)"
    fi

    setup_venv
    install_python_deps
    install_app_files
    install_desktop
    install_services
    configure_mosquitto
    create_user_dirs
    init_database
    print_summary
}

main "$@"

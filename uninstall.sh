#!/usr/bin/env bash
# Meli uninstaller — removes app files but preserves user data
set -euo pipefail

RED='\033[0;31m'; GREEN='\033[0;32m'; YELLOW='\033[1;33m'; NC='\033[0m'
info()    { echo -e "\033[0;34m[INFO]${NC} $*"; }
success() { echo -e "${GREEN}[ OK ]${NC} $*"; }
warn()    { echo -e "${YELLOW}[WARN]${NC} $*"; }

echo ""
echo "  Meli Uninstaller"
echo "  ────────────────────────────────"
echo ""
warn "This will remove the Meli application files."
warn "Your data (~/.local/share/meli) and config (~/.config/meli) will be preserved."
echo ""
read -rp "Continue? [y/N] " confirm
[[ "$confirm" =~ ^[Yy]$ ]] || { echo "Aborted."; exit 0; }

# Stop services
info "Stopping systemd user services..."
systemctl --user stop meli-ingest.service 2>/dev/null || true
systemctl --user disable meli-ingest.service 2>/dev/null || true
rm -f "$HOME/.config/systemd/user/meli-ingest.service"
systemctl --user daemon-reload 2>/dev/null || true
success "Services stopped"

# Remove binary and symlinks
info "Removing binaries..."
sudo rm -f /usr/local/bin/meli
success "Binary removed"

# Remove desktop integration
info "Removing desktop integration..."
sudo rm -f /usr/share/applications/meli.desktop
sudo rm -f /usr/share/icons/hicolor/scalable/apps/meli.svg
sudo update-desktop-database 2>/dev/null || true
sudo gtk-update-icon-cache -f -q /usr/share/icons/hicolor 2>/dev/null || true
success "Desktop integration removed"

# Remove application files
info "Removing /opt/meli..."
sudo rm -rf /opt/meli
success "Application removed"

echo ""
success "Meli has been uninstalled."
echo ""
info "Your data and configuration have been preserved:"
info "  Data:   ~/.local/share/meli/"
info "  Config: ~/.config/meli/"
echo ""
info "To fully remove all user data, run:"
info "  rm -rf ~/.local/share/meli ~/.config/meli"
echo ""

# Arch Linux PKGBUILD for Meli — Honeypot Command Center
# Maintainer: Joseph Sierengowski <joseph@example.com>
# Install with: makepkg -si

pkgname=meli
pkgver=1.0.0
pkgrel=1
pkgdesc="Real-time honeypot monitoring and threat intelligence dashboard"
arch=('x86_64' 'aarch64')
url="https://github.com/sierengowski/meli"
license=('MIT')
depends=(
    'python>=3.11'
    'python-gobject'
    'gtk4'
    'libadwaita'
    'mosquitto'
    'python-sqlalchemy'
    'python-click'
    'python-structlog'
    'python-requests'
    'python-paho-mqtt'
    'python-yaml'
    'python-cryptography'
    'python-argon2_cffi'
    'python-bcrypt'
    'python-pyotp'
    'libnotify'
)
makedepends=(
    'python-build'
    'python-installer'
    'python-wheel'
    'python-setuptools'
)
optdepends=(
    'python-geoip2: Offline IP geolocation'
    'python-reportlab: PDF report generation'
    'webkit2gtk-4.1: Interactive geographic map view'
    'gst-plugins-good: Alert sounds'
)
source=("$pkgname-$pkgver.tar.gz::https://github.com/sierengowski/meli/archive/refs/tags/v$pkgver.tar.gz")
sha256sums=('SKIP')

build() {
    cd "$srcdir/$pkgname-$pkgver"
    python -m build --wheel --no-isolation
}

package() {
    cd "$srcdir/$pkgname-$pkgver"
    python -m installer --destdir="$pkgdir" dist/*.whl

    # Desktop file
    install -Dm644 meli.desktop "$pkgdir/usr/share/applications/meli.desktop"

    # Icon
    install -Dm644 assets/icons/meli.svg \
        "$pkgdir/usr/share/icons/hicolor/scalable/apps/meli.svg"

    # Systemd user service
    install -Dm644 meli-ingest.service \
        "$pkgdir/usr/lib/systemd/user/meli-ingest.service"

    # License
    install -Dm644 LICENSE "$pkgdir/usr/share/licenses/$pkgname/LICENSE"
}

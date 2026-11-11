#!/usr/bin/env bash
# Install (or update) the jabuka-touch menu on the Pi. Idempotent: re-run after every update.
#
#   sudo bash touch/install.sh
#
# Needs the system python with Pillow and numpy (apt: python3-pil python3-numpy
# fonts-dejavu-core). Installs the package to /opt/jabuka-touch (root-owned), the unit to
# /etc/systemd/system/jabuka-touch.service, the wrapper to /usr/local/sbin/jabuka-touch, the
# config /etc/jabuka-touch.json only when absent (calibration kept), then daemon-reload + enable
# + restart jabuka-touch. It never touches the firmware/kernel configuration, /opt/jabuka, the
# deploy/ units, jabuka-core or the ingest.
#
# Test overrides: DESTDIR (prefix of every destination, no root needed), SYSTEMCTL (default
# systemctl), TOUCH_PYTHON (default /usr/bin/python3).
set -euo pipefail

HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
DESTDIR="${DESTDIR:-}"
SYSTEMCTL="${SYSTEMCTL:-systemctl}"
TOUCH_PYTHON="${TOUCH_PYTHON:-/usr/bin/python3}"

die() {
    echo "install jabuka-touch : $*" >&2
    exit 1
}

if [ -z "$DESTDIR" ] && [ "$(id -u)" -ne 0 ]; then
    die "lancer avec sudo : sudo bash touch/install.sh"
fi
[ -d "$HERE/jabuka_touch" ] || die "paquet introuvable : $HERE/jabuka_touch"
"$TOUCH_PYTHON" -c 'import PIL, numpy' >/dev/null 2>&1 ||
    die "Pillow ou numpy absent pour $TOUCH_PYTHON : sudo apt install python3-pil python3-numpy fonts-dejavu-core"

OPT="$DESTDIR/opt/jabuka-touch"
UNIT_DIR="$DESTDIR/etc/systemd/system"
SBIN="$DESTDIR/usr/local/sbin"
CONF="$DESTDIR/etc/jabuka-touch.json"

mkdir -p "$OPT" "$UNIT_DIR" "$SBIN" "$DESTDIR/etc"
chmod 0755 "$OPT"

# package: copy to a .new dir, then swap it in (a running menu keeps its loaded modules)
rm -rf "$OPT/jabuka_touch.new" "$OPT/jabuka_touch.old"
cp -R "$HERE/jabuka_touch" "$OPT/jabuka_touch.new"
find "$OPT/jabuka_touch.new" -name __pycache__ -type d -prune -exec rm -rf {} +
find "$OPT/jabuka_touch.new" -type d -exec chmod 0755 {} +
find "$OPT/jabuka_touch.new" -type f -exec chmod 0644 {} +
if [ -z "$DESTDIR" ]; then
    chown -R root:root "$OPT/jabuka_touch.new"
fi
if [ -d "$OPT/jabuka_touch" ]; then
    mv "$OPT/jabuka_touch" "$OPT/jabuka_touch.old"
fi
mv "$OPT/jabuka_touch.new" "$OPT/jabuka_touch"
rm -rf "$OPT/jabuka_touch.old"
install -m 0644 "$HERE/README.md" "$OPT/README.md"

install -m 0644 "$HERE/jabuka-touch.service" "$UNIT_DIR/jabuka-touch.service"
install -m 0755 "$HERE/jabuka-touch" "$SBIN/jabuka-touch"
if [ -e "$CONF" ]; then
    echo "configuration gardée : /etc/jabuka-touch.json (calibration conservée)"
else
    install -m 0644 "$HERE/jabuka-touch.example.json" "$CONF"
    echo "configuration créée : /etc/jabuka-touch.json"
fi

"$SYSTEMCTL" daemon-reload
"$SYSTEMCTL" enable jabuka-touch.service
"$SYSTEMCTL" restart jabuka-touch.service

cat <<'EOF'
jabuka-touch installé : le menu tactile s'affiche sur l'écran 3,5 pouces.
  retour au menu depuis le terminal : sudo jabuka-touch
  mode course depuis un shell       : sudo jabuka-touch course
  recalibrer le toucher             : sudo jabuka-touch calibrate
  désinstaller                      : sudo bash touch/uninstall.sh
EOF

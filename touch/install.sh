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
# It also installs the Copernicus current step /usr/local/sbin/jabuka-current and its tool,
# copernicusmarine 2.5.1, in a SEPARATE venv /opt/copernicusmarine/venv (exact pins from
# touch/copernicusmarine-constraints.txt, binary wheels only; never the race venvs). That step
# needs internet once; without it (or on a pip error) a clear message is printed and the rest of
# the install goes on: re-run later with internet.
#
# Test overrides: DESTDIR (prefix of every destination, no root needed), SYSTEMCTL (default
# systemctl), TOUCH_PYTHON (default /usr/bin/python3), CM_PYTHON (python creating the
# copernicusmarine venv, default /usr/bin/python3). The internet probe uses curl from PATH (python
# urllib fallback).
set -euo pipefail

HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
DESTDIR="${DESTDIR:-}"
SYSTEMCTL="${SYSTEMCTL:-systemctl}"
TOUCH_PYTHON="${TOUCH_PYTHON:-/usr/bin/python3}"
CM_PYTHON="${CM_PYTHON:-/usr/bin/python3}"
CM_VENV="$DESTDIR/opt/copernicusmarine/venv"
CM_VERSION=2.5.1
PYPI_URL=https://pypi.org/simple/copernicusmarine/

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

# Copernicus current step
install -m 0755 "$HERE/jabuka-current" "$SBIN/jabuka-current"

have_pypi() {
    if command -v curl >/dev/null 2>&1; then
        curl -sfI --max-time 10 -o /dev/null "$PYPI_URL"
    else
        python3 -c 'import sys, urllib.request; urllib.request.urlopen(sys.argv[1], timeout=10)' \
            "$PYPI_URL" >/dev/null 2>&1
    fi
}

# never aborts the install (called with || true, every step tested)
install_copernicusmarine() {
    if "$CM_VENV/bin/copernicusmarine" --version 2>/dev/null | grep -q "version $CM_VERSION"; then
        echo "copernicusmarine $CM_VERSION déjà installé (/opt/copernicusmarine/venv)"
        return 0
    fi
    if ! have_pypi; then
        echo "copernicusmarine NON installé : pas d'internet ; relancer sudo bash touch/install.sh avec internet (partage du téléphone : sudo jabuka-wifi phone). Le reste de l'installation continue."
        return 0
    fi
    echo "installation de copernicusmarine $CM_VERSION dans /opt/copernicusmarine/venv (quelques minutes)…"
    if { [ -x "$CM_VENV/bin/pip" ] || "$CM_PYTHON" -m venv "$CM_VENV"; } &&
        "$CM_VENV/bin/pip" install --disable-pip-version-check --no-input --only-binary=:all: \
            -c "$HERE/copernicusmarine-constraints.txt" "copernicusmarine==$CM_VERSION"; then
        echo "copernicusmarine $CM_VERSION installé (/opt/copernicusmarine/venv)"
    else
        echo "copernicusmarine NON installé (voir les erreurs pip ci-dessus). Le reste de l'installation continue."
    fi
    return 0
}
install_copernicusmarine || true

"$SYSTEMCTL" daemon-reload
"$SYSTEMCTL" enable jabuka-touch.service
"$SYSTEMCTL" restart jabuka-touch.service

cat <<'EOF'
jabuka-touch installé : le menu tactile s'affiche sur l'écran 3,5 pouces.
  retour au menu depuis le terminal : sudo jabuka-touch
  mode course depuis un shell       : sudo jabuka-touch course
  recalibrer le toucher             : sudo jabuka-touch calibrate
  désinstaller                      : sudo bash touch/uninstall.sh
courant Copernicus (jabuka-current) :
  identifiants, une fois            : sudo /opt/copernicusmarine/venv/bin/copernicusmarine login
  lancer / suivre / résultat        : sudo jabuka-current ; journalctl -fu jabuka-current ;
                                      sudo jabuka-current status
EOF

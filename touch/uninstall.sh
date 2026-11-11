#!/usr/bin/env bash
# Remove the jabuka-touch menu and give tty1 back to the text console (getty).
#
#   sudo bash touch/uninstall.sh
#
# A running DÉMO is first ended (race mode); on failure nothing is removed (reboot the Pi: the
# demo drop-ins live in /run, then run this again). /etc/jabuka-touch.json is kept.
# Same test overrides as install.sh: DESTDIR, SYSTEMCTL, TOUCH_PYTHON.
set -euo pipefail

DESTDIR="${DESTDIR:-}"
SYSTEMCTL="${SYSTEMCTL:-systemctl}"
TOUCH_PYTHON="${TOUCH_PYTHON:-/usr/bin/python3}"

die() {
    echo "uninstall jabuka-touch : $*" >&2
    exit 1
}

if [ -z "$DESTDIR" ] && [ "$(id -u)" -ne 0 ]; then
    die "lancer avec sudo : sudo bash touch/uninstall.sh"
fi

OPT="$DESTDIR/opt/jabuka-touch"
DROPIN=zz-jabuka-touch-demo.conf
RUN_UNITS="$DESTDIR/run/systemd/system"

if [ -e "$RUN_UNITS/jabuka-core.service.d/$DROPIN" ] ||
    [ -e "$RUN_UNITS/jabuka-ingest-fastnet.service.d/$DROPIN" ]; then
    echo "démo en cours : retour en mode course d'abord"
    [ -d "$OPT/jabuka_touch" ] || die "démo active mais $OPT absent : redémarrer le Pi (sudo systemctl reboot), puis relancer"
    (cd "$OPT" && "$TOUCH_PYTHON" -s -m jabuka_touch race-mode) ||
        die "retour en mode course impossible : redémarrer le Pi (sudo systemctl reboot), puis relancer"
fi

# ExecStopPost gives the text console back (KD_TEXT)
"$SYSTEMCTL" disable --now jabuka-touch.service || true
rm -f "$DESTDIR/etc/systemd/system/jabuka-touch.service" "$DESTDIR/usr/local/sbin/jabuka-touch"
rm -rf "$OPT"
"$SYSTEMCTL" daemon-reload
"$SYSTEMCTL" start getty@tty1.service || true

echo "jabuka-touch désinstallé ; configuration gardée : /etc/jabuka-touch.json"

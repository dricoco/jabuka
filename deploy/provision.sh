#!/usr/bin/env bash
# Turn a fresh Raspberry Pi OS Lite 64-bit (Trixie) into the Jabuka appliance.
#
#   sudo deploy/provision.sh [--dry-run] [--psk-file FILE] [--wheelhouse DIR] [--skip-ap]
#
# Run it as root ON THE PI, over Ethernet (the AP comes up last and drops any Wi-Fi SSH session).
# Idempotent: re-running it upgrades the app from the wheelhouse and re-applies every config.
# --dry-run prints every mutating command as "+ CMD" and changes nothing (no root needed).
# The Wi-Fi passphrase (JABUKA_PSK) comes from --psk-file and is never printed.
#
# Result: WPA2 access point "jabuka" at 10.42.0.1/24 (NetworkManager, ipv4.method shared),
# /dev/fastnet (read-only to the service group) and /dev/gps, gpsd + chrony GPS time, and the two
# Jabuka services enabled at boot with restart + watchdog. Verify with deploy/PI-SETUP.md sect. 4.
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"

DRY_RUN=0
SKIP_AP=0
PSK_FILE="$SCRIPT_DIR/secrets.env"
WHEELHOUSE="$SCRIPT_DIR/wheelhouse"
JABUKA_PSK=""
EXAMPLE_PSK="change-me-8-to-63-chars"

OPT=/opt/jabuka
VENV=$OPT/venv
DATA=/var/lib/jabuka
APT_PACKAGES=(gpsd gpsd-clients chrony python3-venv jq dnsmasq-base)
F2I_VENV=/opt/fastnet2ip/venv
PREP_VENV=/opt/jabuka-prep/venv

usage() {
    sed -n '2,13p' "${BASH_SOURCE[0]}" | sed 's/^# \{0,1\}//'
}

die() {
    local code="$1"
    shift
    echo "provision: ERROR: $*" >&2
    exit "$code"
}

warn() { echo "provision: WARNING: $*" >&2; }
step() { printf '\n== %s\n' "$*"; }

while [ $# -gt 0 ]; do
    case "$1" in
        --dry-run) DRY_RUN=1 ;;
        --skip-ap) SKIP_AP=1 ;;
        --psk-file)
            [ $# -ge 2 ] || die 2 "--psk-file needs a FILE"
            PSK_FILE="$2"
            shift
            ;;
        --wheelhouse)
            [ $# -ge 2 ] || die 2 "--wheelhouse needs a DIR"
            WHEELHOUSE="$2"
            shift
            ;;
        -h | --help)
            usage
            exit 0
            ;;
        *) die 2 "unknown argument: $1 (see --help)" ;;
    esac
    shift
done

if [ "$DRY_RUN" -eq 0 ] && [ "${EUID:-$(id -u)}" -ne 0 ]; then
    die 1 "must run as root (sudo $0 ...), or use --dry-run"
fi

# --- helpers: every mutating command goes through run() -----------------------------------------

# Print a command with the passphrase masked.
show() {
    local out="+" a
    for a in "$@"; do
        if [ -n "$JABUKA_PSK" ] && [ "$a" = "$JABUKA_PSK" ]; then
            a="***"
        fi
        out="$out $a"
    done
    printf '%s\n' "$out"
}

run() {
    show "$@"
    if [ "$DRY_RUN" -eq 0 ]; then
        "$@"
    fi
}

# Like run(), but a failure is a warning, not fatal.
run_tolerant() {
    show "$@"
    if [ "$DRY_RUN" -eq 0 ]; then
        "$@" || warn "command failed (tolerated): $1 ${2:-}"
    fi
}

# install_file SRC DEST [MODE]
install_file() {
    local src="$1" dest="$2" mode="${3:-0644}"
    [ -f "$src" ] || die 3 "missing file in the repo: $src"
    run install -D -m "$mode" "$src" "$dest"
}

# write_file DEST CONTENT (content is never secret)
write_file() {
    local dest="$1" content="$2"
    show "write_file $dest <<'EOF'"
    printf '%s\n' "$content" | sed 's/^/    /'
    if [ "$DRY_RUN" -eq 0 ]; then
        install -d -m 0755 "$(dirname "$dest")"
        printf '%s\n' "$content" >"$dest.tmp"
        chmod 0644 "$dest.tmp"
        mv -f "$dest.tmp" "$dest"
    fi
}

# --- the Wi-Fi passphrase -----------------------------------------------------------------------

load_psk() {
    [ -f "$PSK_FILE" ] || die 2 "PSK file not found: $PSK_FILE (copy deploy/secrets.env.example to deploy/secrets.env)"
    local line value=""
    # Parsed, never sourced: the file is data, not code.
    while IFS= read -r line || [ -n "$line" ]; do
        case "$line" in
            JABUKA_PSK=*) value="${line#JABUKA_PSK=}" ;;
        esac
    done <"$PSK_FILE"
    value="${value%$'\r'}"
    case "$value" in
        \"*\")
            value="${value#\"}"
            value="${value%\"}"
            ;;
        \'*\')
            value="${value#\'}"
            value="${value%\'}"
            ;;
    esac
    local n=${#value}
    if [ "$n" -lt 8 ] || [ "$n" -gt 63 ]; then
        die 2 "JABUKA_PSK in $PSK_FILE must be 8-63 characters (got $n)"
    fi
    if ! LC_ALL=C grep -q '^[[:print:]]*$' <<<"$value"; then
        die 2 "JABUKA_PSK in $PSK_FILE must be printable ASCII"
    fi
    if [ "$DRY_RUN" -eq 0 ] && [ "$value" = "$EXAMPLE_PSK" ]; then
        die 2 "JABUKA_PSK is still the example value; set a real passphrase in $PSK_FILE"
    fi
    JABUKA_PSK="$value"
}

if [ "$SKIP_AP" -eq 0 ]; then
    load_psk
fi

if [ "$DRY_RUN" -eq 1 ]; then
    echo "provision: DRY RUN (nothing is changed)"
fi

# --- a. packages --------------------------------------------------------------------------------
step "a. apt packages"
missing_pkgs() {
    local p
    for p in "${APT_PACKAGES[@]}"; do
        dpkg-query -W -f='${Status}' "$p" 2>/dev/null | grep -q 'install ok installed' || echo "$p"
    done
}
if [ "$DRY_RUN" -eq 1 ] || [ -n "$(missing_pkgs)" ]; then
    run apt-get update
    run env DEBIAN_FRONTEND=noninteractive apt-get install -y "${APT_PACKAGES[@]}"
else
    echo "all apt packages already installed (offline re-run is fine)"
fi

# --- b. nothing may probe or grab the USB serial adapters -------------------------------------
step "b. purge modemmanager and brltty"
# "not installed" is fine; apt-get purge just reports it
run_tolerant env DEBIAN_FRONTEND=noninteractive apt-get purge -y modemmanager brltty

# --- c. gpsd + udev -----------------------------------------------------------------------------
step "c. gpsd defaults and udev rules"
install_file "$SCRIPT_DIR/gpsd.default" /etc/default/gpsd
install_file "$SCRIPT_DIR/udev/99-jabuka.rules" /etc/udev/rules.d/99-jabuka.rules
run udevadm control --reload
run udevadm trigger

# --- d. chrony from GPS (chrony first, then gpsd, per the gpsd time-service howto) --------------
step "d. chrony GPS refclock"
install_file "$SCRIPT_DIR/chrony-gps.conf" /etc/chrony/conf.d/gps.conf
run sed -i 's/^makestep 1 3$/makestep 1 -1/' /etc/chrony/chrony.conf
if [ "$DRY_RUN" -eq 0 ] && ! grep -q '^makestep 1 -1$' /etc/chrony/chrony.conf; then
    show "append 'makestep 1 -1' to /etc/chrony/chrony.conf"
    printf '\n# Jabuka: no RTC, no internet: GPS may step the clock at any time\nmakestep 1 -1\n' \
        >>/etc/chrony/chrony.conf
fi
run systemctl enable --now chrony.service
run systemctl restart chrony.service
run systemctl enable --now gpsd.service
run systemctl restart gpsd.service

# --- e. service user and directories ------------------------------------------------------------
step "e. jabuka user and directories"
if id -u jabuka >/dev/null 2>&1; then
    echo "user jabuka exists"
    run usermod -a -G dialout jabuka
else
    run useradd --system --user-group --home-dir "$DATA" --no-create-home \
        --shell /usr/sbin/nologin --groups dialout jabuka
fi
run install -d -m 0755 "$OPT"
run install -d -o jabuka -g jabuka -m 0750 "$DATA"

# --- f. app from the offline wheelhouse (hash-locked) -------------------------------------------
step "f. app venv from the wheelhouse"
LOCK="$SCRIPT_DIR/requirements.lock"
if [ ! -f "$LOCK" ]; then
    [ "$DRY_RUN" -eq 1 ] || die 3 "missing $LOCK (run 'bash scripts/build-wheelhouse.sh --relock')"
    warn "missing $LOCK; dry run continues"
fi
JABUKA_WHEEL_NAME="jabuka-*.whl"
if [ -d "$WHEELHOUSE" ] && compgen -G "$WHEELHOUSE/jabuka-*.whl" >/dev/null; then
    JABUKA_WHEEL_NAME="$(basename "$(ls -1 "$WHEELHOUSE"/jabuka-*.whl | sort -V | tail -n 1)")"
elif [ "$DRY_RUN" -eq 1 ]; then
    warn "wheelhouse $WHEELHOUSE is missing (run 'bash scripts/build-wheelhouse.sh' on the laptop); dry run continues"
else
    die 3 "wheelhouse $WHEELHOUSE is missing or has no jabuka-*.whl. On the laptop run 'bash scripts/build-wheelhouse.sh' and copy deploy/wheelhouse/ to the Pi (deploy/PI-SETUP.md section 3)."
fi
run rm -rf "$OPT/wheelhouse.new"
run cp -a "$WHEELHOUSE" "$OPT/wheelhouse.new"
run rm -rf "$OPT/wheelhouse"
run mv "$OPT/wheelhouse.new" "$OPT/wheelhouse"
run install -m 0644 "$LOCK" "$OPT/requirements.lock"
if [ -f "$SCRIPT_DIR/PI-SETUP.md" ]; then
    run install -m 0644 "$SCRIPT_DIR/PI-SETUP.md" "$OPT/PI-SETUP.md"
fi
# Wi-Fi mode switch (boat AP <-> phone hotspot), see PI-SETUP.md section 6.
if [ -f "$SCRIPT_DIR/jabuka-wifi" ]; then
    run install -m 0755 "$SCRIPT_DIR/jabuka-wifi" /usr/local/sbin/jabuka-wifi
fi
run python3 -m venv "$VENV"
run "$VENV/bin/pip" install --no-index --find-links "$OPT/wheelhouse" --require-hashes \
    -r "$OPT/requirements.lock"
run "$VENV/bin/pip" install --no-index --no-deps --force-reinstall "$OPT/wheelhouse/$JABUKA_WHEEL_NAME"

# --- g. Plan B: fastnet2ip (installed, never enabled) -------------------------------------------
# Hash-locked from the wheelhouse into its own venv, like the app: no live PyPI resolution. It runs
# as jabuka without dialout and reads the receive-only relay's pty, never /dev/fastnet itself.
step "g. fastnet2ip Plan B (hash-locked venv + receive-only relay, NOT enabled)"
F2I_LOCK="$SCRIPT_DIR/fastnet2ip.lock"
if [ ! -f "$F2I_LOCK" ]; then
    [ "$DRY_RUN" -eq 1 ] || die 3 "missing $F2I_LOCK (run 'bash scripts/build-wheelhouse.sh --relock')"
    warn "missing $F2I_LOCK; dry run continues"
fi
if [ "$DRY_RUN" -eq 1 ] || [ -d "$OPT/wheelhouse/fastnet2ip" ]; then
    run install -m 0644 "$F2I_LOCK" "$OPT/fastnet2ip.lock"
    run python3 -m venv "$F2I_VENV"
    run "$F2I_VENV/bin/pip" install --no-index --find-links "$OPT/wheelhouse/fastnet2ip" \
        --require-hashes -r "$OPT/fastnet2ip.lock"
else
    warn "no fastnet2ip/ in the wheelhouse: Plan B NOT installed (re-run scripts/build-wheelhouse.sh)"
fi
# An earlier provisioning installed fastnet2ip with `pipx install --global` (root, unpinned
# dependencies): remove it so only the hash-locked venv remains.
if [ "$DRY_RUN" -eq 0 ] && [ -e /usr/local/bin/fastnet2ip ] && command -v pipx >/dev/null 2>&1; then
    run_tolerant pipx uninstall --global fastnet2ip
fi
install_file "$SCRIPT_DIR/systemd/jabuka-fastnet-relay.service" \
    /etc/systemd/system/jabuka-fastnet-relay.service
install_file "$SCRIPT_DIR/systemd/fastnet2ip.service" /etc/systemd/system/fastnet2ip.service

# --- g2. emergency weather prep on the Pi (never the app venv) ---------------------------------
# Hash-locked from the wheelhouse into its own venv, like Plan B. Used only by `prerace` /
# `jabuka-prep-pi` when the laptop is unavailable (PI-SETUP.md section 8).
step "g2. emergency weather prep venv /opt/jabuka-prep/venv (separate from the app venv)"
PREP_LOCK="$SCRIPT_DIR/prep.lock"
if [ ! -f "$PREP_LOCK" ]; then
    [ "$DRY_RUN" -eq 1 ] || die 3 "missing $PREP_LOCK (run 'bash scripts/build-wheelhouse.sh')"
    warn "missing $PREP_LOCK; dry run continues"
fi
if [ "$DRY_RUN" -eq 1 ] || [ -d "$OPT/wheelhouse/prep" ]; then
    run install -m 0644 "$PREP_LOCK" "$OPT/prep.lock"
    run python3 -m venv "$PREP_VENV"
    run "$PREP_VENV/bin/pip" install --no-index --find-links "$OPT/wheelhouse" --require-hashes \
        -r "$OPT/requirements.lock"
    run "$PREP_VENV/bin/pip" install --no-index --find-links "$OPT/wheelhouse/prep" \
        --require-hashes -r "$OPT/prep.lock"
    run "$PREP_VENV/bin/pip" install --no-index --no-deps --force-reinstall \
        "$OPT/wheelhouse/$JABUKA_WHEEL_NAME"
    run ln -sfn "$PREP_VENV/bin/jabuka-prep" /usr/local/bin/jabuka-prep-pi
else
    warn "no prep/ in the wheelhouse: emergency weather prep NOT installed (re-run scripts/build-wheelhouse.sh)"
fi
# One-command weather prep on the Pi (`sudo prerace`); it reports a missing venv itself at run time.
if [ -f "$SCRIPT_DIR/prerace" ]; then
    run install -m 0755 "$SCRIPT_DIR/prerace" /usr/local/sbin/prerace
fi

# --- h. services, journald, hardware watchdog ---------------------------------------------------
step "h. systemd units and drop-ins"
install_file "$SCRIPT_DIR/systemd/jabuka-ingest-fastnet.service" \
    /etc/systemd/system/jabuka-ingest-fastnet.service
install_file "$SCRIPT_DIR/systemd/jabuka-core.service" /etc/systemd/system/jabuka-core.service
install_file "$SCRIPT_DIR/systemd/watchdog.conf" /etc/systemd/system.conf.d/jabuka-watchdog.conf
install_file "$SCRIPT_DIR/systemd/journald-jabuka.conf" /etc/systemd/journald.conf.d/jabuka.conf
run systemctl daemon-reload
run systemctl enable jabuka-ingest-fastnet.service jabuka-core.service
run systemctl restart systemd-journald.service
# (re)start so a re-run picks up the new wheel; the hardware watchdog arms at the next boot
run systemctl restart jabuka-ingest-fastnet.service jabuka-core.service

# --- i. SSH: key-only, but only if a key is installed (lockout guard) ---------------------------
step "i. SSH key-only login"
have_key=0
for f in /home/*/.ssh/authorized_keys; do
    if [ -s "$f" ]; then
        have_key=1
        break
    fi
done
if [ "$have_key" -eq 1 ]; then
    # sshd keeps the FIRST value it reads for each keyword and includes sshd_config.d/*.conf in
    # lexical order, so a numbered drop-in (e.g. Imager/cloud-init 50-cloud-init.conf with
    # "PasswordAuthentication yes") would win over "jabuka.conf". 00- sorts first.
    write_file /etc/ssh/sshd_config.d/00-jabuka.conf "# Jabuka: key-only SSH (written by deploy/provision.sh)
PasswordAuthentication no
KbdInteractiveAuthentication no"
    if [ -e /etc/ssh/sshd_config.d/jabuka.conf ]; then
        run rm -f /etc/ssh/sshd_config.d/jabuka.conf # the old, overridable name
    fi
    run sshd -t
    run_tolerant systemctl reload ssh.service
    # Verify the EFFECTIVE configuration, not just that the file was written.
    if [ "$DRY_RUN" -eq 1 ]; then
        show "sshd -T | grep -x 'passwordauthentication no' (verify)"
    else
        effective="$(sshd -T 2>/dev/null || true)"
        for kv in "passwordauthentication no" "kbdinteractiveauthentication no"; do
            if ! grep -qx "$kv" <<<"$effective"; then
                warn "SSH is NOT key-only: sshd -T does not report '$kv' (another sshd_config.d drop-in or a Match block wins; fix it before the boat)"
            fi
        done
    fi
else
    warn "no non-empty /home/*/.ssh/authorized_keys: leaving SSH password login ON (lockout guard)"
fi

# --- j. Wi-Fi access point (LAST: it takes over wlan0) ------------------------------------------
if [ "$SKIP_AP" -eq 1 ]; then
    step "j. access point: skipped (--skip-ap)"
else
    step "j. WPA2 access point jabuka at 10.42.0.1/24"
    if command -v raspi-config >/dev/null 2>&1; then
        run raspi-config nonint do_wifi_country HR
    else
        echo "raspi-config not found: Wi-Fi country not set here (Imager sets it; see PI-SETUP.md)"
    fi

    # The AP must be the only autoconnect profile on wlan0: delete every other Wi-Fi profile,
    # except jabuka-phone (phone hotspot of jabuka-wifi, written with autoconnect=false).
    if [ "$DRY_RUN" -eq 1 ]; then
        show nmcli connection delete "<every 802-11-wireless profile except jabuka-ap and jabuka-phone>"
    else
        ap_uuid="$(nmcli -g connection.uuid connection show jabuka-ap 2>/dev/null || true)"
        while IFS=: read -r uuid type name; do
            [ "$type" = "802-11-wireless" ] || continue
            [ "$uuid" = "$ap_uuid" ] && continue
            if [ "$name" = "jabuka-phone" ]; then
                run nmcli connection modify uuid "$uuid" connection.autoconnect no
                continue
            fi
            run nmcli connection delete uuid "$uuid"
        done < <(nmcli -t -f UUID,TYPE,NAME connection show)
    fi

    AP_PROPS=(
        connection.autoconnect yes
        connection.autoconnect-priority 100
        802-11-wireless.mode ap
        802-11-wireless.band bg
        802-11-wireless.channel 6
        802-11-wireless.powersave 2
        ipv4.method shared
        ipv4.addresses 10.42.0.1/24
        ipv6.method disabled
        wifi-sec.key-mgmt wpa-psk
        wifi-sec.psk "$JABUKA_PSK"
        wifi-sec.proto rsn
        wifi-sec.pairwise ccmp
        wifi-sec.group ccmp
        wifi-sec.pmf disable
    )
    if [ "$DRY_RUN" -eq 0 ] && nmcli connection show jabuka-ap >/dev/null 2>&1; then
        run nmcli connection modify jabuka-ap connection.interface-name wlan0 \
            802-11-wireless.ssid jabuka "${AP_PROPS[@]}"
    else
        run nmcli connection add type wifi ifname wlan0 con-name jabuka-ap ssid jabuka "${AP_PROPS[@]}"
    fi

    warn "bringing up the AP now: an SSH session over Wi-Fi DROPS here (provision over Ethernet)"
    run nmcli connection up jabuka-ap
fi

# --- k. next steps ------------------------------------------------------------------------------
step "k. done"
echo "Now run the verify checklist: deploy/PI-SETUP.md section 4 (also at $OPT/PI-SETUP.md)."
echo "Reboot once (sudo reboot) to arm the hardware watchdog and prove a clean headless boot."

# Jabuka Pi setup and verification runbook

This runbook turns a Raspberry Pi 3B into the Jabuka appliance and verifies it on the hardware.
Everything that can be checked without the hardware is already covered by the automated tests
on the laptop (`bash scripts/check.sh`). The steps below are the ones that need the real Pi, the
real adapters and a tablet.

Run the steps in order. Each step gives the exact command and what you should see. Record
pass/fail for every item of section 4 in the phase UAT.

The result is a WPA2 access point `jabuka` at **http://10.42.0.1/**, with the Fastnet ingest and
the core starting at boot and restarting after a crash.

---

## 0. Prerequisites

Hardware:

- Raspberry Pi 3B
- a good 5 V 3 A power supply (undervoltage causes SD corruption and random resets)
- a microSD card, plus a spare card for a clone later
- DTECH USB RS422/485 adapter (FTDI FT232R) on the Fastnet bus (receive only)
- VK-162 USB GPS (u-blox 7)
- an Ethernet cable to your home router. Provision over Ethernet, never over Wi-Fi.

On the laptop, in the repo:

1. Build the offline wheelhouse (needs internet):

   ```bash
   bash scripts/build-wheelhouse.sh
   ```

   Expected: the last line is `build-wheelhouse: ok`, and `ls deploy/wheelhouse` lists 18 wheels,
   including `jabuka-0.1.0-py3-none-any.whl`.

2. Create the Wi-Fi secret (8-63 characters, never committed, `deploy/secrets.env` is gitignored):

   ```bash
   cp deploy/secrets.env.example deploy/secrets.env
   chmod 600 deploy/secrets.env
   $EDITOR deploy/secrets.env        # set JABUKA_PSK=<your passphrase>
   ```

3. Check the provisioning plan without touching anything:

   ```bash
   bash deploy/provision.sh --dry-run --psk-file deploy/secrets.env
   ```

   Expected: every step a-k is printed as `+ ...` lines, the passphrase shows as `***`, and the
   exit code is 0.

## 1. Flash the SD card

1. Install Raspberry Pi Imager 2.x on the laptop.
2. Choose **Raspberry Pi 3**, **Raspberry Pi OS Lite (64-bit)** (Debian 13 "Trixie"), and the SD card.
3. In the customisation settings, set:
   - hostname `jabuka`
   - a user name and password (you will use this user to SSH in)
   - SSH: enabled, **public-key only**, paste your laptop's `~/.ssh/id_ed25519.pub`
   - Wi-Fi: do not configure a Wi-Fi network, only set **Wi-Fi country HR**
   - time zone `Europe/Zagreb`, keyboard as you like
4. Write the card.

Alternative without Imager (no customisation, so you must add user and SSH yourself):

```bash
xz -dc 2026-xx-xx-raspios-trixie-arm64-lite.img.xz | sudo dd of=/dev/sdX bs=4M conv=fsync
```

Note: on Trixie, first boot is configured by **cloud-init**. Imager writes `user-data`,
`network-config` and `meta-data` to the FAT boot partition, so you can still fix the user or the
SSH key there, from any computer, before the first boot.

## 2. First boot over Ethernet

1. Put the card in the Pi, plug in Ethernet, the DTECH adapter and the VK-162, then power on.
2. Wait about 2 minutes, then SSH in (use the router's DHCP list if `jabuka.local` does not resolve):

   ```bash
   ssh <user>@jabuka.local
   ```

3. Check that both USB adapters enumerate with the IDs the udev rules expect:

   ```bash
   lsusb
   ```

   Expected: a line with `0403:6001` (FTDI, the DTECH) and a line with `1546:01a7` (u-blox 7, the
   VK-162).

   If an ID differs, edit `deploy/udev/99-jabuka.rules` on the laptop to match before step 3.
   If more than one FTDI device may ever be plugged in, pin the DTECH by its serial number:

   ```bash
   udevadm info -a -n /dev/ttyUSB0 | grep -m1 'ATTRS{serial}'
   ```

   Then add `ATTRS{serial}=="<that value>"` to the fastnet rule.

## 3. Install

1. From the laptop, copy the repo, including `deploy/wheelhouse/` and `deploy/secrets.env`, but
   not the laptop's virtualenvs:

   ```bash
   rsync -a --delete --exclude '.venv*' --exclude '.git' --exclude '__pycache__' \
       ./ <user>@jabuka.local:jabuka/
   ```

   The copy has no `.git` on purpose: the soak report identifies the code by the fingerprint of
   the installed package (`code.sha256`, docs/SOAK.md), and freeze-check F4 compares it with
   `src/jabuka` at HEAD.

2. On the Pi, over Ethernet:

   ```bash
   cd ~/jabuka
   sudo deploy/provision.sh --psk-file deploy/secrets.env
   ```

   Expected: the steps a-k run without `ERROR`. The last step brings up the access point and
   prints that a Wi-Fi SSH session would drop (yours is on Ethernet, so it stays).
   The script is idempotent: run it again after any change (for example a new wheelhouse).
   It needs internet only for `apt-get`. The app and the fastnet2ip Plan B both install from the
   wheelhouse with `--require-hashes` (`deploy/requirements.lock`, `deploy/fastnet2ip.lock`), so
   with every apt package already installed a re-run works offline.

3. Reboot once, so the hardware watchdog is armed and you prove a clean headless boot:

   ```bash
   sudo reboot
   ```

## 4. Verify checklist (human-check; record pass/fail for each item)

a. **Both services are active.**

   ```bash
   systemctl status jabuka-ingest-fastnet jabuka-core
   systemctl is-enabled jabuka-ingest-fastnet jabuka-core
   ```

   Expected: `active (running)` twice, and `enabled` twice.

b. **The Fastnet device is read-only to the service group.**

   ```bash
   ls -l /dev/fastnet /dev/gps
   ls -lL /dev/fastnet
   ```

   Expected: both symlinks exist, and `/dev/fastnet` resolves to a `ttyUSB` node shown as
   `crw-r----- 1 root dialout`.

c. **Serial line settings on the real FTDI** (ptys cannot test parity, so only the Pi proves this).
   With the ingest running:

   ```bash
   stty -F /dev/fastnet
   ```

   Expected: `speed 28800 baud` and the flags `parenb parodd cs8 cstopb`.

d. **Only the ingest holds the adapter.**

   ```bash
   sudo lsof /dev/ttyUSB*
   ```

   Expected: only `jabuka-ingest-fastnet` (shown as `python3`/`jabuka-in`) on the FTDI node, and
   `gpsd` on the GPS node. No ModemManager, no brltty.

e. **GPS fix and chrony on GPS time.**

   ```bash
   gpspipe -w -n 5 | grep TPV
   chronyc sources
   ```

   Expected: TPV lines with `"mode":3` (or 2), and a `#* GPS` line in `chronyc sources` once
   chrony has selected it (allow a few minutes after a cold start).

f. **Boot with no internet.** Unplug Ethernet, reboot, and wait for a GPS fix outdoors.

   ```bash
   date -u
   ```

   Expected: the correct UTC time (within a second). On the diagnostics page the routing time gate
   goes from `blocked` to `ok`.

g. **Tablet joins the AP.** First check the AP's key management on the Pi:

   ```bash
   sudo wpa_cli -i wlan0 status | grep key_mgmt
   journalctl -b -t jabuka-wifi | grep key_mgmt
   ```

   Expected: `key_mgmt=WPA2-PSK` (never a `...-SHA256` value), and a line from this boot saying
   key_mgmt was reset to WPA-PSK (or was already WPA-PSK).

   Why: on this Pi (NetworkManager 1.52, brcmfmac firmware without MFP/SAE) NetworkManager asks
   wpa_supplicant for WPA-PSK plus WPA-PSK-SHA256, even with `wifi-sec.pmf disable`. The firmware
   beacons PSK only, but message 3 of the 4-way handshake carries PSK + PSK-SHA256, so clients
   drop right after it although the passphrase is right. Provision installs
   `/etc/NetworkManager/dispatcher.d/90-jabuka-ap-keymgmt`, which resets it to WPA-PSK each time
   jabuka-ap comes up (boot, provision, `sudo jabuka-wifi ap`, fallback from the phone hotspot).

   Then on the tablet, forget other networks and turn mobile data off. Join `jabuka` with the
   passphrase, then open **http://10.42.0.1/**. Join `jabuka` from a phone too.

   Expected: the tablet and the phone both join `jabuka`, and the tablet shows the Jabuka
   diagnostics page, with values, sources and ages. After `sudo jabuka-wifi phone` then
   `sudo jabuka-wifi ap`, the key_mgmt check gives `key_mgmt=WPA2-PSK` again.

h. **kill -9 recovery.**

   ```bash
   sudo kill -9 $(systemctl show -p MainPID --value jabuka-core)
   sleep 5; systemctl show -p NRestarts -p ActiveState jabuka-core
   sudo kill -9 $(systemctl show -p MainPID --value jabuka-ingest-fastnet)
   sleep 5; systemctl show -p NRestarts -p ActiveState jabuka-ingest-fastnet
   ```

   Expected: each service is back `active` within about 5 s, and its NRestarts went up by 1. The
   page shows live values again. The ingest's NRestarts must stay at 1 (a value that keeps
   climbing means it cannot reopen the device; see section 6).

i. **Unplug and replug the adapters while running.** Unplug the DTECH, wait 10 s, plug it back.
   Do the same with the VK-162.

   Expected: the page shows the source as missing, then recovered, with no manual action.

j. **5 power pulls.** Pull the power while everything runs, wait 10 s, power on. Repeat 5 times.
   After each boot:

   ```bash
   systemctl is-active jabuka-ingest-fastnet jabuka-core
   sudo -u jabuka /opt/jabuka/venv/bin/jabuka-logcheck /var/lib/jabuka/logs
   ```

   Expected: `active` twice, and `jabuka-logcheck` ends with `logcheck: OK` and exit code 0
   (`echo $?`). Torn tails are expected and fine. `BAD` lines are not.

k. **Hardware watchdog armed.**

   ```bash
   dmesg | grep -i watchdog
   ```

   Expected: a line showing the bcm2835 watchdog in use with a timeout around 15 s.

l. **Probe on a disconnected bus.** With the ingest stopped and the bus NOT connected:

   ```bash
   sudo systemctl stop jabuka-ingest-fastnet
   sudo -u jabuka /opt/jabuka/venv/bin/fastnet-probe --device /dev/fastnet --seconds 10
   sudo systemctl start jabuka-ingest-fastnet
   ```

   Expected: a `NO BYTES` verdict (the adapter is fine, nothing is talking). If the ingest is
   still running the probe prints `PORT BUSY` and exits 1 without a wiring verdict: the port is
   opened with an exclusive lock, so two readers never split the byte stream.

m. **Package lock review.** Read `deploy/requirements.lock` and confirm the 17 resolved names
   are exactly: annotated-doc, annotated-types, anyio, click, fastapi, h11, idna,
   opentelemetry-api, pydantic, pydantic-core, pyfastnet, pyserial, starlette, typing-extensions,
   typing-inspection, uvicorn, websockets. Flag any extra or unfamiliar name before the wheelhouse
   goes to the Pi. Do the same for `deploy/fastnet2ip.lock` (Plan B, 11 names): fastnet2ip,
   nmea2000, orjson, packaging, pyfastnet, pyserial, pyserial-asyncio, python-can, tenacity,
   typing-extensions, wrapt.

## 5. Plan B: fastnet2ip and OpenCPN

Use this only when the Jabuka ingest is unusable. fastnet2ip never gets the bus:

- `jabuka-fastnet-relay` opens `/dev/fastnet` exactly like the ingest (O_RDONLY, break/RTS/DTR/
  RS-485 control refused, echo and XON/XOFF off, exclusive lock) and copies the bytes into a pty
  at `/run/jabuka-relay/fastnet-ro`.
- fastnet2ip runs as `jabuka` WITHOUT the `dialout` group, so it cannot open `/dev/fastnet` at
  all. It reads the relay's pty; pyserial opens that read/write and sets DTR/RTS on it, but
  anything written there is read back by the relay, discarded and logged
  (`journalctl -u jabuka-fastnet-relay`: "Plan B reader wrote N bytes ... discarded").
- fastnet2ip 3.3.1 and all 10 dependencies are pinned with hashes in `deploy/fastnet2ip.lock` and
  installed offline into `/opt/fastnet2ip/venv`. No `pipx`/PyPI resolution happens on the Pi.

Residual risk: the third-party code still runs on the appliance (as an unprivileged user with
its own venv), and `nmea2000` 2026.11.3 was released days before it was locked. Review the lock
(item m) and re-lock deliberately (`bash scripts/build-wheelhouse.sh --relock`).

1. Start it. `Conflicts=` stops the Jabuka ingest automatically:

   ```bash
   sudo systemctl start fastnet2ip
   systemctl is-active fastnet2ip jabuka-fastnet-relay jabuka-ingest-fastnet
   ```

   Expected: `active`, `active`, then `inactive`.

2. On the laptop, join the `jabuka` AP and set OpenCPN to a network connection: UDP, input,
   port 2002. NMEA 0183 sentences are broadcast to 10.42.0.255.

3. Return to Jabuka:

   ```bash
   sudo systemctl start jabuka-ingest-fastnet
   ```

   Expected: fastnet2ip and the relay stop, and the ingest is active again. Neither fastnet2ip
   nor the relay is ever enabled at boot.

## 6. Troubleshooting

- **AP missing (no `jabuka` network):** Wi-Fi may still be rfkill-blocked because no country is
  set.

  ```bash
  rfkill list
  sudo raspi-config nonint do_wifi_country HR
  sudo nmcli connection up jabuka-ap
  ```

- **Internet on the Pi through a phone hotspot** (fetch a GRIB, `apt`, Claude Code at the dock):
  `jabuka-wifi` (installed by provision in `/usr/local/sbin`) switches wlan0 between the boat AP
  and the phone. While on the phone, the tablet loses `jabuka`: switch back before racing.

  ```bash
  sudo jabuka-wifi                 # status: active profile, SSID, IP
  sudo jabuka-wifi phone           # join Noway_nomap (WPA2); asks the password the first time
  sudo jabuka-wifi phone AUTRE_SSID --new-password   # other hotspot / changed password
  sudo jabuka-wifi ap              # back to the jabuka AP (10.42.0.1)
  journalctl -t jabuka-wifi        # what happened
  ```

  The switch runs detached: an SSH session over Wi-Fi drops, then reconnect through the phone
  (`ssh drico@<hostname>.local` or the address in the phone's hotspot client list). The phone
  profile never autoconnects: if joining fails, or the hotspot disappears later, the AP comes back
  on its own, and a reboot always starts on the AP. Re-running provision keeps the profile. To
  build the race weather on the Pi itself, see section 8 (`sudo prerace`).

- **Tablet cannot join, or joins and drops:** first run the key_mgmt check of section 4 g
  (`sudo wpa_cli -i wlan0 status | grep key_mgmt`). If it shows a `...-SHA256` value, check that
  the dispatcher is in place:

  ```bash
  ls -l /etc/NetworkManager/dispatcher.d/90-jabuka-ap-keymgmt   # -rwxr-xr-x root root
  systemctl is-enabled NetworkManager-dispatcher                # enabled
  journalctl -t jabuka-wifi | grep key_mgmt                     # what it did
  ```

  The journal says "boucle évitée" if the loop guard stopped it (3 fixes within 60 s). Re-run
  `sudo deploy/provision.sh --skip-ap` if the file is missing or not owned by root. Manual fix:

  ```bash
  sudo wpa_cli -i wlan0 list_networks          # note the id of jabuka
  sudo wpa_cli -i wlan0 set_network <id> key_mgmt WPA-PSK
  sudo wpa_cli -i wlan0 disconnect
  sudo wpa_cli -i wlan0 select_network <id>
  ```

  Then forget and rejoin `jabuka` on the tablet. The manual fix lasts until the next activation of
  jabuka-ap, which the dispatcher fixes again. Leave `wifi-sec.pmf` at `disable` (what provision
  sets): the PMF setting does not remove WPA-PSK-SHA256.

- **/dev/fastnet missing:** compare `lsusb` against the IDs in `/etc/udev/rules.d/99-jabuka.rules`,
  fix the rule, then:

  ```bash
  sudo udevadm control --reload && sudo udevadm trigger
  ls -l /dev/fastnet
  ```

- **Ingest restarting in a loop** (`NRestarts` keeps climbing): read
  `journalctl -u jabuka-ingest-fastnet`. The old `cannot open /dev/fastnet: ... Invalid argument`
  loop (a tty left at 28800 that glibc 2.43 refused to re-apply) is fixed: the ingest resets the
  tty to a standard speed before configuring it (commit 6f5f5af). A missing device does NOT
  restart the ingest (it reports `device: missing` and reconnects); a task that dies does (exit 1,
  restarted by systemd), so look for `task ... died` in the journal.

- **Fastnet health missing or silent:** stop the ingest and run the probe (item l) with the bus
  connected. `NO BYTES`: check the wires are on the adapter's T/R+ and T/R- (not RXD), the adapter
  is in RS-485 mode, and the instruments are on. `BYTES BUT NO VALID FRAMES` (no_frames): swap the
  White and Green wires (A/B).

- **Clock blocked (routing time gate stays blocked):** the GPS needs a sky view. Check the fix:

  ```bash
  cgps -s
  chronyc sources
  ```

- **Disk filling up:** the logs live in `/var/lib/jabuka/logs` (`raw/`, `derived/`, `gps/`,
  `events/`, and `bus/` only with `jabuka-core --bus-log on`, off by default because it grows about
  4 GB/day at full bus load). One retention policy (`jabuka.ingest.retention`) covers the whole
  volume:
  - The total log budget is half of the data filesystem (override with
    `jabuka-core --log-budget-gb N`), split raw 50 %, derived 20 %, bus 15 %, gps 10 %, events 5 %.
    The core deletes the oldest files of a category that is over its share.
  - Raw history inside the newest 36 h is never deleted for budget reasons. On a 16 GB card the
    budget is about 7 GB, so raw (~0.5 GB/day) keeps about a week.
  - When free space drops below the reserve (1 GB, at most 10 % of the filesystem), both the core
    and the ingest delete the oldest files in the order bus, derived, gps, events, raw. Raw inside
    the 36 h floor goes only as a last resort, and it is counted (`raw_floor_breaches`).
  - The diagnostics page shows `disk` under Core (free space, usage per category, raw history in
    hours, deletions), and a red banner when the disk is low, being pruned for space, or the raw
    floor was breached. The Fastnet health box shows `disk_state` and `disk_free_bytes`.

## 7. Phase 4: soak, commissioning, freeze, spare SD

- 36 h soak (laptop and Pi, same `jabuka-logcheck` gate): [docs/SOAK.md](../docs/SOAK.md).
- On-boat commissioning runbook for 12–13 Nov (REL-03: wiring, the 12 Nov bus capture, AWA sign,
  tablet, race pack, course, degraded drills, go/no-go), rehearsable on the laptop with
  `bash scripts/commissioning-rehearsal.sh`: [docs/COMMISSIONING.md](../docs/COMMISSIONING.md).
- Spare SD card (clone, boot check, swap at sea) and the optional read-only overlay filesystem
  with its rollback: [docs/SPARE-SD.md](../docs/SPARE-SD.md).
- Feature freeze of 2026-11-11 (tag `race-2026`, wheelhouse, lock review, config-only changes
  afterwards, `bash scripts/freeze-check.sh`): [docs/FREEZE.md](../docs/FREEZE.md).

## 8. Weather on the Pi (laptop dead): sudo prerace

Use this when the laptop is dead or absent at the dock. The Pi carries its own copy of the
weather-prep tools in `/opt/jabuka-prep/venv`, separate from the app venv `/opt/jabuka/venv`.
Provision step g2 installs it, hash-locked and offline, from `deploy/wheelhouse/prep`, which
`bash scripts/build-wheelhouse.sh` builds with the rest of the wheelhouse. It never modifies the
app.

Check after provisioning:

```bash
/opt/jabuka-prep/venv/bin/python -c "import pygrib, shapely, netCDF4"
jabuka-prep-pi --help
```

One-time prerequisite: save the phone hotspot password with `sudo jabuka-wifi phone`, then go back
with `sudo jabuka-wifi ap` (see section 6).

**Main path:** `sudo prerace`. It:

1. runs detached as the unit `jabuka-prerace`, so an SSH session over the boat AP that drops does
   not stop it;
2. uses the phone hotspot only if the Pi has no internet, and always comes back to the `jabuka` AP
   at the end, even on failure;
3. copies the current pack to `/var/lib/jabuka/racepack.new`, then runs ICON-EU `wind` (fatal on
   error), EWAM `waves` (optional) and `check` there, as the `jabuka` user;
4. swaps the new pack in, keeps the previous one as `/var/lib/jabuka/racepack.prev`, and restarts
   jabuka-core.

Follow it and read the result:

```bash
journalctl -fu jabuka-prerace
sudo prerace status
```

- `OK` = the new pack is installed and jabuka-core restarted.
- `MÉTÉO INCOMPLÈTE` = installed anyway: read the coverage lines shown by `sudo prerace status`
  and the section "Reading the coverage report" of [docs/WEATHER-PACK.md](../docs/WEATHER-PACK.md).
- `ÉCHEC` = the old pack is untouched (the reason and the end of the log are in the status).

Cost and timing: about 100 MB of mobile data per ICON-EU run, plus a few MB for the waves. The Pi 3
is several times slower than the laptop, so start well before the weather window. The SSH session
drops when the Wi-Fi switches to the phone and again when it comes back; reconnect afterwards.

Organiser forecast: `sudo prerace --organiser FILE` also writes `wind_organiser` beside the pack,
unused. To route with it, rename it to `wind.npz` / `wind.json` as described in
[docs/WEATHER-PACK.md](../docs/WEATHER-PACK.md), then restart jabuka-core.

Rollback to the previous pack:

```bash
sudo mv /var/lib/jabuka/racepack /var/lib/jabuka/racepack.bad
sudo mv /var/lib/jabuka/racepack.prev /var/lib/jabuka/racepack
sudo systemctl restart jabuka-core
```

**Manual fallback** (if `prerace` itself fails):

```bash
sudo jabuka-wifi phone
sudo -u jabuka /opt/jabuka-prep/venv/bin/jabuka-prep wind --out /var/lib/jabuka/racepack --cache /var/lib/jabuka/cache/prep
sudo systemctl restart jabuka-core
sudo jabuka-wifi ap
```

- `--cache` is required: the default cache path (`var/cache/prep`) is relative to the current
  directory, which the `jabuka` user cannot write.
- The manual path writes the live pack in place (no staging copy, no `racepack.prev`).
- `jabuka-prep grib FILE` works the same way, with FILE readable by `jabuka` (e.g. copied to
  `/tmp`) and the same `--out` / `--cache`, optionally with `--name wind_organiser`.

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

2. On the Pi, over Ethernet:

   ```bash
   cd ~/jabuka
   sudo deploy/provision.sh --psk-file deploy/secrets.env
   ```

   Expected: the steps a-k run without `ERROR`. The last step brings up the access point and
   prints that a Wi-Fi SSH session would drop (yours is on Ethernet, so it stays).
   The script is idempotent: run it again after any change (for example a new wheelhouse).
   It needs internet only for `apt-get` and the fastnet2ip Plan B. With every apt package
   already installed, a re-run works offline.

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

g. **Tablet joins the AP.** On the tablet, forget other networks and turn mobile data off. Join
   `jabuka` with the passphrase, then open **http://10.42.0.1/**.

   Expected: the Jabuka diagnostics page, with values, sources and ages.

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

   Expected: a `NO BYTES` verdict (the adapter is fine, nothing is talking).

m. **Package lock review.** Read `deploy/requirements.lock` and confirm the 17 resolved names
   are exactly: annotated-doc, annotated-types, anyio, click, fastapi, h11, idna,
   opentelemetry-api, pydantic, pydantic-core, pyfastnet, pyserial, starlette, typing-extensions,
   typing-inspection, uvicorn, websockets. Flag any extra or unfamiliar name before the wheelhouse
   goes to the Pi.

## 5. Plan B: fastnet2ip and OpenCPN

Use this only when the Jabuka ingest is unusable. fastnet2ip runs as root and opens the port
read/write (pyserial), so the kernel-enforced read-only guarantee does not apply. Its 3.3.1 source
has no serial write call, but it is still a fallback, not the normal mode.

1. Start it. `Conflicts=` stops the Jabuka ingest automatically:

   ```bash
   sudo systemctl start fastnet2ip
   systemctl is-active fastnet2ip jabuka-ingest-fastnet
   ```

   Expected: `active` then `inactive`.

2. On the laptop, join the `jabuka` AP and set OpenCPN to a network connection: UDP, input,
   port 2002. NMEA 0183 sentences are broadcast to 10.42.0.255.

3. Return to Jabuka:

   ```bash
   sudo systemctl start jabuka-ingest-fastnet
   ```

   Expected: fastnet2ip stops, and the ingest is active again. fastnet2ip is never enabled at
   boot.

## 6. Troubleshooting

- **AP missing (no `jabuka` network):** Wi-Fi may still be rfkill-blocked because no country is
  set.

  ```bash
  rfkill list
  sudo raspi-config nonint do_wifi_country HR
  sudo nmcli connection up jabuka-ap
  ```

- **Tablet cannot join, or joins and drops:** some clients do not get along with PMF disabled or
  enabled on the Pi's brcmfmac radio. Toggle it, then forget and rejoin on the tablet:

  ```bash
  sudo nmcli connection modify jabuka-ap wifi-sec.pmf default
  sudo nmcli connection up jabuka-ap
  ```

- **/dev/fastnet missing:** compare `lsusb` against the IDs in `/etc/udev/rules.d/99-jabuka.rules`,
  fix the rule, then:

  ```bash
  sudo udevadm control --reload && sudo udevadm trigger
  ls -l /dev/fastnet
  ```

- **Ingest restarting in a loop** (`NRestarts` keeps climbing,
  `journalctl -u jabuka-ingest-fastnet` shows `cannot open /dev/fastnet: ... Invalid argument`):
  the tty may be holding a 28800 setting that the C library refuses to re-apply. Unplug and
  replug the DTECH, which resets the tty, and report it (01-04 SUMMARY, deferred item).

- **Fastnet health missing or silent:** stop the ingest and run the probe (item l) with the bus
  connected. `NO BYTES`: check the wires are on the adapter's T/R+ and T/R- (not RXD), the adapter
  is in RS-485 mode, and the instruments are on. `BYTES BUT NO VALID FRAMES` (no_frames): swap the
  White and Green wires (A/B).

- **Clock blocked (routing time gate stays blocked):** the GPS needs a sky view. Check the fix:

  ```bash
  cgps -s
  chronyc sources
  ```

- **Disk filling up:** the logs live in `/var/lib/jabuka/logs`. The raw and bus logs delete their
  oldest files when free space drops below 1 GB.

## 7. Deferred to Phase 4

- The 36 h soak test on the Pi, with the same `jabuka-logcheck` gate.
- The on-boat commissioning runbook (REL-03), including the AWA sign check and the 12 Nov bus
  capture.
- The decision on a read-only root / overlay filesystem, and cloning the spare SD card.

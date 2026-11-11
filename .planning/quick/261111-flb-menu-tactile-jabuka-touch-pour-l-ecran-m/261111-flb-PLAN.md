---
phase: quick-261111-flb
plan: 01
type: execute
wave: 1
depends_on: []
files_modified:
  - touch/jabuka_touch/__init__.py
  - touch/jabuka_touch/__main__.py
  - touch/jabuka_touch/config.py
  - touch/jabuka_touch/fb.py
  - touch/jabuka_touch/touchin.py
  - touch/jabuka_touch/console.py
  - touch/jabuka_touch/ui.py
  - touch/jabuka_touch/render.py
  - touch/jabuka_touch/actions.py
  - touch/jabuka_touch/status.py
  - touch/jabuka_touch/demo.py
  - touch/jabuka_touch/demo_wind.py
  - touch/jabuka_touch/calibrate.py
  - touch/jabuka_touch/app.py
  - touch/jabuka_touch/selftest.py
  - touch/jabuka-touch.service
  - touch/jabuka-touch
  - touch/jabuka-touch.example.json
  - touch/install.sh
  - touch/uninstall.sh
  - touch/README.md
  - tests/touch/conftest.py
  - tests/touch/test_fb.py
  - tests/touch/test_touchin.py
  - tests/touch/test_ui.py
  - tests/touch/test_actions.py
  - tests/touch/test_status.py
  - tests/touch/test_demo.py
  - tests/touch/test_tracer.py
  - tests/touch/test_render_selftest.py
  - tests/touch/test_install_files.py
  - tests/touch/test_isolation.py
  - scripts/check.sh
autonomous: true
requirements: [HELM-05, REL-03]

estimate:
  tokens: 180000
  raw_tokens: 180000
  tasks: 3
  confidence: low

must_haves:
  truths:
    - "On the Pi, `sudo bash touch/install.sh` (idempotent, re-runnable) installs the package to /opt/jabuka-touch (root-owned), the unit to /etc/systemd/system/jabuka-touch.service, the wrapper to /usr/local/sbin/jabuka-touch, creates /etc/jabuka-touch.json only when absent (calibration kept), then daemon-reload + enable + restart jabuka-touch; it never edits the boot partition, /opt/jabuka, deploy/ units or any jabuka-core/ingest unit; `sudo bash touch/uninstall.sh` returns to race mode if a demo runs, removes the menu and gives tty1 back to getty"
    - "jabuka-touch runs with the system /usr/bin/python3 only (Pillow, numpy, DejaVu from apt); nothing under touch/jabuka_touch imports jabuka except demo_wind.py, which is only ever executed by /opt/jabuka/venv/bin/python as user jabuka"
    - "The menu draws on the framebuffer found by name fb_ili9486 in /proc/fb, with width/height/bpp/stride read from /sys/class/graphics/fbN, as native little-endian RGB565; it renders only when the view changes and rewrites only the changed row band; tty1 is in KD_GRAPHICS while it runs and KD_TEXT is restored on normal exit, SIGTERM, crash and by ExecStopPost"
    - "The home screen shows, about once a second, ten big coloured tiles (green/orange/red, grey = unknown) with short French text: Fastnet bus, GPS + clock, wind source, weather pack, route, Wi-Fi (mode, SSID, client count), power (vcgencmd get_throttled now/past), CPU temperature, disk of /var/lib/jabuka, services jabuka-core/jabuka-ingest-fastnet/gpsd; the data comes read-only from GET /api/state and /api/nav on the core (127.0.0.1, 1 s timeout) and from short-timeout system commands on a background thread, and a core that does not answer shows red « cœur muet », never a frozen or crashed screen"
    - "Every risky action (prerace, Wi-Fi AP, Wi-Fi téléphone, démo, mode course, redémarrer services, terminal, redémarrer le Pi, éteindre) first shows a confirmation screen with big OUI/NON buttons that auto-cancels after 8 s; taps are ignored for 0.6 s after any screen change; every button is at least 80 px tall and no OUI button lies under the centre of a button that opens a confirmation"
    - "Actions run as argv lists (never through a shell) from a fixed whitelist of executables, with timeouts, one at a time on a worker thread that never blocks the display loop; jabuka-touch.service never Requires/BindsTo/PartOf jabuka-core, has Nice=10, a MemoryMax, Restart=on-failure, Conflicts=getty@tty1.service, so a menu crash never affects navigation"
    - "MÉTÉO / WI-FI screen: launches `prerace` (refused while a demo runs), shows its live journal (journalctl -u jabuka-prerace, last lines, refreshed) and the last result (prerace status / prerace-last.txt: résultat + code 0/3/2), switches `jabuka-wifi ap` / `jabuka-wifi phone` and shows `jabuka-wifi status`"
    - "DÉMO starts a simulated boat that the tablet sees at http://10.42.0.1: volatile drop-ins /run/systemd/system/{jabuka-core,jabuka-ingest-fastnet}.service.d/zz-jabuka-touch-demo.conf (named to sort after any operator drop-in such as the override.conf written by `systemctl edit`, since systemd applies drop-ins of /etc and /run in filename order) swap only --data-dir/--racepack/--clock sim/--gpsd 127.0.0.1:2948 (core) and --device/--data-dir (ingest) of the effective installed ExecStart, data in /var/lib/jabuka-demo (wiped on each start), the synthetic boat in a transient unit jabuka-demo-sim run as jabuka; /var/lib/jabuka (racepack, course.json, settings.json, bias.json) is only ever read; a big DÉMO banner is shown on every screen; MODE COURSE (or a reboot, since /run is volatile) restores the production units and verifies them active"
    - "A demo is never half-applied: after daemon-reload the EFFECTIVE ExecStart of each unit (fresh `systemctl cat` parse) must equal the demo argv before anything is restarted, and after the restart each unit's main process command line (/proc/<MainPID>/cmdline) must carry every demo argument (argv[1:], like the soak's runs_soak_argv); any mismatch (for example an operator drop-in sorting after ours) rolls back to race mode and shows « ÉCHEC démo »; when MODE COURSE has removed the drop-ins but a unit is still not active after 30 s, the screen says that rebooting the Pi (« redémarrer le Pi ») restores race mode"
    - "TERMINAL restores KD_TEXT and runs `systemctl --no-block start getty@tty1.service` (which stops the menu through Conflicts=); `sudo jabuka-touch` brings the menu back, `sudo jabuka-touch course` returns to race mode, `sudo jabuka-touch calibrate` recalibrates the touch panel (3 taps) into /etc/jabuka-touch.json; REDÉMARRER LE PI / ÉTEINDRE run `systemctl reboot` / `systemctl poweroff`"
    - "`bash scripts/check.sh` is green on both venvs with tests/touch included and ruff covering touch/ (the known flaky UI test test_switch_to_slovenian_then_english_persists_and_fits may be re-run alone); rendering is exercised by `python3 -m jabuka_touch selftest` under the system python (Pillow absent from the dev venvs, no package installed); `git diff --name-only 7c61a53 -- src deploy pyproject.toml` is empty (freeze-check F3/F4 unaffected); nothing is written to the Pi"
  artifacts:
    - path: "touch/jabuka_touch/fb.py"
      provides: "framebuffer discovery by name in /proc/fb, sysfs geometry, RGB565 conversion, row-band partial writes (FrameBuffer on a device or a plain file)"
      contains: "fb_ili9486"
    - path: "touch/jabuka_touch/touchin.py"
      provides: "64-bit input_event parsing (struct '=qqHHi', 24 bytes), device discovery by name, calibrated mapping with swap, inverse mapping, median tap detection with debounce"
      contains: "=qqHHi"
    - path: "touch/jabuka_touch/console.py"
      provides: "KDSETMODE KD_GRAPHICS / KD_TEXT on /dev/tty1 (0x4B3A), injectable ioctl"
      contains: "0x4B3A"
    - path: "touch/jabuka_touch/ui.py"
      provides: "Pillow-free screen state machine, layouts, hit-testing, confirmation with timeout and tap guard, view key"
      contains: "confirm"
    - path: "touch/jabuka_touch/render.py"
      provides: "Pillow rendering of every screen (day and night palettes, DÉMO banner)"
      contains: "DejaVuSans-Bold.ttf"
    - path: "touch/jabuka_touch/actions.py"
      provides: "whitelisted Runner (argv, timeouts, never raises), FakeRunner for tests, single-flight Worker, builders for system/prerace/Wi-Fi actions"
      contains: "getty@tty1.service"
    - path: "touch/jabuka_touch/status.py"
      provides: "pure parsers (get_throttled, iw info, station dump, is-active, chronyc tracking, prerace-last.txt, API JSON) and the background Collector producing a Snapshot of ten items"
      contains: "get_throttled"
    - path: "touch/jabuka_touch/demo.py"
      provides: "effective ExecStart parsing from `systemctl cat`, demo argv and drop-in rendering, demo pack assembly, start/stop sequences with effective-ExecStart and main-process verification, rollback, reboot hint"
      contains: "zz-jabuka-touch-demo.conf"
    - path: "touch/jabuka_touch/demo_wind.py"
      provides: "helper run by /opt/jabuka/venv/bin/python as jabuka: demo wind.npz via jabuka.soak.pack.write_wind"
      contains: "write_wind"
    - path: "touch/jabuka-touch.service"
      provides: "isolated systemd unit for the menu"
      contains: "Conflicts=getty@tty1.service"
    - path: "touch/install.sh"
      provides: "idempotent root installer (DESTDIR/SYSTEMCTL/TOUCH_PYTHON overrides for tests)"
      contains: "/opt/jabuka-touch"
    - path: "touch/README.md"
      provides: "short French manual: install, back to the menu from the terminal, race mode, calibration, uninstall, demo"
      contains: "sudo jabuka-touch"
    - path: "scripts/check.sh"
      provides: "gate: ruff check/format also cover touch (tests/touch collected by pytest testpaths)"
      contains: "touch"
  key_links:
    - from: "touch/jabuka_touch/app.py main loop"
      to: "/dev/fb1 (fb_ili9486) via fb.FrameBuffer.show"
      via: "render.render(view) -> fb.rgb565 -> os.pwrite of the changed row band only"
      pattern: "pwrite"
    - from: "touch/jabuka_touch/touchin.py TouchReader (ADS7846 Touchscreen event device)"
      to: "ui.UI.on_tap(x, y)"
      via: "median of samples between BTN_TOUCH 1 and 0, mapped with the config calibration (default 3936 227 268 3880, swap)"
      pattern: "on_tap"
    - from: "ui confirmation OUI"
      to: "actions.Worker.submit(action_id) -> Runner.run(argv, timeout)"
      via: "fixed registry of action ids, whitelist of executables, no shell"
      pattern: "ALLOWED"
    - from: "touch/jabuka_touch/status.py Collector"
      to: "jabuka-core GET /api/state and /api/nav on 127.0.0.1"
      via: "urllib with 1 s timeout; health.fastnet.state, health.gps, clock.time_valid, nav.wind.source, nav.route.{state,version,age_s,pack}"
      pattern: "/api/nav"
    - from: "touch/jabuka_touch/demo.py start sequence"
      to: "/run/systemd/system/jabuka-core.service.d/zz-jabuka-touch-demo.conf and jabuka-ingest-fastnet.service.d/zz-jabuka-touch-demo.conf"
      via: "ExecStart= reset + demo argv from the effective installed ExecStart + ReadWritePaths=-/var/lib/jabuka-demo, then daemon-reload, effective ExecStart re-parsed and compared to the demo argv (rollback on mismatch), restart, main-process cmdline check"
      pattern: "ReadWritePaths=-/var/lib/jabuka-demo"
    - from: "touch/jabuka-touch.service"
      to: "getty@tty1.service"
      via: "Conflicts= (Terminal: systemctl --no-block start getty@tty1.service stops the menu; `sudo jabuka-touch` starts it back)"
      pattern: "Conflicts=getty@tty1.service"
---

<objective>
Build "jabuka-touch", a French touchscreen menu for the MHS35 3.5" screen on the Pi 3B (480x320,
fbtft fb_ili9486, ADS7846 touch panel), so that on arriving at the boat the crew can check the
whole system at a glance and start the race, run prerace, switch Wi-Fi, run a demo, restart
services, open a terminal, reboot or power off with a finger and no laptop.

Purpose: the core value (trustworthy steer/tack advice) depends on a data chain that the crew
must be able to diagnose and recover on board without a laptop. The menu is strictly an
add-on: it reads the core's existing API and calls existing commands, and it can never take
navigation down.

Output: a self-contained top-level `touch/` directory (package `jabuka_touch`, systemd unit,
wrapper, install/uninstall scripts, French README), tests under `tests/touch/`, and the gate's
ruff lines extended to `touch`. Nothing under `src/`, `deploy/` or `pyproject.toml` changes
(code freeze 2026-11-11, docs/FREEZE.md). Nothing is written to the Pi: deployment and the
real-screen trial are done by the orchestrator afterwards.
</objective>

<execution_context>
@/home/drico/.claude/gsd-core/workflows/execute-plan.md
@/home/drico/.claude/gsd-core/templates/summary.md
</execution_context>

<context>
@.planning/STATE.md
@.claude/CLAUDE.md
@docs/FREEZE.md
@scripts/freeze-check.sh
@scripts/check.sh
@deploy/systemd/jabuka-core.service
@deploy/systemd/jabuka-ingest-fastnet.service
@deploy/prerace
@deploy/jabuka-wifi

<freeze_findings>
Verified by the planner in scripts/freeze-check.sh: F3/F4's git rule only diffs
`src deploy pyproject.toml ':(exclude)deploy/*.md'`; the code fingerprint covers src/jabuka and
the unit fingerprint deploy/systemd only. So `touch/`, `tests/touch/` and `scripts/` are NOT
frozen. F1 needs the tracked tree clean (commit everything you create) and F2 runs
`scripts/check.sh` (tests/touch must be green). docs/FREEZE.md lists src/jabuka, pyproject,
the lock and deploy/{systemd,udev,provision.sh,...} as frozen; scripts/ is not listed.
</freeze_findings>

<environment_findings>
- Laptop: `.venv` and `.venv313` are both Python 3.13.12 with numpy 2.5.4 and pytest, but
  WITHOUT Pillow. `/usr/bin/python3` (3.14.7) has Pillow 12.2 + numpy 2.4.4 but no pytest.
  DejaVu fonts are at /usr/share/fonts/truetype/dejavu/. Do NOT install anything (no Pillow in
  the venvs, no pyproject change): keep every module except render.py Pillow-free so the venv
  tests cover them, and exercise rendering through `python3 -m jabuka_touch selftest` run by
  `/usr/bin/python3` (from a pytest test via subprocess, skipped when that interpreter lacks
  Pillow). The Pi runs the same selftest with its system python (3.13, Pillow 11.1, numpy 2.2):
  use only long-stable Pillow/numpy APIs (ImageFont.truetype, ImageDraw.text/textlength/
  textbbox/rectangle/rounded_rectangle, ImageFont.load_default(size=) as fallback).
- pytest config: testpaths = ["tests"], `--import-mode=importlib`, no `__init__.py` in test
  dirs. tests/touch/conftest.py puts `<repo>/touch` at the front of sys.path so tests do
  `import jabuka_touch`.
- jabuka.tools.demo and jabuka.tools.rehearsal are NOT usable on the Pi: they import httpx
  (absent from deploy/requirements.lock) and their land mask/test map live in tests/fixtures
  (not in the wheel). jabuka.soak.pack IS usable there (numpy + jabuka.prep.wxpack + atomicio
  only): `write_wind(dest, root, start_utc, end_utc, *, twd, tws_kn, shift_deg_h=0.0,
  tws_factor=1.0, hours_before=2.0)` writes `wind.npz` + `wind.json` into dest (dest must be
  inside root), synchronous writes (background fsync is opt-in).
</environment_findings>

<interfaces>
Installed units on the Pi (read deploy/systemd/*.service; NEVER edit them):
- jabuka-core: `ExecStart=/opt/jabuka/venv/bin/jabuka-core --http-host 0.0.0.0 --http-port 80
  --data-dir /var/lib/jabuka --clock gps --gpsd 127.0.0.1:2947`; User=jabuka; ProtectSystem=strict;
  ReadWritePaths=/var/lib/jabuka; PrivateDevices=yes; core also accepts `--racepack DIR`
  (default <data-dir>/racepack).
- jabuka-ingest-fastnet: `ExecStart=/opt/jabuka/venv/bin/jabuka-ingest-fastnet --device
  /dev/fastnet --data-dir /var/lib/jabuka --udp 127.0.0.1:47100`; User=jabuka; ProtectSystem=strict;
  ReadWritePaths=/var/lib/jabuka; no PrivateDevices (a pty under /dev/pts opens fine). An
  operator drop-in may add `--awa-sign -1` (docs/FREEZE.md): always start from the EFFECTIVE
  ExecStart given by `systemctl cat`, never from a hardcoded line.
- Soak precedent to port (src/jabuka/soak/systemd.py lines 151-250, read it): `_service_items`
  (parse [Service] key=value, comment lines skipped), `unit_execstart` (an empty `ExecStart=`
  resets the list, exactly one must remain), `_set_flag` (replace `--flag value` or
  `--flag=value`, append when absent), `_quote` with `_SAFE = ^[A-Za-z0-9_@%+=:,./-]+$` and `%`
  doubled, `dropin_text` (`[Service]`, `ExecStart=`, `ExecStart=<argv>`). Soak drop-ins are named
  `50-jabuka-soak.conf`; ours are `zz-jabuka-touch-demo.conf` and must never touch theirs.
  systemd merges the drop-ins of /etc/systemd/system/<unit>.d and /run/systemd/system/<unit>.d
  in FILENAME order (a later `ExecStart=` reset wins): docs/FREEZE.md tells the operator to add
  `--awa-sign -1` with `sudo systemctl edit jabuka-ingest-fastnet`, i.e.
  /etc/systemd/system/jabuka-ingest-fastnet.service.d/override.conf, which would beat a
  `50-...` name. Hence the `zz-` prefix AND an explicit check of the effective ExecStart (the soak
  does the same with runs_soak_argv, src/jabuka/soak/systemd.py lines 458-475 and 658-668).
- jabuka-sim (`/opt/jabuka/venv/bin/jabuka-sim`, src/jabuka/sim/synth.py): `--mode pty --link
  PATH --speed X --duration S --twd D --tws KN --twa 45 --start LAT,LON --start-utc ISO
  --variation V --gpsd-port 2948 --wait-reader 30 --seed 1 --shift DEG_H --follow URL
  --follow-route --follow-nowait` (embedded fake gpsd on 127.0.0.1:PORT; --follow-nowait so a core
  restart never stalls the boat). Demo constants from src/jabuka/tools/demo.py and
  rehearsal.py: start 2026-11-13T18:00:00Z, TWD 161, TWS 12 kn, TWA 45, shift 6 deg/h,
  speed 2, start point = jabuka.nav.geo.offset(43.684627, 15.811626, radians(341), 2.0 nm)
  (geo.offset: lat2 = lat + d*cos(b)/60; lon2 = lon + d*sin(b)/(cos(radians((lat+lat2)/2))*60)),
  variation = default Settings().variation_deg = 4.7 (fresh demo data dir).
- Core API (local, Host 127.0.0.1 is accepted by the core's Host check):
  GET /api/state -> {"clock": {"kind", "time_valid", "routing_time_gate", "utc", ...},
  "health": {"fastnet": {"device": ok|missing|busy, "state": ok|silent|few_bytes|no_frames|noisy|
  missing|busy, "hint", "frames_per_s", "alive", "age_s", ...}, "gps": {"connected", "mode",
  "sats_used", "server", "alive", ...}, "router": {"pack_ok", "pack_reason", "version",
  "coverage": {"alerts", "warnings"}, ...}, "racepack": {...}}, "core": {"disk", "uptime_s", ...},
  "values": [...]}. ALIVE_S = 3 s.
  GET /api/nav -> {"wind": {"source": LIVE|LIVE_BG|MANUEL|GRIB|NONE, "stale", "tws_kn", ...} or
  null, "route": {"state": ok|computing|outdated|blocked_clock|no_pack|no_position|no_course|
  disabled|failed, "reason", "version", "age_s", "computed_utc", "pack": {"ok", "model", "run",
  "alerts": [...]}, ...} or absent, "utc", ...}. Parse everything defensively (.get + type checks).
- prerace (/usr/local/sbin/prerace, root): `prerace` launches the detached unit jabuka-prerace
  and returns at once (exit 1 "déjà en cours" when running, 2 bad args); `prerace status` prints
  "en cours : ..." when running, then /var/lib/jabuka/prerace-last.txt (lines "prerace : <UTC>",
  "résultat : <OK|MÉTÉO INCOMPLÈTE|ÉCHEC ...>", "code : 0|3|2", "vent : ...", "vagues : ...",
  "Wi-Fi : ...", coverage tail). Prerace itself switches to the phone hotspot and back.
- jabuka-wifi (/usr/local/sbin/jabuka-wifi, root): `status` (French lines "Wi-Fi : ...",
  "Adresse wlan0 : ...", "Profil téléphone ..."), `ap` and `phone` detach the switch and return
  at once; `phone` without a saved profile asks a password on /dev/tty and fails without one
  (show the hint: « sudo jabuka-wifi phone depuis le Terminal pour enregistrer le mot de passe »).
- System formats: `vcgencmd get_throttled` -> `throttled=0x50005` (bit0 under-voltage now,
  bit16 under-voltage occurred, bits 1-3 / 17-19 capping/throttling/soft-temp); `iw dev wlan0
  info` -> lines `ssid <name>`, `type AP|managed`; `iw dev wlan0 station dump` -> one
  `Station <mac> (on wlan0)` line per client; `systemctl is-active A B C` prints one state per
  line and exits non-zero when any is not active (parse stdout, rc is not an error);
  `chronyc -n -c tracking` -> CSV whose 2nd field is the reference name (e.g. GPS) and last field
  the leap status ("Normal" / "Not synchronised"); /sys/class/thermal/thermal_zone0/temp is
  milli-degC; /proc/fb lines are `<N> <name>`; /sys/class/graphics/fbN/{virtual_size "480,320",
  bits_per_pixel "16", stride "960"}; input device names in /sys/class/input/eventN/device/name.
- Linux constants: input_event on 64-bit = struct '=qqHHi' (24 bytes); EV_SYN 0, EV_KEY 1,
  EV_ABS 3, SYN_REPORT 0, ABS_X 0, ABS_Y 1, ABS_PRESSURE 24, BTN_TOUCH 330. KDSETMODE 0x4B3A,
  KD_TEXT 0, KD_GRAPHICS 1.
- Touch calibration (goodtft, rotate=90, xorg evdev semantics: swap first, then calibrate):
  x_min 3936, x_max 227, y_min 268, y_max 3880, swap_xy true. Mapping: (a, b) = (raw_y, raw_x)
  when swap else (raw_x, raw_y); x = (a - x_min) / (x_max - x_min) * (W - 1); y = (b - y_min) /
  (y_max - y_min) * (H - 1); clamp to the screen.
</interfaces>
</context>

<tasks>

<task type="tracer" tdd="true">
  <name>Task 1: Tracer: tap SYSTÈME -> REDÉMARRER SERVICES -> OUI runs the whitelisted systemctl restart, drawn on the framebuffer (program only; packaging comes in task 3)</name>
  <files>touch/jabuka_touch/__init__.py, touch/jabuka_touch/__main__.py, touch/jabuka_touch/config.py, touch/jabuka_touch/fb.py, touch/jabuka_touch/touchin.py, touch/jabuka_touch/console.py, touch/jabuka_touch/ui.py, touch/jabuka_touch/render.py, touch/jabuka_touch/actions.py, touch/jabuka_touch/status.py, touch/jabuka_touch/app.py, touch/jabuka_touch/selftest.py, tests/touch/conftest.py, tests/touch/test_fb.py, tests/touch/test_touchin.py, tests/touch/test_ui.py, tests/touch/test_actions.py, tests/touch/test_tracer.py, tests/touch/test_render_selftest.py, tests/touch/test_isolation.py, scripts/check.sh</files>
  <read_first>
    - scripts/freeze-check.sh (lines 1-30 and the F3 git rule) and docs/FREEZE.md: confirm touch/, tests/touch/, scripts/ are outside the frozen set (see freeze_findings above)
    - scripts/check.sh
  </read_first>
  <behavior>
    - fb: /proc/fb text "0 vc4drmfb\n1 fb_ili9486\n" -> index 1; missing name -> None; geometry read from a fake sysfs dir (480x320, 16 bpp, stride 960); rgb565 of white/red/green/blue/(8,4,8) = 0xFFFF/0xF800/0x07E0/0x001F/0x0821 as little-endian uint16; FrameBuffer over a plain file: first show writes the whole frame, an identical frame writes nothing (returns None), a change confined to rows 100-119 writes only that band at offset 100*stride (returns (100, 120)); stride larger than W*2 keeps the padding untouched; bpp other than 16 is refused with a clear error
    - touchin: parse_events on packed '=qqHHi' records, a trailing partial record is kept for the next read; a press (BTN_TOUCH 1, ABS_X/ABS_Y + SYN_REPORT samples, BTN_TOUCH 0) yields one tap at the median sample mapped through the calibration; the default calibration maps raw (x=268, y=3936) -> (0, 0) and raw (x=3880, y=227) -> (479, 319); out-of-range raws clamp; screen_to_raw is the inverse of the mapping within 1 px; a second tap within debounce_s (0.25) is dropped; a press without coordinates yields nothing; find_device picks the event node whose sysfs name equals "ADS7846 Touchscreen"
    - console: graphics() then text() call ioctl(fd, 0x4B3A, 1) then (fd, 0x4B3A, 0) through an injected ioctl; text() never raises (missing tty is logged)
    - ui (no Pillow): home -> tap on SYSTÈME -> screen "system"; tap REDÉMARRER SERVICES -> screen "confirm" for action restart_services; tap NON -> back to "system" and nothing submitted; tap OUI (after the 0.6 s guard) -> submit("restart_services") and back; a confirmation left alone 8 s returns to the previous screen without submitting; a tap 0.3 s after a screen change is ignored; while the worker is busy the action buttons are disabled (taps ignored) but navigation works; every button of every screen is >= 80 px tall and inside the screen; no OUI rect contains the centre of any button that opens a confirmation; view_key is equal for identical inputs and changes when the screen, snapshot version, minute or busy state change
    - actions: restart_services argv = systemctl restart jabuka-ingest-fastnet.service jabuka-core.service; reboot = systemctl reboot; poweroff = systemctl poweroff; terminal = systemctl --no-block start getty@tty1.service (after console.text()); Runner refuses an executable outside ALLOWED or a non-str argument (ValueError, a programming error) and otherwise never raises: missing binary -> rc None + "introuvable", TimeoutExpired -> timed_out True; Worker runs one action at a time (second submit while busy returns False) and records ActionResult(id, title, state running|ok|fail, lines)
    - tracer (in-process, fake renderer, no Pillow): App fed raw input bytes for the three taps, FileFrameBuffer in tmp, FakeRunner, injected clock -> FakeRunner.calls == [restart argv]; the framebuffer file was written
    - selftest (system python with Pillow, via subprocess): `python3 -m jabuka_touch selftest --out DIR` exits 0, writes one PNG per screen state and runs the same tracer scenario with the real renderer
  </behavior>
  <action>
Create the self-contained package `touch/jabuka_touch/` (system python only; it never imports jabuka). Packaging (unit file, wrapper, example config, install.sh, uninstall.sh and their tests) is NOT part of this task: it comes in task 3, so this executor context stays on the program itself. Keep modules small and Pillow-free except render.py (and selftest.py, which imports render lazily). All filesystem/device paths, the clock, the ioctl function, the subprocess runner and the HTTP fetcher are injectable so tests run on the laptop with tmp paths.

config.py: dataclasses for the touch calibration (x_min 3936, x_max 227, y_min 268, y_max 3880, swap_xy true, device_name "ADS7846 Touchscreen", debounce_s 0.25), fb_name "fb_ili9486", core_url "http://127.0.0.1", night false, confirm_timeout_s 8, tap_guard_s 0.6 and a demo block (speed 2, shift_deg_h 6, start_utc "2026-11-13T18:00:00+00:00"). load(path) reads JSON, keeps defaults for missing keys, ignores (and logs) wrong types/out-of-range values and a corrupt file; save(path, cfg) writes atomically (tmp + os.replace, 0644). defaults_dict() returns the defaults as a JSON-ready dict (task 3 writes the example config from it and tests the equality).

fb.py: find_fb(proc_fb_text, name) -> index or None; read_geometry(sysfs_dir) -> (width, height, bpp, stride) from virtual_size, bits_per_pixel, stride; rgb565(array HxWx3 uint8) -> HxW uint16 little-endian ((r>>3)<<11 | (g>>2)<<5 | b>>3); class FrameBuffer(path, width, height, stride, bpp) opening O_RDWR, keeping the previous frame, show(rgb_array) -> written row band (y0, y1) or None, writing rows y0..y1 with os.pwrite at y0*stride (each row padded to stride when stride > 2*W, padding bytes preserved by reading them once at open). Only 16 bpp is supported (clear error otherwise). open_display(paths, cfg) locates /dev/fbN by name each time it is called so the app can retry every 10 s when the fb is missing.

touchin.py: EVENT_FMT "=qqHHi" (assert calcsize 24); parse_events(buffer) -> (events, remainder); Calibration.map(raw_x, raw_y, W, H) and screen_to_raw(x, y, W, H) per the interfaces formula (swap first, then calibrate, clamp); TapDetector.feed(event, now) collecting (raw_x, raw_y) at each SYN_REPORT while BTN_TOUCH is down (ABS_PRESSURE > 0 as fallback when the device never sends BTN_TOUCH), emitting on release one tap at the median sample (drop the last sample when >= 3: release glitch), dropping taps closer than debounce_s to the previous one; find_device(sys_input_dir, name) -> /dev/input/eventN path; TouchReader(path) non-blocking fd with poll(timeout) returning mapped taps, reopening every 5 s when the device is missing (never crashes the loop).

console.py: Console(tty_path "/dev/tty1", ioctl=fcntl.ioctl) with graphics() and text() using KDSETMODE 0x4B3A (KD_GRAPHICS 1 / KD_TEXT 0); text() swallows and logs OSError. Never call VT_ACTIVATE or switch VTs: logind could spawn autovt@tty1 (= getty@tty1), which conflicts with the menu and would stop it.

ui.py (no Pillow): screen ids home, details, prep, journal, demo, system, confirm. Button(id, rect, label, kind nav|action, risky). Layout for 480x320 computed from W/H: header band 0-36; home = ten tiles in 2 columns x 5 rows over 36-236 (tapping any tile opens details) and a bottom row of three 84 px buttons MÉTÉO / WI-FI, DÉMO, SYSTÈME; system = two rows of three buttons (REDÉMARRER SERVICES, TERMINAL, NUIT or JOUR / RETOUR, REDÉMARRER LE PI, ÉTEINDRE); prep, journal, demo and details screens exist as navigable placeholders here with a RETOUR button (filled in tasks 2 and 3); confirm = title + detail + countdown text with NON (left) and OUI (right) placed so that no OUI rect contains the centre of any confirmation-opening button on any screen. UI(clock, cfg, submit, is_busy): on_tap(x, y) ignores taps within tap_guard_s of the last screen change, opens the confirmation for RISKY action ids (prerace, wifi_ap, wifi_phone, demo_start, race_mode, restart_services, terminal, reboot, poweroff), submits non-risky ones (night_toggle) directly, refuses action taps while busy; tick() auto-cancels a confirmation after confirm_timeout_s; view_key(snapshot) is a hashable tuple of everything the renderer draws (screen, confirmation id and remaining whole seconds, snapshot version, local HH:MM, busy, last action result, night, demo flag). French confirmation texts: « Redémarrer les services Jabuka ? » / « Navigation coupée ~30 s. »; « Quitter le menu pour le terminal ? » / « Retour au menu : sudo jabuka-touch (clavier USB) ou redémarrer le Pi. »; « Redémarrer le Pi ? » / « ~1 min sans navigation. »; « ÉTEINDRE le Pi ? » / « Attendre ~20 s avant de couper le courant. » (the other actions' texts come in tasks 2 and 3).

render.py (Pillow): render(view, W, H) -> HxWx3 uint8 numpy array. DejaVuSans-Bold.ttf / DejaVuSans.ttf / DejaVuSansMono.ttf from /usr/share/fonts/truetype/dejavu with ImageFont.load_default(size=) fallback. Strong contrast: day = white text on dark grey/black, tiles filled green #1b7f3a / orange #d97706 / red #c62828 / grey #555 with white bold text ~20 px; buttons with 22 px bold labels that fit their rect (shrink to 16 px, then split on spaces into two lines; `\n` in labels allowed); header shows « JABUKA », the mode and local HH:MM; while demo is active the whole header is a magenta (#c000c0) banner « DÉMO — bateau simulé » on every screen; when the snapshot is older than 10 s the header shows « ÉTAT FIGÉ » in red; a busy action shows « … » with its title. Night palette (cfg.night): black background, dark-red text, dimmed tile colours.

status.py (minimal here, completed in task 2): Item(key, label, level ok|warn|bad|unknown, short, detail), Snapshot(items, version, t, demo=False, prerace_running=False, extra={}), parse_is_active(stdout, units) and a Collector thread skeleton (start/stop/latest, interval, every collect step wrapped so an exception only turns that item unknown) that fills the SERVICES tile from `systemctl is-active jabuka-core.service jabuka-ingest-fastnet.service gpsd.service` and leaves the nine other tiles unknown.

actions.py: ALLOWED = {systemctl, systemd-run, journalctl, prerace, jabuka-wifi, runuser, nmcli, iw, vcgencmd, chronyc} (basename of argv[0]; prerace and jabuka-wifi resolved under /usr/local/sbin); Runner.run(argv, timeout) uses subprocess.run with an argv list, stdin DEVNULL, capture_output, text, a fixed env (PATH=/usr/local/sbin:/usr/local/bin:/usr/sbin:/usr/bin:/sbin:/bin, LANG=C.UTF-8), never a shell, returns CmdResult(rc, out, err, timed_out, error) and never raises except ValueError for a non-whitelisted executable or non-str argument; FakeRunner(responses) records calls; builders for restart_services (timeout 90 s), reboot, poweroff (30 s), terminal (console.text() first, then the --no-block getty start); Worker(registry) single-flight thread with busy and last ActionResult; night_toggle flips cfg.night and saves the config.

app.py: App(cfg, paths, display_factory, touch_reader, collector, worker, ui, renderer, clock) main loop: poll touch with a timeout of at most 0.2 s, feed taps to ui, ui.tick(), and when view_key changed render and fb.show (only the changed band hits SPI); SIGTERM/SIGINT set a stop flag; console.graphics() at start and console.text() in a finally (also on exceptions, then exit 1 so Restart=on-failure applies); fb or touch missing -> keep running and retry (log once). Logging to stderr (journal).

__main__.py: subcommands run (default), restore-console (KD_TEXT on /dev/tty1, exit 0 always), selftest --out DIR, status (one collection pass printed as French text lines, for the terminal); task 2 adds calibrate, task 3 adds race-mode.

selftest.py: renders every screen state (home day/night, home with demo banner, details, prep, journal, demo, system, each confirmation) to DIR/<name>.png with the real renderer and a fake snapshot of ten mixed-level items, then replays the tracer scenario (raw input events built with screen_to_raw written to a file read by TouchReader, FileFrameBuffer in DIR, FakeRunner, injected clock advancing past the tap guard) and asserts the restart argv was the only call and that the DÉMO header pixels are magenta; prints « selftest : ok (N écrans) » and exits 0, else prints the failure and exits 1. Tasks 2 and 3 extend it with their screens.

Tests (tests/touch/): conftest.py (sys.path insert of <repo>/touch, fixtures: fake sysfs/proc trees, FakeRunner, manual clock); test_fb.py, test_touchin.py, test_ui.py, test_actions.py, test_tracer.py per the behavior block; test_render_selftest.py runs `/usr/bin/python3 -m jabuka_touch selftest --out tmp` with cwd <repo>/touch (skip with a clear reason when /usr/bin/python3 is missing or cannot import PIL and numpy; in-process instead when PIL is importable) and asserts rc 0 and the PNGs exist; test_isolation.py walks the AST of every touch/jabuka_touch/*.py except demo_wind.py and fails on any import of the jabuka package (module name `jabuka` or starting with `jabuka.`; `jabuka_touch` is of course allowed), on os.system/os.popen, and on any call passing shell=<anything truthy> (AST-based, so comments never trip it).

scripts/check.sh: extend the two ruff lines to `src tests touch` (pytest already collects tests/touch through testpaths). Do not touch scripts/bootstrap-dev.sh and install nothing.

Commit (stage the explicit paths only): `feat(touch): menu tactile jabuka-touch, traceur écran + toucher + redémarrage des services` ending with the Co-Authored-By line.
  </action>
  <verify>
    <automated>cd /home/drico/git/jabuka && .venv313/bin/python -m pytest -q -rs tests/touch && .venv/bin/ruff check touch tests/touch && .venv/bin/ruff format --check touch tests/touch && D=$(mktemp -d) && (cd touch && /usr/bin/python3 -m jabuka_touch selftest --out "$D") && ls "$D"/*.png | wc -l</automated>
  </verify>
  <done>tests/touch green on .venv313 with no skip of test_render_selftest on this laptop (system python has Pillow); the selftest prints « selftest : ok » and writes the PNGs; ruff clean on touch and tests/touch; nothing under src/, deploy/, pyproject.toml changed; committed by explicit paths.</done>
</task>

<task type="auto" tdd="true">
  <name>Task 2: Full status at a glance (ten tiles + details), the MÉTÉO / WI-FI screen (prerace with live journal and result, Wi-Fi AP/phone/status) and touch calibration</name>
  <files>touch/jabuka_touch/status.py, touch/jabuka_touch/ui.py, touch/jabuka_touch/render.py, touch/jabuka_touch/actions.py, touch/jabuka_touch/app.py, touch/jabuka_touch/selftest.py, touch/jabuka_touch/calibrate.py, touch/jabuka_touch/__main__.py, tests/touch/test_status.py, tests/touch/test_ui.py, tests/touch/test_actions.py, tests/touch/test_touchin.py</files>
  <read_first>
    - deploy/prerace (launch, status, prerace-last.txt format, exit codes 0/3/2, unit jabuka-prerace)
    - deploy/jabuka-wifi (status text, ap/phone detach, phone profile prompt on /dev/tty)
    - src/jabuka/ingest/bus_health.py (bus states) and src/jabuka/core/main.py diag_message (lines 235-265)
    - src/jabuka/core/router_service.py lines 1443-1545 (route block and router health shapes)
    - src/jabuka/core/nav_service.py lines 118-140 and 200-215 (nav envelope, wind block)
  </read_first>
  <behavior>
    - parse_throttled: "throttled=0x0" -> ok; "0x50005" -> bad « sous-tension ! »; "0x50000" -> warn « sous-tension passée »; garbage -> unknown
    - parse_iw_info: AP with ssid jabuka -> mode ap; managed with ssid Noway_nomap -> mode phone; empty -> none; parse_station_dump counts `Station ` lines (2 stations -> 2, empty -> 0)
    - parse_chrony_tracking: CSV with name GPS and leap Normal -> synced; "Not synchronised" -> not synced; garbage -> unknown
    - parse_prerace_last: the file text from deploy/prerace write_result -> (date, résultat, code 0/3/2); "en cours" first line -> running
    - API items: fastnet state ok + alive -> green; silent/few_bytes/no_frames/noisy -> orange with the state; missing/busy or alive false or no fastnet health -> red; gps connected mode 3 + clock.time_valid -> green « 3D 9 sat »; fix but time_valid false -> orange « horloge en attente »; mode < 2 or not connected -> red; wind LIVE/LIVE_BG -> green, MANUEL/GRIB or stale -> orange, NONE or null -> red; route ok -> green « v12 · 3 min »; computing/outdated/no_course/disabled -> orange; failed/no_pack/no_position/blocked_clock -> red with reason; pack ok without alerts -> green « <model> <run> », alerts -> orange (first alert in details), ok false -> red; API unreachable (fetch returns None) -> those five tiles red « cœur muet »
    - temperature < 70 green, 70-79 orange, >= 80 red; disk free > 20 % green, 10-20 % orange, < 10 % red, shown as « x,x Go libres »; services all active -> green, else red naming the inactive ones
    - Collector.collect_once with a FakeRunner and fake fetch returns a Snapshot of exactly ten items in a fixed order; when every command raises, times out or is missing and the API is down it still returns ten items (unknown/red), never raises; extra queries (journal_prerace, prerace_status, wifi_status) are only run while requested
    - ui/actions: MÉTÉO / WI-FI screen buttons LANCER PRERACE, JOURNAL, WI-FI BATEAU, WI-FI TÉLÉPHONE, RETOUR; prerace argv = prerace (timeout 30 s), refused with « Démo en cours : revenir en mode course avant prerace » while demo is active; wifi_ap = jabuka-wifi ap, wifi_phone = jabuka-wifi phone (timeout 30 s); a failing phone switch shows the code, the last output line and the profile hint; journal screen requests journalctl -u jabuka-prerace.service -n 10 --no-pager -o cat and shows it, with a RÉSULTAT button switching the text to `prerace status`
    - calibration: solve_calibration from three synthetic taps generated with the default calibration at (40,40), (W-40,40), (40,H-40) recovers x_min/x_max/y_min/y_max within 2 raw units and swap_xy true; non-swapped synthetic taps give swap_xy false; saving keeps the other config keys
  </behavior>
  <action>
Complete status.py with pure parsers and the item builders for the ten tiles, in this fixed order and with these labels: BUS, GPS, VENT, MÉTÉO, ROUTE, WI-FI, ALIM, TEMP., DISQUE, SERVICES. Short texts stay within one tile line (about 14 characters, the renderer truncates with an ellipsis anyway); details carry the longer French explanation (fastnet hint, frames/s, gps server and satellites, chrony reference and leap status, coverage alert, route reason, SSID and clients, throttled hex, °C, free bytes, unit states). Read the core API (cfg.core_url + /api/state and /api/nav) with urllib.request, 1 s timeout, JSON objects only (anything else counts as unreachable); fetch errors never propagate. The GPS tile combines health.gps (connected, mode, sats_used) with clock.time_valid from /api/state and the chrony tracking line; the MÉTÉO tile reads nav.route.pack (ok, model, run, alerts) and health.router.pack_reason; the ROUTE tile formats age_s in minutes. System inputs: `systemctl is-active jabuka-core.service jabuka-ingest-fastnet.service gpsd.service` (stdout parsed even when rc is non-zero), `vcgencmd get_throttled`, `iw dev wlan0 info`, `iw dev wlan0 station dump`, `chronyc -n -c tracking`, `systemctl is-active jabuka-prerace.service`, /sys/class/thermal/thermal_zone0/temp, os.statvfs of /var/lib/jabuka, and /var/lib/jabuka/prerace-last.txt read directly (root can read it). Each command has a 2 s timeout. Collector cadence: API every 1 s, system commands every 5 s, extra queries every 3 s while requested by the UI (set_extra(names)); it publishes an immutable Snapshot with an incrementing version only when the content changed (the renderer then has nothing to redraw otherwise), plus a demo flag (presence of the demo drop-in file, path from paths; task 3 writes it) and the prerace running flag.

ui.py/render.py: the details screen lists the ten items' details in DejaVuSans 15 px (one line each, truncated to the width) with RETOUR; the home tiles render level colours and short texts; the prep screen (MÉTÉO / WI-FI) shows an info band of three lines (« Prerace : <en cours | résultat, date, code> », « Wi-Fi : <point d'accès jabuka · N clients | téléphone SSID | aucun> », last action result) and the buttons LANCER PRERACE, JOURNAL, WI-FI BATEAU, WI-FI TÉLÉPHONE, RETOUR, all >= 80 px tall; the journal screen shows up to ten lines of DejaVuSansMono 14 px from the requested query, with RÉSULTAT (switches to the prerace status text) and RETOUR; opening it calls collector.set_extra({"journal_prerace"}) and leaving it clears the request; while the prep screen is open the wifi_status query feeds its Wi-Fi line from `jabuka-wifi status`. Confirmation texts: « Lancer prerace ? » / « Télécharge la météo par le partage du téléphone : Wi-Fi bateau coupé 10 à 30 min. »; « Revenir au Wi-Fi bateau (jabuka) ? » / « Les tablettes se reconnectent à jabuka. »; « Passer sur le partage du téléphone ? » / « Les tablettes perdent la connexion. Retour : WI-FI BATEAU ou redémarrer. ». After a successful prerace launch the UI switches to the journal screen.

actions.py: builders prerace, wifi_ap, wifi_phone as argv lists of the whitelisted executables (absolute /usr/local/sbin paths), each result line list = the command's last output lines (stdout then stderr) so the result band shows what the script said; prerace is refused while the demo flag is set (Wi-Fi switching stays allowed during a demo).

selftest.py: add the prep, journal (with sample journal lines) and details screens and the three new confirmations to the PNG set; assert the five API tiles are red when the fake fetch is down; render the calibration cross screen too.

calibrate.py: solve_calibration(targets, raws, W, H) -> Calibration (swap decided by which raw axis moves most between the first two targets, then linear extrapolation of each axis to pixel 0 and W-1 / H-1); run_calibration(display, reader, console, cfg_path) draws a large cross at each of the three targets in turn with a French instruction (« Touchez le centre de la croix »), takes the median raw of each press (raw, unmapped: TouchReader exposes raw taps for this), shows the result and saves it into the touch section of /etc/jabuka-touch.json (other keys kept, config.save). __main__ gains `calibrate` (KD_GRAPHICS during the procedure, KD_TEXT after, also on error).

Tests: test_status.py per the behavior block, with API fixtures written as Python dicts that follow the shapes in the interfaces block (one healthy boat, one degraded, one with the API down); extend test_ui.py (prep/journal/details navigation, extra-query requests on enter/leave, button heights, OUI placement), test_actions.py (prerace/wifi argv, demo refusal, failure lines) and test_touchin.py (calibration cases).

Commit by explicit paths: `feat(touch): état d'un coup d'œil (10 voyants), écran météo et Wi-Fi (prerace, journal, bascule), calibration` with the Co-Authored-By line.
  </action>
  <verify>
    <automated>cd /home/drico/git/jabuka && .venv313/bin/python -m pytest -q -rs tests/touch && .venv/bin/ruff check touch tests/touch && .venv/bin/ruff format --check touch tests/touch && D=$(mktemp -d) && (cd touch && /usr/bin/python3 -m jabuka_touch selftest --out "$D")</automated>
  </verify>
  <done>Ten tiles with correct levels for healthy/degraded/API-down fixtures; collector never raises and stays within its timeouts; prep/journal/details screens navigable and rendered by the selftest; prerace/Wi-Fi actions confirmed, whitelisted and refused for prerace during a demo; calibration solver recovers the default and the calibrate subcommand exists; committed by explicit paths.</done>
</task>

<task type="auto" tdd="true">
  <name>Task 3: DÉMO / MODE COURSE with verified volatile drop-ins and an isolated demo pack, packaging (unit, wrapper, install/uninstall), README, full gate</name>
  <files>touch/jabuka_touch/demo.py, touch/jabuka_touch/demo_wind.py, touch/jabuka_touch/ui.py, touch/jabuka_touch/render.py, touch/jabuka_touch/actions.py, touch/jabuka_touch/app.py, touch/jabuka_touch/__main__.py, touch/jabuka_touch/selftest.py, touch/jabuka-touch.service, touch/jabuka-touch, touch/jabuka-touch.example.json, touch/install.sh, touch/uninstall.sh, touch/README.md, tests/touch/test_demo.py, tests/touch/test_ui.py, tests/touch/test_install_files.py</files>
  <read_first>
    - src/jabuka/soak/systemd.py lines 151-250 (drop-in parsing and rendering to port), 452-475 (install: drop-ins, daemon-reload, restart) and 658-668 (runs_soak_argv: the main process cmdline must carry every soak argument), 984-1020 (cleanup_system: only its own drop-ins, restart, verify)
    - docs/FREEZE.md line 28 (operator `sudo systemctl edit jabuka-ingest-fastnet` for --awa-sign -1, i.e. an override.conf drop-in in /etc)
    - deploy/systemd/jabuka-core.service and deploy/systemd/jabuka-ingest-fastnet.service (unit style, hardening, comments, for the menu's own unit)
    - tests/deploy/test_provisioning_files.py lines 1-40 (how repo tests run a shell script as a dry run)
    - src/jabuka/soak/pack.py (write_wind, inside)
    - src/jabuka/tools/demo.py (demo stack, constants, build_pack choice of map files) and src/jabuka/tools/rehearsal.py lines 533-660 (constants, write_boat_pack, synth_args)
    - src/jabuka/route/racepack.py lines 30-45 (race-pack file names: wind.npz, waves.npz, current.npz, landmask.npz, polar.json)
    - src/jabuka/nav/geo.py offset and src/jabuka/nav/settings.py variation_deg default
  </read_first>
  <behavior>
    - effective_execstart on `systemctl cat` text built from the repo's deploy/systemd/jabuka-ingest-fastnet.service plus an operator drop-in that resets ExecStart and adds --awa-sign -1 returns that drop-in's argv (the operator flag survives); zero or two effective ExecStart, or a prefixed value (-, @, +, !, :), raise
    - demo_argv(core) replaces exactly --data-dir /var/lib/jabuka-demo/data, --racepack /var/lib/jabuka-demo/racepack, --clock sim, --gpsd 127.0.0.1:2948 and keeps --http-host/--http-port; demo_argv(ingest) replaces exactly --device /run/jabuka-demo/fastnet-pty and --data-dir and keeps --udp and --awa-sign; gpsd port 2947 is refused; dropin_text has `ExecStart=` then the quoted argv then `ReadWritePaths=-/var/lib/jabuka-demo`; unsafe tokens raise
    - demo pack: from a fake race pack containing race.pmtiles, coastline.geojson, seamarks.geojson, racepack.json, polar.json, landmask.npz, landmask.json, wind.npz, wind.json, waves.npz, current.npz, coverage.txt, the demo pack gets the seven map/polar/mask files and none of wind*, waves*, current*, coverage.txt; the race pack bytes and mtimes are unchanged afterwards; a pack without landmask.npz still builds with the warning « pas de masque terre : la route ne sera pas calculée »
    - start_demo with FakeRunner, tmp paths and a fake fetch returns the ordered calls: systemctl stop + reset-failed jabuka-demo-sim.service, runuser -u jabuka -- /opt/jabuka/venv/bin/python -I <touch>/jabuka_touch/demo_wind.py ..., systemctl cat for both units, systemctl daemon-reload, systemctl cat for both units again (effective ExecStart re-parsed and equal to the demo argv), systemd-run --unit=jabuka-demo-sim --collect -p User=jabuka -p Group=jabuka ... jabuka-sim with --link /run/jabuka-demo/fastnet-pty --gpsd-port 2948 --follow http://127.0.0.1:80 --follow-route --follow-nowait, then systemctl restart jabuka-ingest-fastnet.service jabuka-core.service, then systemctl show -p MainPID --value for both units (fake /proc/<pid>/cmdline under a tmp proc root carrying the demo argv); both zz-jabuka-touch-demo.conf files exist under the tmp dropin root; it is refused when the demo drop-in already exists, when a 50-jabuka-soak.conf exists, when prerace is running or when the race pack is missing; a failing step triggers stop_demo (rollback) and reports « ÉCHEC démo : <étape> »
    - drop-in ordering (the `systemctl cat` fake is a test helper that concatenates the tmp unit file and every *.conf of the tmp /etc and /run <unit>.d dirs sorted by FILENAME, as systemd applies them): (a) an operator /etc/.../jabuka-ingest-fastnet.service.d/override.conf resetting ExecStart with --awa-sign -1 sorts BEFORE zz-jabuka-touch-demo.conf: the demo argv wins, keeps --awa-sign -1, verification passes; (b) an operator drop-in sorting AFTER ours (e.g. zzz-local.conf resetting ExecStart) leaves the race argv effective: verification fails BEFORE any restart, start_demo rolls back (stop_demo calls, our drop-ins gone, operator drop-in untouched) and reports « ÉCHEC démo : ExecStart effectif de jabuka-ingest-fastnet.service différent de la démo (drop-in appliqué après zz-jabuka-touch-demo.conf) »; (c) the main process cmdline of a unit lacking a demo argument after the restart (stale process) also rolls back with « ÉCHEC démo »
    - stop_demo removes only zz-jabuka-touch-demo.conf (a 50-jabuka-soak.conf, an override.conf and a zzz-local.conf in the same .d dirs survive), stops the sim, daemon-reload, restarts both units, polls `systemctl is-active` until both are active, checks `systemctl cat jabuka-core.service` no longer mentions zz-jabuka-touch-demo, and wipes /var/lib/jabuka-demo and /run/jabuka-demo only when the marker .jabuka-touch-demo is present; it refuses to wipe a path equal to or inside /var/lib/jabuka; when the drop-ins are already removed but a unit is still not active after 30 s, the result is a failure whose lines include « Drop-ins démo retirés, mais <unit> pas actif : redémarrer le Pi rétablit le mode course » and the DÉMO screen shows that line (and a REDÉMARRER LE PI shortcut through the normal confirmed reboot action)
    - packaging: the unit, wrapper, example config, install.sh and uninstall.sh checks listed in the action
    - parity (dev venv imports jabuka): demo start point == jabuka.nav.geo.offset(PLIC, radians(341), 2.0) within 1e-9; DEMO_VARIATION == Settings().variation_deg; running demo_wind.py with sys.executable into a tmp root writes wind.npz + wind.json whose t covers start - 2 h .. start + 4 days
    - ui: DÉMO screen shows the mode (« COURSE : capteurs réels » / « DÉMO : bateau simulé »), progress lines and one action button (LANCER LA DÉMO or MODE COURSE) + RETOUR; both are confirmed actions
  </behavior>
  <action>
demo.py: Paths for the demo (race data /var/lib/jabuka, race pack /var/lib/jabuka/racepack, demo root /var/lib/jabuka-demo with data/ and racepack/, run dir /run/jabuka-demo with the pty link fastnet-pty, dropin root /run/systemd/system (and /etc/systemd/system, only read, for tests of the ordering), drop-in name zz-jabuka-touch-demo.conf (the zz- prefix makes it sort after the operator's override.conf and the soak's 50- files: systemd applies the drop-ins of /etc and /run together in filename order), proc root /proc, venv /opt/jabuka/venv, touch root /opt/jabuka-touch, marker .jabuka-touch-demo, sim unit jabuka-demo-sim.service, fake gpsd port 2948), all overridable by tests. Port the soak helpers (service items, effective ExecStart with reset semantics, set_flag, quote with the same safe-character rule, drop-in text) into this module: the touch package never imports jabuka, so copy the logic, cite the source in a comment, and test it against the repo's real unit files. Demo constants: PLIC 43.684627, 15.811626, bearing 341, 2.0 nm (offset computed with the geo.offset formula), TWD 161, TWS 12, TWA 45, DEMO_VARIATION 4.7, start/speed/shift from cfg.demo, duration 4 days.

start_demo(runner, paths, cfg, fetch, progress, sleep, owner) runs, each step announced in French through progress (shown on the DÉMO screen): refuse (demo drop-in present, any 50-jabuka-soak.conf present, jabuka-prerace active, race pack missing); stop + reset-failed the sim unit (rc ignored); wipe and recreate the demo root (marker first) and the run dir, owned by jabuka:jabuka through `owner` (pwd lookup on the Pi, None in tests); copy race.pmtiles, coastline.geojson, seamarks.geojson, racepack.json, polar.json, landmask.npz, landmask.json when present (read-only on the race side, shutil.copyfile) and never the weather files; write the demo wind by running `runuser -u jabuka -- /opt/jabuka/venv/bin/python -I /opt/jabuka-touch/jabuka_touch/demo_wind.py <demo racepack> <demo root> <start epoch> <end epoch> <twd> <tws> <shift>` (timeout 120 s; numbers formatted from validated floats); read `systemctl cat` of both units (timeout 10 s), build the demo argv, write both drop-ins atomically (tmp + os.replace, 0644, creating the .d dirs); daemon-reload; VERIFY BEFORE RESTARTING: read `systemctl cat` of both units again and require that the re-parsed effective ExecStart equals the demo argv token for token (an operator drop-in that sorts after ours, or any other later ExecStart reset, makes it differ: then roll back and report « ÉCHEC démo : ExecStart effectif de <unit> différent de la démo (drop-in appliqué après zz-jabuka-touch-demo.conf) », the half-applied demo must never be restarted); start the sim with `systemd-run --unit=jabuka-demo-sim --collect -p User=jabuka -p Group=jabuka -p Nice=5 -p MemoryMax=200M -p Restart=on-failure /opt/jabuka/venv/bin/jabuka-sim ...` (the sim runs as jabuka so the pty slave belongs to jabuka and the ingest, also jabuka, can open it without the soak's chown thread; its follow URL uses the core's --http-port from the parsed ExecStart); wait up to 20 s for the pty link; `systemctl restart jabuka-ingest-fastnet.service jabuka-core.service` (timeout 90 s); then VERIFY THE RUNNING PROCESSES: for each unit `systemctl show -p MainPID --value`, read <proc root>/<pid>/cmdline (NUL-separated) and require every demo argument argv[1:] to be present, like the soak's runs_soak_argv (an is-active check or LIVE wind alone proves nothing: the real bus also gives LIVE wind), retrying for up to 20 s while the PID is 0 or the process is starting, else roll back with « ÉCHEC démo »; then wait up to 120 s for GET /api/nav wind.source == LIVE (a timeout here only warns « démo lancée, vent LIVE pas encore là »). Any failure before that point calls stop_demo and reports « ÉCHEC démo : <étape> ; retour en mode course : OK | ÉCHEC ». Pitfalls to respect: the units have ProtectSystem=strict, so the core and ingest can only write under ReadWritePaths (hence the extra ReadWritePaths=-/var/lib/jabuka-demo line; /run stays read-only for them and the ingest only follows the link); never stop gpsd (it keeps feeding chrony; the demo core reads the fake gpsd on 2948 with --clock sim).

stop_demo(runner, paths, progress, sleep) is the « Mode course » action and the rollback: stop + reset-failed the sim unit, remove only our two drop-in files (rmdir a .d dir only when it became empty), daemon-reload, restart both units, verify both active (poll 30 s) and that `systemctl cat jabuka-core.service` no longer contains our drop-in name, then wipe the demo root and run dir only when the marker is there and the path is not the race data dir nor inside it. It is idempotent (works with nothing to clean) and reports a clear French result. When the drop-ins are gone but a unit is still not active after the 30 s poll, the result is a failure whose lines say « Drop-ins démo retirés, mais <unit> pas actif : redémarrer le Pi rétablit le mode course » (true because the drop-ins live in /run); the DÉMO screen shows these lines in its result band (the start-rollback failure path shows the same hint), so the crew knows the safe next step is REDÉMARRER LE PI (the existing confirmed reboot action, also reachable from the DÉMO screen as a button when this failure is displayed). demo_active(paths) = our core drop-in file exists (used by the Collector's demo flag, the banner and the prerace refusal).

demo_wind.py: standalone script for the venv python only (header comment says so): argv DEST ROOT START END TWD TWS SHIFT, calls jabuka.soak.pack.write_wind(dest, root, start, end, twd=..., tws_kn=..., shift_deg_h=...), prints the written path, exits 1 with the message on any error. It is the only file of the package allowed to import jabuka (test_isolation already excludes it).

__main__ gains `race-mode` (runs stop_demo with the real runner and prints progress; exit 0 on success, 1 otherwise, printing the reboot hint on the not-active failure).

ui.py/render.py/actions.py/app.py: the DÉMO screen per the behavior block; demo_start and race_mode registered in the worker with the progress callback feeding the screen's lines; confirmation texts « Lancer la DÉMO ? » / « Bateau simulé à la place des instruments. Données de course intactes. Redémarrage = mode course. » and « Revenir en MODE COURSE ? » / « Capteurs réels et données de course. »; the header banner follows the snapshot demo flag; selftest adds the demo screen in both modes and both confirmations.

Packaging (moved here from task 1 so each executor context stays bounded):

touch/jabuka-touch.service: Description in French; [Unit] Conflicts=getty@tty1.service, After=systemd-user-sessions.service, StartLimitIntervalSec=120, StartLimitBurst=5, OnFailure=getty@tty1.service (console comes back only once restarts are exhausted); no Requires/BindsTo/PartOf/Requisite/After on jabuka-core or the ingest. [Service] Type=simple, WorkingDirectory=/opt/jabuka-touch, ExecStart=/usr/bin/python3 -s -m jabuka_touch run, ExecStopPost=/usr/bin/python3 -s -m jabuka_touch restore-console, Restart=on-failure, RestartSec=3, RestartMode=direct (systemd >= 254 on Trixie: auto-restarts skip the failed state so OnFailure only fires at the start limit), Nice=10, MemoryMax=150M, OOMScoreAdjust=500, StandardInput=null, StandardOutput=journal, StandardError=journal, Environment=PYTHONUNBUFFERED=1. Runs as root (fb, input, KDSETMODE, systemctl): comment why. [Install] WantedBy=multi-user.target. Header comment: a menu crash never affects navigation; reboot always comes back on the menu in race mode.

touch/jabuka-touch.example.json: exactly config.defaults_dict() (test asserts equality).

touch/jabuka-touch (bash wrapper installed as /usr/local/sbin/jabuka-touch, root required): no argument or `menu` -> `systemctl start jabuka-touch.service` after printing that the tty1 session will close; `status` -> python3 -s -m jabuka_touch status from /opt/jabuka-touch; `course` -> python3 -s -m jabuka_touch race-mode from /opt/jabuka-touch; `calibrate` -> stop jabuka-touch.service, run the calibrate subcommand, start the service again (warning first that a tty1 session will close); usage line otherwise.

touch/install.sh (bash, set -euo pipefail, idempotent): root required unless DESTDIR is set; overrides DESTDIR (prefix for every destination), SYSTEMCTL (default systemctl) and TOUCH_PYTHON (default /usr/bin/python3) for tests; checks `$TOUCH_PYTHON -c 'import PIL, numpy'` and dies with the apt hint (python3-pil python3-numpy fonts-dejavu-core) when missing; copies touch/jabuka_touch to a .new dir under /opt/jabuka-touch, drops __pycache__, swaps it in, root:root 0755/0644 (chown skipped under DESTDIR); installs the unit 0644 to /etc/systemd/system/, the wrapper 0755 to /usr/local/sbin/jabuka-touch, the example config to /etc/jabuka-touch.json only when absent; then daemon-reload, enable jabuka-touch.service, restart jabuka-touch.service; prints a short French summary (menu on the screen; back to the menu: sudo jabuka-touch). It never edits the boot partition (firmware config / kernel command line are already done by the orchestrator), /opt/jabuka, deploy units or jabuka-core/ingest.

touch/uninstall.sh: same overrides; first, when a zz-jabuka-touch-demo.conf drop-in exists, run the race-mode subcommand and stop on failure with the manual hint (reboot); then `disable --now jabuka-touch.service` (ExecStopPost restores the text console), removes unit, wrapper and /opt/jabuka-touch, daemon-reload, `systemctl start getty@tty1.service`; keeps /etc/jabuka-touch.json and says so.

touch/README.md (French, short): what the menu shows and does; installation (`sudo bash touch/install.sh` from the repo copy on the Pi, needs python3-pil python3-numpy fonts-dejavu-core); back to the menu from the Terminal (`sudo jabuka-touch`, or reboot); race mode from a shell (`sudo jabuka-touch course`); calibration (`sudo jabuka-touch calibrate`, values in /etc/jabuka-touch.json, defaults 3936 227 268 3880 + swap); what the demo changes (volatile drop-ins zz-jabuka-touch-demo.conf in /run, data in /var/lib/jabuka-demo, race data untouched, a reboot always comes back in race mode; the demo refuses to start, with « ÉCHEC démo », if a local drop-in would override it); never start a soak (scripts/soak.sh --systemd system) while a demo runs, since our zz- drop-in would override the soak's 50- drop-in: go back to race mode first; if MODE COURSE says a unit is not active, reboot the Pi; uninstall (`sudo bash touch/uninstall.sh`); tests (`.venv313/bin/python -m pytest tests/touch`, part of scripts/check.sh; `cd touch && python3 -m jabuka_touch selftest --out DIR` renders every screen to PNG, also on the Pi before installing).

Tests: test_demo.py per the behavior block (a fake `systemctl cat` that reads the tmp unit file built from the repo unit files plus every *.conf of the tmp /etc and /run .d dirs sorted by filename; tmp proc root with fake cmdline files; tmp race pack hashed before/after; fake fetch returning LIVE; the three ordering cases (operator override.conf before ours, operator zzz-local.conf after ours -> rollback, stale main process -> rollback); failure injection for rollback; the 30 s not-active case of stop_demo with its reboot line; wipe guards); test_ui.py demo screen (result band shows the reboot hint and the reboot shortcut button after that failure); test_install_files.py checks, on non-comment lines only: the unit has Conflicts=getty@tty1.service, Nice=10, MemoryMax=, Restart=on-failure, ExecStopPost restore-console, WorkingDirectory=/opt/jabuka-touch, and no Requires/BindsTo/PartOf/Requisite naming jabuka-core or jabuka-ingest-fastnet; the example config equals config.defaults_dict(); `bash -n` passes for install.sh, uninstall.sh and the wrapper; install.sh and uninstall.sh never reference the boot partition; a DESTDIR dry run (fake systemctl script logging its argv, TOUCH_PYTHON = a stub that exits 0) installs the expected files, a second run is idempotent and keeps an edited /etc/jabuka-touch.json, uninstall removes all but the config and calls race-mode first when a zz-jabuka-touch-demo.conf exists under DESTDIR; the wrapper usage covers menu, status, course and calibrate.

Finally run the full gate and the freeze guard, then commit by explicit paths: `feat(touch): démo et mode course par drop-ins volatils vérifiés, paquet d'installation, README` with the Co-Authored-By line. Never stage cad/, stl/, hardware/, docs/SOAK.md, docs/I18N-SL-REVIEW.md.bak, deploy/secrets.env, uv.lock, orc/ or .planning/STATE.md.
  </action>
  <verify>
    <automated>cd /home/drico/git/jabuka && bash scripts/check.sh && D=$(mktemp -d) && (cd touch && /usr/bin/python3 -m jabuka_touch selftest --out "$D") && test -z "$(git diff --name-only 7c61a53 -- src deploy pyproject.toml)" && test -z "$(git status --porcelain -- src deploy pyproject.toml)"</automated>
  </verify>
  <done>Demo start/stop sequences proven with fakes (only volatile zz- drop-ins, effective ExecStart and main-process argv verified with rollback on mismatch for both drop-in orderings, race pack untouched, wipe guards, idempotent stop, reboot hint when a unit stays inactive); parity tests against jabuka pass in the dev venv; unit/wrapper/install/uninstall present and dry-run tested; README present (including the no-soak-during-demo note); `bash scripts/check.sh` green on both venvs (the known flaky UI i18n test may be re-run alone); no change under src/, deploy/, pyproject.toml; committed by explicit paths; nothing deployed to the Pi.</done>
</task>

</tasks>

<threat_model>
## Trust Boundaries

| Boundary | Description |
|----------|-------------|
| touch panel -> root menu process | anyone on deck (or spray) can tap; taps reach root-level actions |
| menu -> subprocesses as root | systemctl, systemd-run, prerace, jabuka-wifi, runuser run with root rights |
| core HTTP API -> menu | local JSON parsed by a root process |
| menu -> production units | demo drop-ins change what jabuka-core and the ingest run |
| /etc/jabuka-touch.json -> menu | config values flow into argv (demo numbers) and the touch mapping |

## STRIDE Threat Register

| Threat ID | Category | Component | Severity | Disposition | Mitigation Plan |
|-----------|----------|-----------|----------|-------------|-----------------|
| T-flb-01 | Elevation of privilege | actions.Runner | high | mitigate | fixed ALLOWED set of executables, argv lists only, no shell (AST test), no user-entered strings; only constants and validated floats/ints formatted into argv |
| T-flb-02 | Tampering | demo vs race state | high | mitigate | drop-ins only under /run/systemd/system (volatile, gone at reboot), named zz-jabuka-touch-demo.conf to sort after operator/soak drop-ins, soak/operator drop-ins never removed; effective ExecStart re-parsed after daemon-reload and main-process cmdline checked after restart, rollback on any mismatch (no half-applied demo); demo data in /var/lib/jabuka-demo with marker; race pack only read; test hashes the race pack before/after; wipe refuses the race data dir |
| T-flb-03 | Denial of service | navigation availability | high | mitigate | separate unit without Requires/BindsTo/PartOf on the core, Nice=10, MemoryMax=150M, OOMScoreAdjust=500, every command with a timeout on worker/collector threads, display loop never blocks |
| T-flb-04 | Tampering | API JSON parsing | low | mitigate | defensive .get/type checks, any failure -> unknown/red tile, never an exception into the loop |
| T-flb-05 | Tampering | config file | low | mitigate | root-owned 0644, typed and range-checked load with defaults, atomic save |
| T-flb-06 | Elevation of privilege | accidental taps (spray, wet fingers) on power-off/demo/Wi-Fi | medium | mitigate | confirmation OUI/NON with 8 s auto-cancel, 0.6 s tap guard after screen changes, OUI never under a triggering button (test), median tap + debounce |
| T-flb-07 | Denial of service | text console lost (KD_GRAPHICS left) | medium | mitigate | finally + signal handler + ExecStopPost restore-console + OnFailure getty after the restart limit + uninstall restores getty |
| T-flb-08 | Elevation of privilege | demo wind helper importing venv code | medium | mitigate | run with runuser -u jabuka and python -I, never as root; package installed root:root under /opt/jabuka-touch |
| T-flb-09 | Information disclosure | Terminal button | low | accept | getty requires the normal login password; same exposure as plugging a keyboard today |
</threat_model>

<verification>
- `bash scripts/check.sh` green on .venv and .venv313, tests/touch collected, ruff covering touch (re-run the known flaky test_switch_to_slovenian_then_english_persists_and_fits alone if it fails).
- `cd touch && /usr/bin/python3 -m jabuka_touch selftest --out DIR` exits 0 and the PNGs show every screen (orchestrator can eyeball them before the Pi trial).
- Freeze guard: `git diff --name-only 7c61a53 -- src deploy pyproject.toml` and `git status --porcelain -- src deploy pyproject.toml` are empty.
- No write to the Pi; no package installed anywhere.
</verification>

<success_criteria>
- The crew can, by finger only: read ten health lights, open details, launch prerace and follow it, switch Wi-Fi, start and stop a demo that the tablet sees, restart services, open a terminal, reboot and power off; every risky action is confirmed and auto-cancels.
- A demo never writes to /var/lib/jabuka and a reboot always comes back in race mode.
- The menu can crash or be removed without any effect on jabuka-core or the ingest.
- Gate green, freeze untouched, three atomic commits staged by explicit paths.
</success_criteria>

<output>
Create `.planning/quick/261111-flb-menu-tactile-jabuka-touch-pour-l-ecran-m/261111-flb-SUMMARY.md` when done (do not edit the quick-tasks table of .planning/STATE.md: the orchestrator owns it).
</output>

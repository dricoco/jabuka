---
phase: quick-261111-vew
plan: 01
type: execute
wave: 1
depends_on: []
files_modified:
  - touch/jabuka-current
  - touch/copernicusmarine-constraints.txt
  - touch/install.sh
  - touch/uninstall.sh
  - touch/README.md
  - touch/jabuka_touch/actions.py
  - touch/jabuka_touch/ui.py
  - touch/jabuka_touch/status.py
  - touch/jabuka_touch/config.py
  - tests/touch/test_current_script.py
  - tests/touch/test_current_menu.py
  - tests/touch/test_actions.py
  - tests/touch/test_status.py
  - tests/touch/test_install_files.py
  - docs/WEATHER-PACK.md
autonomous: true
requirements: [GRIB-03, ROUT-04]

estimate:
  tokens: 120000
  raw_tokens: 120000
  tasks: 3
  confidence: low

must_haves:
  truths:
    - "`sudo jabuka-current` launches a detached transient unit jabuka-current (systemd-run --unit=jabuka-current --collect, RuntimeMaxSec=5400), exactly like prerace, and refuses cleanly (exit 1, French message, nothing launched) when jabuka-current or jabuka-prerace is already active, when a jabuka-touch demo drop-in (zz-jabuka-touch-demo.conf) exists, when copernicusmarine or jabuka-prep is missing, or when the Copernicus credentials file is absent; `sudo jabuka-current status` prints the last result (and says when a run is in progress or waiting for prerace)"
    - "The run downloads uo/vo of cmems_mod_med_phy-cur_anfc_4.2km-2D_PT1H-m over lon 14.75..16.55 / lat 42.55..44.25 for the race window read from the installed jabuka-prep (jabuka.route.racepack DEFAULT_WINDOW_LOCAL through window_from_local, the same window `jabuka-prep check` judges) minus 6 h / plus 2 h, i.e. 2026-11-13T11:00:00 -> 2026-11-15T11:00:00 UTC, with copernicusmarine run as root and --credentials-file /root/.copernicusmarine/.copernicusmarine-credentials; the content of that file is never read, printed or copied"
    - "Without internet the run switches to the phone hotspot (only when the jabuka-phone profile exists) and ALWAYS switches back with `jabuka-wifi _switch ap` from the EXIT/TERM trap, exactly as deploy/prerace does"
    - "The NetCDF is imported as user jabuka into a staging copy of /var/lib/jabuka/racepack (`jabuka-prep current FILE --out STAGE` then `jabuka-prep check --out STAGE`); the pack is swapped in (one racepack.prev kept) and jabuka-core restarted ONLY when both return 0 or 3, current.npz exists, coverage.txt has no current problem line, prerace/demo are not active and the live pack's identity recorded at staging time (directory inode, sha256 of its *.json sidecars, prerace-last.txt mtime) is unchanged; any failure (network, credentials, server, import, coverage, prerace or demo started meanwhile, pack modified meanwhile e.g. by an SSH `sudo prerace` that ran and finished during the current run) leaves the live pack byte-identical, exits 2 and writes a French explanation to /var/lib/jabuka/current-last.txt (date, résultat, code, fenêtre, fichier, Wi-Fi, journal tail on failure); if `mv STAGE PACK` fails after `mv PACK PREV`, the old pack is moved back"
    - "jabuka-current refuses to start, and refuses the phone Wi-Fi switch, whenever jabuka-prerace is active at any of its check points (start of the body, before the internet probe / Wi-Fi switch, after the download, after staging, before the swap)"
    - "Touch menu, MÉTÉO / WI-FI screen: LANCER PRERACE (confirmed) launches prerace and then `jabuka-current --after-prerace <epoch>`, whose detached run waits for jabuka-prerace to finish and continues only if that prerace wrote a fresh result with code 0 or 3; a new COURANT button (confirmed, >= 80 px tall, centre outside OUI) runs the current step alone; both are refused during a demo and LANCER PRERACE is refused while a current run is active; the info lines show the last current result (or waiting / running), the MÉTÉO tile details say whether current.npz is present and when it was downloaded, and JOURNAL follows both units"
    - "`sudo bash touch/install.sh` installs /usr/local/sbin/jabuka-current (0755) and copernicusmarine 2.5.1 in its own venv /opt/copernicusmarine/venv (pinned constraints, binary wheels only), skips the venv when 2.5.1 is already there, and without internet or on a pip failure prints a clear French message and completes the rest of the install; it never touches /opt/jabuka/venv nor /opt/jabuka-prep/venv"
    - "`bash scripts/check.sh` is green and nothing changed under src/, deploy/ or pyproject.toml since 7c61a53"
  artifacts:
    - path: "touch/jabuka-current"
      provides: "detached Copernicus current step: launch, status, _run body (Wi-Fi like prerace, download, staging import, atomic swap, result file)"
      contains: "cmems_mod_med_phy-cur_anfc_4.2km-2D_PT1H-m"
    - path: "touch/copernicusmarine-constraints.txt"
      provides: "exact dependency pins of the laptop-validated copernicusmarine 2.5.1 environment"
      contains: "copernicusmarine==2.5.1"
    - path: "touch/install.sh"
      provides: "installs jabuka-current and the separate copernicusmarine venv (non-fatal step)"
      contains: "/opt/copernicusmarine/venv"
    - path: "touch/jabuka_touch/actions.py"
      provides: "whitelisted jabuka-current, `current` action, prerace -> current chaining"
      contains: "--after-prerace"
    - path: "touch/jabuka_touch/ui.py"
      provides: "COURANT button, confirmation text, current info line"
      contains: "COURANT"
    - path: "touch/jabuka_touch/status.py"
      provides: "current-last.txt parsing, current presence in the MÉTÉO details, journal of both units"
      contains: "jabuka-current.service"
    - path: "tests/touch/test_current_script.py"
      provides: "stubbed-PATH tests of touch/jabuka-current"
    - path: "tests/touch/test_current_menu.py"
      provides: "menu tests: COURANT button, chaining, info lines, details"
    - path: "docs/WEATHER-PACK.md"
      provides: "note: current on the Pi with sudo jabuka-current / the menu"
      contains: "jabuka-current"
  key_links:
    - from: "touch/jabuka_touch/ui.py COURANT button"
      to: "touch/jabuka_touch/actions.py current action -> /usr/local/sbin/jabuka-current"
      via: "confirm -> Worker.submit('current') -> Runner.run([CURRENT])"
      pattern: "jabuka-current"
    - from: "touch/jabuka_touch/actions.py prerace action"
      to: "jabuka-current --after-prerace <since>"
      via: "second whitelisted argv after a successful prerace launch"
      pattern: "--after-prerace"
    - from: "touch/jabuka-current _run"
      to: "/opt/jabuka-prep/venv/bin/jabuka-prep current|check"
      via: "runuser -u jabuka (never root: the NetCDF is untrusted input)"
      pattern: "runuser -u jabuka"
    - from: "touch/jabuka-current cleanup trap"
      to: "/usr/local/sbin/jabuka-wifi _switch ap"
      via: "trap cleanup EXIT + trap 'exit 143' TERM INT HUP"
      pattern: "_switch ap"
    - from: "touch/jabuka_touch/status.py Collector"
      to: "/var/lib/jabuka/current-last.txt and /var/lib/jabuka/racepack/current.npz"
      via: "config.Paths.current_last / current_npz, read every system step"
      pattern: "current_last"
    - from: "touch/install.sh"
      to: "/opt/copernicusmarine/venv/bin/pip install -c copernicusmarine-constraints.txt"
      via: "non-fatal install_copernicusmarine step before daemon-reload"
      pattern: "copernicusmarine-constraints.txt"
---

<objective>
Add a Copernicus "current" step to the Pi's pre-race weather preparation without touching anything
frozen (freeze 2026-11-11: src/, deploy/ except *.md, pyproject.toml; see scripts/freeze-check.sh).

Locked user decisions for this quick task (no CONTEXT.md; cited below as U1..U4 and R):
- U1: a new script `jabuka-current` (bash, set -u, logged) that checks internet like deploy/prerace
  (phone hotspot when needed, ALWAYS back to the AP from a trap, detached systemd-run unit
  jabuka-current), downloads with copernicusmarine as root using /root/.copernicusmarine into a
  cache, imports with `runuser -u jabuka -- /opt/jabuka-prep/venv/bin/jabuka-prep current FILE
  --out STAGING` then `jabuka-prep check` on an rsync staging copy of /var/lib/jabuka/racepack,
  installs only if the import succeeded and the current covers the window, by atomic swap keeping
  racepack.prev, then restarts jabuka-core, writes /var/lib/jabuka/current-last.txt (date, code,
  result, run/window), exits 0 OK / 2 failure (pack unchanged), never runs at the same time as
  prerace nor during a jabuka-touch demo (clean refusal), and explains Copernicus failures clearly
  in French. The window comes from the race window jabuka-prep uses (13/11 18:00 -> 15/11 10:00
  local) with a -6 h / +2 h margin.
- U2: install via touch/install.sh: copernicusmarine in a SEPARATE venv (/opt/copernicusmarine/venv),
  never in /opt/jabuka/venv nor /opt/jabuka-prep/venv; script installed as
  /usr/local/sbin/jabuka-current; idempotent; without internet a clear message and the rest of the
  install continues.
- U3: touch menu, MÉTÉO / WI-FI screen: LANCER PRERACE chains prerace THEN jabuka-current (current
  only if prerace ended with code 0 or 3); a confirmed COURANT button runs it alone; the last current
  result in the info lines; a mention in the MÉTÉO details (current present + run). Existing rules:
  command whitelist, no shell, confirmations, buttons >= 80 px, refused during the demo.
- U4: pytest tests on the laptop (command construction, Wi-Fi/trap with stubbed PATH, refusals,
  pack unchanged on import failure, prerace -> current chaining, new button); touch/README.md
  (French) + a note in docs/WEATHER-PACK.md.
- R (rules): robustness over features, keep it small; never read/print/copy the credentials file;
  the executor never writes to the Pi (install and the real trial are done by the orchestrator);
  stage by explicit path only.

Purpose: the router uses current when current.npz is in the pack (ROUT-04, imported by GRIB-03);
today that needs the laptop. After this task the Pi can fetch it itself, from the menu, with the
same safety net as prerace.
Output: touch/jabuka-current + tests, installer step + constraints, menu wiring + tests, docs.
</objective>

<execution_context>
@/home/drico/.claude/gsd-core/workflows/execute-plan.md
@/home/drico/.claude/gsd-core/templates/summary.md
</execution_context>

<context>
@.planning/STATE.md
@.claude/CLAUDE.md
@deploy/prerace
@tests/deploy/test_prerace.py
@.planning/quick/261111-flb-menu-tactile-jabuka-touch-pour-l-ecran-m/261111-flb-SUMMARY.md

Facts verified while planning (2026-11-11), do not re-derive:
- deploy/prerace is the model for everything shell-side: env overrides for tests only
  (PRERACE_DATA_DIR / PRERACE_PREP / PRERACE_WIFI), `launch` re-runs "$SELF" _run via
  `systemd-run --quiet --unit=... --collect --property=RuntimeMaxSec=...`, `have_internet` (curl -sfI
  --max-time 10, python urllib fallback), `have_phone_profile` (nmcli -g NAME connection show | grep
  -x jabuka-phone), SWITCHED=1 set BEFORE `"$WIFI" _switch phone || true`, 12 tries x sleep 5,
  `cleanup` on EXIT (switch back with `"$WIFI" _switch ap`, write_result, remove staging when not
  installed, cat result, exit rc), `trap 'exit 143' TERM INT HUP`, `prep()` = `runuser -u jabuka --
  nice -n 10 "$PREP" ... 2>&1 | tee -a "$LOG"`, swap = rm -rf PREV; mv PACK PREV; mv STAGE PACK;
  chown -R jabuka:jabuka PACK; systemctl restart jabuka-core.service. tests/deploy/test_prerace.py
  is the model for the stubbed-PATH harness (RECORD stubs appending "<name> <args>" to $FAKE_CALLS).
- `jabuka-prep current FILE --out DIR` and `jabuka-prep check --out DIR` (src/jabuka/prep/cli.py):
  exit 0 ok, 3 coverage incomplete (files written), 2 input error. `current` prints
  "Courant : N échéances <t0> -> <t1>, grille AxB -> <path>" and also runs the check. Both use the
  default window jabuka.route.racepack.DEFAULT_WINDOW_LOCAL = ("2026-11-13T18:00",
  "2026-11-15T10:00") Europe/Zagreb via window_from_local(start, end) -> RaceWindow(start_utc,
  end_utc) (ints, UTC epoch) = 2026-11-13T17:00Z .. 2026-11-15T09:00Z.
- coverage.txt current lines (src/jabuka/route/racepack.py coverage/format_report): every current
  problem ends in "courant désactivé" (window not covered, mark/leg outside the grid, NaN),
  "Courant invalides (...) : courant désactivé" for a rejected file, "Info : Courant absent :
  routage sans courant" when no file. A step warning "courant : pas de temps de ..." is harmless.
  Wind problems make check return 3 but are not the current step's concern.
- The current.json sidecar has model MEDSEA, run "" (Copernicus has no run time): the
  "run" shown to the user is the download date of the last successful jabuka-current.
- copernicusmarine 2.5.1 (`~/.local/bin/copernicusmarine subset --help` on the laptop): flags
  --dataset-id, --variable (repeatable), --minimum/maximum-longitude/latitude, --start-datetime,
  --end-datetime (naive ISO is UTC, as in the validated docs command), --output-directory,
  --output-filename, --overwrite (replaces an existing file; default would create file_(1).nc),
  --credentials-file PATH, --disable-progress-bar, --log-level. v2 has no confirmation prompt.
  `copernicusmarine --version` prints "copernicusmarine, version 2.5.1".
- Internet probe for the script: https://stac.marine.copernicus.eu/metadata/catalog.stac.json
  answers HEAD 200 (the toolbox's own catalogue). For the installer: https://pypi.org/simple/copernicusmarine/
  answers HEAD 200.
- The 64 packages of the laptop's copernicusmarine 2.5.1 tool env
  (`uv pip freeze --python ~/.local/share/uv/tools/copernicusmarine/bin/python`) all have a py3-any
  or a cp313/abi3 manylinux aarch64 wheel on PyPI at those exact versions (pyarrow, pandas, h5py,
  numpy, numcodecs, msgspec, google-crc32c, pydantic-core, pyyaml are the binary ones), so
  `--only-binary=:all:` with those pins installs on the Pi (Trixie, Python 3.13) without compiling.
- deploy/provision.sh installs python3-venv on the Pi; /opt/jabuka-prep/venv is a regular venv, so
  /opt/jabuka-prep/venv/bin/python exists next to bin/jabuka-prep.
- Touch package (quick 261111-flb): actions.py (ALLOWED executables + ALLOWED_DIRS, Runner /
  FakeRunner, Action / Outcome, cmd_outcome, build_registry with prerace(runner, demo_active)),
  ui.py (RISKY, CONFIRM_TEXTS, Layout, prep screen info band y 36-152 drawn with wrapped 14 px text
  by render.py, buttons rows 152-236 and 236-320, OUI rect x 240-480 / y 150-240, tick() opens
  the journal after a successful prerace), status.py (EXTRA_QUERIES journal_prerace /
  prerace_status / wifi_status, parse_prerace_last, Collector._prerace_step reads
  paths.prerace_last and `systemctl is-active jabuka-prerace.service`, pack_item from the core API),
  config.py (frozen dataclass Paths with defaults under /var/lib/jabuka and demo_flag
  /run/systemd/system/jabuka-core.service.d/zz-jabuka-touch-demo.conf). The menu runs as root
  (no User= in jabuka-touch.service) and calls scripts without sudo with a fixed ENV dict.
- Existing tests that the changes touch: tests/touch/test_actions.py::test_prerace_and_wifi_argv
  (exact runner.calls list), tests/touch/test_status.py (journalctl argv list, Paths built with tmp
  paths), tests/touch/test_install_files.py (fixture `env`: DESTDIR, SYSTEMCTL, TOUCH_PYTHON, LOG;
  asserts the last three log lines are daemon-reload / enable / restart and the uninstall log is
  exactly three systemctl lines; parametrized syntax test forbids "/opt/jabuka/" and "deploy/" in
  non-comment lines). tests/ui/test_start_ui.py::test_start_zone_and_times_on_the_map and
  test_switch_to_slovenian_then_english_persists_and_fits are known flaky: rerun alone.
- Shell gotcha on this laptop: an RTK hook rewrites bare `git`/`ls` commands and can print
  "(empty)" instead of output; use /usr/bin/git and /bin/ls in verify commands.
</context>

<tasks>

<task type="tracer">
  <name>Task 1 (tracer): COURANT button -> jabuka-current -> download -> staging import -> swap, one happy path end to end</name>
  <files>touch/jabuka-current, tests/touch/test_current_script.py, touch/jabuka_touch/actions.py, touch/jabuka_touch/ui.py, tests/touch/test_current_menu.py</files>
  <read_first>deploy/prerace (whole file: copy its structure, do NOT edit it, deploy/ is frozen), tests/deploy/test_prerace.py (harness), touch/jabuka_touch/actions.py, touch/jabuka_touch/ui.py, tests/touch/test_ui.py lines 100-140 (geometry rules), tests/touch/conftest.py</read_first>
  <behavior>
    - Script launch: `jabuka-current` (root) with nothing active calls systemd-run once with --unit=jabuka-current, --collect, --property=RuntimeMaxSec=5400, the resolved script path and _run, prints how to follow it, and runs no download.
    - Script happy path (`_run`, internet up, old pack present): copernicusmarine is called with subset, --dataset-id cmems_mod_med_phy-cur_anfc_4.2km-2D_PT1H-m, --variable uo, --variable vo, --minimum-longitude 14.75, --maximum-longitude 16.55, --minimum-latitude 42.55, --maximum-latitude 44.25, --start-datetime 2026-11-13T11:00:00, --end-datetime 2026-11-15T11:00:00, --output-directory DATA/cache/current, --output-filename current_med.nc, --overwrite, --credentials-file CREDS; the order is download < `jabuka-prep current` < `jabuka-prep check` < `systemctl restart jabuka-core`; both prep calls carry --out DATA/racepack.current-new; the live pack ends with current.npz, racepack.prev holds the old pack, no staging dir is left; current-last.txt has "code : 0", a "résultat : OK" line, the window and the "Courant : ..." import line; exit 0.
    - A SECRET token written in the fake credentials file never appears in stdout, stderr, current-last.txt or current-last.log.
    - Menu: on the prep screen a COURANT action button exists, is risky (opens the confirmation), its centre is not inside OUI, it is >= 80 px tall and >= 100 px wide; tapping COURANT then OUI submits "current"; the `current` action runs exactly [/usr/local/sbin/jabuka-current] with a 30 s timeout; during a demo it returns a refusal line and runs nothing.
  </behavior>
  <action>
Implements U1 (core path) and U3 (COURANT button) as the thinnest end-to-end slice; Task 2 hardens
the script, Task 3 adds chaining and display.

A. Create touch/jabuka-current (new file, executable 0755, `#!/usr/bin/env bash`, `set -euo pipefail`),
structured exactly like deploy/prerace (read it first and reuse its function names and order:
die, unit_active, launch, status, have_internet, have_phone_profile, note, write_result, cleanup,
prep, run_body, final case on "$1"). Header comment lines 2..~16 are the French-and-English usage
printed by -h/--help (same `sed -n` trick), listing: `sudo jabuka-current` (background:
phone hotspot only without internet, Copernicus current into a staging copy, swap, restart
jabuka-core, back to the AP), `sudo jabuka-current --after-prerace EPOCH` (wait for prerace, used
by the touch menu), `sudo jabuka-current status`, follow with journalctl -fu jabuka-current, exit
0 OK / 2 failure with the old pack untouched. Comments must say the credentials file is only
tested for existence and passed by path, never read.
Variables: test-harness overrides only, with the same comment as prerace (sudo env_reset and
systemd-run drop them; the menu calls the script with a fixed env): DATA from CURRENT_DATA_DIR
(default /var/lib/jabuka), PREP from CURRENT_PREP (default /opt/jabuka-prep/venv/bin/jabuka-prep),
PREP_PY = the `python` next to PREP (dirname of PREP), WIFI from CURRENT_WIFI (default
/usr/local/sbin/jabuka-wifi), CM from CURRENT_CM (default
/opt/copernicusmarine/venv/bin/copernicusmarine), CREDS from CURRENT_CREDS (default
/root/.copernicusmarine/.copernicusmarine-credentials), RUN_UNITS from CURRENT_RUN_UNITS (default
/run/systemd/system), POLL_S from CURRENT_POLL_S (default 15), WAIT_MAX_S from CURRENT_WAIT_MAX_S
(default 3900). Constants: UNIT=jabuka-current, PRERACE_UNIT=jabuka-prerace,
URL=https://stac.marine.copernicus.eu/metadata/catalog.stac.json, PHONE=jabuka-phone,
DATASET=cmems_mod_med_phy-cur_anfc_4.2km-2D_PT1H-m, the bbox 14.75 16.55 42.55 44.25 (same as
docs/WEATHER-PACK.md), MARGIN_BEFORE_S=21600, MARGIN_AFTER_S=7200, PACK=$DATA/racepack,
STAGE=$DATA/racepack.current-new (never prerace's racepack.new), PREV=$DATA/racepack.prev,
CACHE=$DATA/cache/current, NC_NAME=current_med.nc, RESULT=$DATA/current-last.txt,
LOG=$DATA/current-last.log, PRERACE_RESULT=$DATA/prerace-last.txt, SELF via readlink -f.
Root check like prerace (every subcommand needs root, /var/lib/jabuka is 0750).

launch (tracer scope): refuse with exit 1 if the jabuka-current unit is active ("un
téléchargement du courant est déjà en cours : journalctl -fu jabuka-current"); run `preflight`
(a function reused by the body: PREP executable, CM executable, CREDS exists via `[ -f ]` only;
French messages: venv météo du Pi absent / copernicusmarine absent : sudo bash touch/install.sh
avec internet / identifiants Copernicus absents : sudo /opt/copernicusmarine/venv/bin/copernicusmarine
login (une fois)); then `systemd-run --quiet --unit=jabuka-current --collect
--property=RuntimeMaxSec=5400 "$SELF" _run` and print "suivre : journalctl -fu jabuka-current ;
résultat : sudo jabuka-current status". status: same shape as prerace's (en cours line when the
unit is active, then the result file or "aucun téléchargement du courant enregistré").

run_body (tracer scope = internet already up): cd DATA, truncate LOG, init SWITCHED=0 INSTALLED=0
OUTCOME="ÉCHEC : interrompu" NOTES="" WIFI_NOTE="non utilisé" WINDOW_NOTE="?" IMPORT_LINE="?",
install both traps exactly like prerace. Steps:
1. preflight; on failure set OUTCOME to the French reason + ", pack inchangé" and exit 2.
2. Window: `runuser -u jabuka -- "$PREP_PY" -I -c` with a one-liner that imports
   DEFAULT_WINDOW_LOCAL and window_from_local from jabuka.route.racepack, builds the window and
   prints start_utc and end_utc (-I so a file planted in the jabuka-writable cwd cannot shadow an
   import). Validate both are integers, subtract MARGIN_BEFORE_S / add MARGIN_AFTER_S, format with
   `date -u -d @N +%Y-%m-%dT%H:%M:%S` into START / END; WINDOW_NOTE = "START -> END UTC (fenêtre
   de course jabuka-prep, marge -6 h / +2 h)". Failure: "ÉCHEC : fenêtre de course illisible (venv
   météo du Pi), pack inchangé", exit 2.
3. Internet: `have_internet` copied from prerace with URL above. In this task, no internet =
   OUTCOME "ÉCHEC : pas d'internet" exit 2 (Task 2 replaces it with the phone hotspot logic).
4. No live pack (`[ -d "$PACK" ]` false): "ÉCHEC : pas de pack de course installé (prerace
   d'abord)", exit 2.
5. Download: mkdir -p CACHE, remove any old CACHE/NC_NAME, then run
   `env HOME=/root timeout --kill-after=30 900 nice -n 10 "$CM" subset` with the exact argument
   list of the behavior block (plus --disable-progress-bar), stdout+stderr through `tee -a "$LOG"`
   (pipefail gives copernicusmarine's code). Non-zero code or an empty/missing file:
   OUTCOME "ÉCHEC : téléchargement Copernicus (code N : réseau, identifiants ou serveur, voir le
   journal ci-dessous), pack inchangé", exit 2. Then chown -R jabuka:jabuka "$CACHE".
6. Staging exactly like prerace step 2 (rm -rf STAGE, rsync -a PACK/ STAGE/ or cp -a fallback,
   chown -R jabuka:jabuka STAGE).
7. `prep current "$CACHE/$NC_NAME"` then `prep check`, where prep() is prerace's helper without
   --cache (neither subcommand uses it): `runuser -u jabuka -- nice -n 10 "$PREP" "$@" --out
   "$STAGE"`, tee to LOG. Accept 0 or 3 for each; anything else: "ÉCHEC : import du courant (code
   N), pack inchangé" / "ÉCHEC : contrôle du pack (code N), pack inchangé", exit 2. Keep the last
   LOG line starting with "Courant : " as IMPORT_LINE.
8. Coverage gate (U1 "covers the window"): STAGE/current.npz must exist and STAGE/coverage.txt must
   have no line matching "courant désactivé", "Courant absent" or "Courant invalides"; otherwise
   "ÉCHEC : le courant ne couvre pas la fenêtre de course (voir coverage), pack inchangé", exit 2.
   If check returned 3 (wind already incomplete), add a note, do not fail.
9. Swap exactly like prerace step 4 (one racepack.prev), INSTALLED=1, chown, restart
   jabuka-core.service (note on failure), remove the downloaded .nc, OUTCOME "OK : courant
   installé, jabuka-core redémarré", exit 0.
write_result (atomic tmp + mv like prerace) writes, in this order: "courant : <UTC now ISO Z>",
"résultat : $OUTCOME", "code : N", "fenêtre : $WINDOW_NOTE", "fichier : $IMPORT_LINE", "Wi-Fi :
$WIFI_NOTE", optional "notes : ...", then "--- coverage.txt (courant) ---" with the coverage.txt
lines mentioning courant (case-insensitive) from PACK when installed else STAGE, and on failure
"--- journal (fin) ---" with the last 15 LOG lines. cleanup = prerace's, except the exit code is
normalised: 0 stays 0, anything else (including 143 after a signal) exits 2, so the run contract
is exactly 0 OK / 2 failure.

B. tests/touch/test_current_script.py: copy the harness of tests/deploy/test_prerace.py (STUBS
dict with RECORD for id, systemctl, systemd-run, nmcli, curl, runuser, chown, sleep; FAKE_ACTIVE
style env switches) adapted to CURRENT_* overrides; a fake jabuka-prep that records "prep <args>",
for `current` writes current.npz + current.json into --out and prints "Courant : 49 échéances
2026-11-13T11:00Z -> 2026-11-15T11:00Z, grille 41x44 -> ..." (rc from FAKE_RC_CURRENT), for
`check` writes coverage.txt from FAKE_COVERAGE (default "COUVERTURE MÉTÉO : OK") with rc
FAKE_RC_CHECK; a `python` wrapper beside the fake jabuka-prep that execs sys.executable (the dev
venv, where jabuka is installed editable) with all its arguments, so the REAL window code runs; a
fake copernicusmarine recording "cm <args>" that writes a non-empty file at
--output-directory/--output-filename unless FAKE_RC_CM is non-zero; a fake credentials file
containing a SECRET token. Tracer tests: bash -n, executable bit, launch detaches (behavior block),
happy path (behavior block: exact cm tokens via a parsed argv, order, pack/prev/staging state,
result lines), secret never leaks.

C. touch/jabuka_touch/actions.py: add "jabuka-current" to ALLOWED, a CURRENT constant
f"{SBIN}/jabuka-current", a CURRENT_DEMO_REFUSAL "Démo en cours : revenir en mode course avant le
courant", and `current(runner, demo_active)` -> Action("current", "Courant", fn) modelled on
prerace(): refusal during a demo (no command run), progress "Lancement du courant Copernicus…",
runner.run([CURRENT], 30.0), cmd_outcome(res, "Courant lancé : suivre le journal"). Register it in
build_registry's fixed tuple with the same demo_active callable as prerace.

D. touch/jabuka_touch/ui.py: add "current" to RISKY; CONFIRM_TEXTS["current"] = ("Télécharger le
courant Copernicus ?", "Partage du téléphone s'il n'y a pas d'internet : Wi-Fi bateau coupé
quelques minutes. Pack inchangé en cas d'échec."); on the prep screen replace the 152-236 row by
three explicit buttons built with Layout.r: LANCER PRERACE x 0-125, COURANT x 125-240 (both
confirmation-opening centres stay left of OUI, which starts at x 240), JOURNAL x 240-480 (nav);
keep the 236-320 row unchanged. In tick(), open the journal after a successful "current" too
(same condition as prerace).

E. tests/touch/test_current_menu.py (new, uses the conftest fixtures and the Harness pattern of
tests/touch/test_ui.py, or a minimal local equivalent): the menu behaviors listed above.
  </action>
  <verify>
    <automated>cd /home/drico/git/jabuka && .venv313/bin/python -m pytest -q tests/touch/test_current_script.py tests/touch/test_current_menu.py tests/touch/test_ui.py tests/touch/test_actions.py && bash -n touch/jabuka-current && test -x touch/jabuka-current</automated>
  </verify>
  <done>The happy path works end to end under stubs (COURANT -> OUI -> [/usr/local/sbin/jabuka-current]; `_run` downloads with the exact Copernicus arguments, imports as jabuka into staging, swaps with one racepack.prev, restarts jabuka-core, writes current-last.txt with code 0); existing touch UI/action tests still pass; committed as `feat(touch): étape courant Copernicus jabuka-current, traceur bouton COURANT` with the Co-Authored-By line.</done>
</task>

<task type="auto" tdd="true">
  <name>Task 2: harden jabuka-current (Wi-Fi like prerace, refusals, --after-prerace wait, failure paths) + installer with its own copernicusmarine venv + WEATHER-PACK note</name>
  <files>touch/jabuka-current, tests/touch/test_current_script.py, touch/install.sh, touch/uninstall.sh, touch/copernicusmarine-constraints.txt, tests/touch/test_install_files.py, docs/WEATHER-PACK.md</files>
  <read_first>touch/jabuka-current (as left by Task 1), deploy/prerace lines 99-223 (Wi-Fi body), touch/install.sh, touch/uninstall.sh, tests/touch/test_install_files.py, docs/WEATHER-PACK.md lines 84-125</read_first>
  <behavior>
    - No internet, phone profile present (curl fails twice then succeeds): `wifi _switch phone` happens before the download, the last wifi call is `wifi _switch ap` and comes after `systemctl restart jabuka-core`, result says "retour au point d'accès", exit 0.
    - No internet and no jabuka-phone profile: exit 2, no wifi call, no download, live pack unchanged, the prerace-style message about `sudo jabuka-wifi phone` is in the output and in current-last.txt.
    - Phone hotspot without internet: switched then back to the AP, no download, pack unchanged, exit 2.
    - copernicusmarine fails (FAKE_RC_CM=1) with the phone hotspot used: exit 2, pack directory listing and file bytes unchanged, no racepack.prev created, no restart, staging removed, Wi-Fi back to the AP, result "ÉCHEC : téléchargement Copernicus" with the journal tail.
    - `jabuka-prep current` fails (rc 2), or `check` fails (rc 2), or coverage.txt contains a "courant ... : courant désactivé" line: exit 2, pack unchanged, no restart.
    - Launch refusals (exit 1, no systemd-run): jabuka-current active; jabuka-prerace active (normal mode); a zz-jabuka-touch-demo.conf drop-in under RUN_UNITS for jabuka-core or jabuka-ingest-fastnet; CM missing; CREDS missing; unknown argument exits 2; `--after-prerace` with a non-numeric value exits 2.
    - `--after-prerace N` launch is NOT refused while prerace is active and passes `_run --after-prerace N` to systemd-run.
    - `_run --after-prerace N`: while `systemctl is-active jabuka-prerace` succeeds it sleeps POLL_S (sleep stub) and polls again; once inactive, with prerace-last.txt mtime >= N and "code : 0" or "code : 3" it proceeds (download happens after the polls); with "code : 2" it exits 2 with "NON LANCÉ : prerace en échec (code 2), pack inchangé" and no wifi/download; with an mtime older than N it exits 2 "NON LANCÉ" and no download; after WAIT_MAX_S of polling it exits 2.
    - Body refusals: demo drop-in present at `_run` time, or prerace active at `_run` time in normal mode: exit 2 before any Wi-Fi switch or download.
    - Prerace or a demo appearing between the check and the swap (the fake `check` creates a flag that makes the systemctl stub report jabuka-prerace active): exit 2, pack unchanged, Wi-Fi back.
    - A prerace that started AND finished during the run (prerace is never seen active): with FAKE_SWAP_DURING_CHECK=1 the fake `check` simulates prerace's swap on DATA (rm -rf racepack.prev, mv racepack racepack.prev, a new racepack with a fresh wind.json, a new prerace-last.txt). Result: exit 2, current-last.txt says « pack modifié pendant le courant : pack inchangé, relancer COURANT », the live racepack is byte-identical to the one the simulated prerace installed (no current.npz, fresh wind.json), racepack.prev is still the simulated prerace's, no `systemctl restart`, staging removed.
    - No internet, phone profile present, but jabuka-prerace active at the internet/Wi-Fi check point (systemctl stub flag): exit 2 with « prerace en cours », NO `wifi _switch phone` call at all, no download, pack unchanged.
    - Swap rollback: with a `mv` stub (first in PATH, real mv otherwise) that fails only when its source is racepack.current-new, the run exits 2, the live racepack is back with its original bytes (moved back from racepack.prev), no `systemctl restart`, staging removed, and current-last.txt says the old pack was put back.
    - Window query failure (python wrapper exits 1): exit 2 before any Wi-Fi or download.
    - `status`: "aucun téléchargement du courant enregistré" without a run; the result file after a run; an "en cours" line when the unit is active, "en attente de la fin de prerace" when both units are active.
    - Every non-comment line of the script that uses the credentials variable is either the existence test or the --credentials-file argument; a copy of prerace's "never handles the phone password" test passes on this script.
    - Installer: first run creates the venv with CM_PYTHON -m venv DESTDIR/opt/copernicusmarine/venv, calls its pip with install, --only-binary=:all:, -c pointing at touch/copernicusmarine-constraints.txt and copernicusmarine==2.5.1, installs DESTDIR/usr/local/sbin/jabuka-current 0755 identical to touch/jabuka-current, and the last three log lines stay daemon-reload / enable / restart; a second run says "déjà installé" and calls pip no more; without internet (curl stub fails) or with a failing pip it exits 0, prints a French message containing "copernicusmarine NON installé" and still installs the menu; uninstall removes usr/local/sbin/jabuka-current and keeps opt/copernicusmarine.
  </behavior>
  <action>
Implements U1 (robustness, refusals, Wi-Fi), U2 (installer) and the docs half of U4. Write the
failing tests for each behavior first in tests/touch/test_current_script.py and
tests/touch/test_install_files.py, then the code.

A. touch/jabuka-current:
- Wi-Fi: replace Task 1's "no internet" failure by prerace's block verbatim in logic (profile
  check with its French "lancer d'abord sudo jabuka-wifi phone une fois pour enregistrer le mot de
  passe" message, SWITCHED=1 before the switch, 12 probes 5 s apart, failure message about the
  phone sharing, WIFI_NOTE values) and keep the switch back in cleanup (U1: always back to the AP
  via the trap). All local checks (preflight, window, demo/prerace refusals, live pack present,
  after-prerace gate) run BEFORE the internet check so a doomed run never drops the boat Wi-Fi.
- Demo detection: a `demo_active` function true when zz-jabuka-touch-demo.conf exists under
  RUN_UNITS/jabuka-core.service.d or RUN_UNITS/jabuka-ingest-fastnet.service.d (same test as
  touch/uninstall.sh). prerace detection: `systemctl is-active --quiet jabuka-prerace.service`.
- launch: parse `--after-prerace N` (N must match ^[0-9]+$, else die 2 with the usage), refuse
  (exit 1, French on stderr) when jabuka-current is active, when prerace is active and no
  --after-prerace was given ("prerace en cours : le courant suivra si lancé depuis le menu, sinon
  attendre la fin (sudo prerace status)"), when a demo runs ("démo en cours : revenir en mode course
  avant le courant (sudo jabuka-touch course)"), or when preflight fails; pass the option through
  as `_run --after-prerace N`.
- run_body: parse the same option. If given: poll every POLL_S while prerace is active, up to
  WAIT_MAX_S ("ÉCHEC : prerace toujours en cours après 65 min, courant non lancé"); then require
  PRERACE_RESULT to exist with `stat -c %Y` >= N ("NON LANCÉ : pas de résultat récent de prerace,
  pack inchangé") and read its first "code : X" line; continue only for 0 or 3, else "NON LANCÉ :
  prerace en échec (code X), pack inchangé" (U3: current only after prerace 0 or 3). Without the
  option: refuse if prerace is active. In both modes refuse if a demo is active. All exit 2.
- Concurrency guard (frozen deploy/prerace does not know about jabuka-current, so an SSH `sudo
  prerace` can start, or even start and finish, during a current run): one `guard STEP` function
  that exits 2 with "ÉCHEC : prerace en cours (STEP), pack inchangé" or "ÉCHEC : démo en cours
  (STEP), pack inchangé" when jabuka-prerace is active or a demo drop-in exists. Call it at the
  start of the body (after the optional wait), immediately before the internet probe (so the phone
  Wi-Fi switch is never attempted while prerace runs), after the download, after staging, and
  immediately before the swap.
- Pack identity: right after the staging copy, record the live pack's identity with a
  `pack_identity` function printing one line: `stat -c %i` of PACK, the sha256 of every PACK/*.json
  sidecar in name order (the sidecars carry the sha256 of their npz, so any weather change shows),
  and the mtime of PRERACE_RESULT (or "none"). Immediately before the swap (after the last guard),
  recompute it; if it differs: OUTCOME "ÉCHEC : pack modifié pendant le courant : pack inchangé,
  relancer COURANT", exit 2 (the staging copy is discarded by cleanup). This catches a prerace
  that ran entirely between two guard points (its swap gives PACK a new inode) and a laptop rsync
  into the live pack (sidecar hashes).
- Swap rollback: in the swap, after `mv "$PACK" "$PREV"`, if `mv "$STAGE" "$PACK"` fails, run
  `mv "$PREV" "$PACK"` and exit 2 with "ÉCHEC : installation impossible, ancien pack remis en
  place" (INSTALLED stays 0, no restart); if that rollback also fails, the OUTCOME gives the exact
  manual command (sudo mv /var/lib/jabuka/racepack.prev /var/lib/jabuka/racepack).
- Wi-Fi stays as decided (U1): cleanup ALWAYS switches back to the AP when this run switched, even if
  an SSH prerace started meanwhile (that prerace then fails safely and keeps its old pack); this
  caveat goes in the README (Task 3).
- status: when the unit is active and prerace is also active print "en attente de la fin de
  prerace : journalctl -fu jabuka-current", else "en cours : journalctl -fu jabuka-current".
- Keep every failure message French, mention "pack inchangé" whenever the live pack was not
  touched, and keep exit codes 0 / 2 for runs, 1 for launch refusals, 2 for usage.

B. touch/copernicusmarine-constraints.txt: generate with
`uv pip freeze --python ~/.local/share/uv/tools/copernicusmarine/bin/python` (64 pins, laptop env
that downloaded and validated the real file today), prefixed by a comment header saying what it is,
how it was produced, and that it is used by touch/install.sh only for /opt/copernicusmarine/venv.

C. touch/install.sh (U2), keeping every existing behavior and test: document the new overrides in
the header (CM_PYTHON default /usr/bin/python3; the internet probe uses curl from PATH with the
python urllib fallback). After the wrapper/config install and BEFORE daemon-reload, install
touch/jabuka-current as $SBIN/jabuka-current (0755) and call an `install_copernicusmarine` function
that can never abort the script under set -e: CM_VENV=$DESTDIR/opt/copernicusmarine/venv,
CM_VERSION=2.5.1; if "$CM_VENV/bin/copernicusmarine" --version reports "version 2.5.1" print
"copernicusmarine 2.5.1 déjà installé (/opt/copernicusmarine/venv)"; else if a HEAD probe of
https://pypi.org/simple/copernicusmarine/ fails print "copernicusmarine NON installé : pas
d'internet ; relancer sudo bash touch/install.sh avec internet (partage du téléphone : sudo
jabuka-wifi phone). Le reste de l'installation continue."; else create the venv with
"$CM_PYTHON" -m venv when $CM_VENV/bin/pip is missing, then run "$CM_VENV/bin/pip" install
--disable-pip-version-check --no-input --only-binary=:all: -c "$HERE/copernicusmarine-constraints.txt"
"copernicusmarine==$CM_VERSION"; on any failure print "copernicusmarine NON installé (voir les
erreurs pip ci-dessus). Le reste de l'installation continue." This venv is the only place
copernicusmarine goes: the script never references the race venvs for pip. Extend the final
heredoc with the jabuka-current usage and the one-time login line
(sudo /opt/copernicusmarine/venv/bin/copernicusmarine login). Do not put the literal string
"/opt/jabuka/" or "deploy/" on a non-comment line (existing parametrized test).

D. touch/uninstall.sh: also remove $DESTDIR/usr/local/sbin/jabuka-current; keep
/opt/copernicusmarine and say so in the final message (sudo rm -rf /opt/copernicusmarine to remove
it); no new systemctl call (the uninstall test checks the exact systemctl log).

E. tests/touch/test_install_files.py: extend the `env` fixture with CM_PYTHON = a stub that, for
`-m venv DIR`, creates DIR/bin/pip (logs "pip <args>" to LOG and, on install, creates
DIR/bin/copernicusmarine printing "copernicusmarine, version 2.5.1"; exit code from FAKE_PIP_RC)
and with PATH prefixed by a directory holding a curl stub whose exit code comes from FAKE_CURL_RC
(default 0), so no test ever touches the network or creates a real venv. Add "jabuka-current" to
the parametrized syntax/forbidden-path test. Add the installer behaviors above and a check that
every non-comment line of the constraints file is name==version and copernicusmarine==2.5.1 is
present.

F. docs/WEATHER-PACK.md (docs/ is not frozen; scripts/freeze-check.sh only guards src, deploy
except *.md and pyproject.toml): after the "Copernicus current: your own account (manual step)"
section add a short subsection, in the same language as that section, "On the Pi:
`sudo jabuka-current` (or COURANT in the touch menu)": one-time `sudo
/opt/copernicusmarine/venv/bin/copernicusmarine login` (the toolbox stores the credentials under
/root/.copernicusmarine; jabuka only passes the path), the window (jabuka-prep race window -6 h /
+2 h), Wi-Fi like prerace, install only when import + check pass and the current covers the window,
`sudo jabuka-current status`, and that LANCER PRERACE in the menu chains it after a prerace ending
with code 0 or 3.
  </action>
  <verify>
    <automated>cd /home/drico/git/jabuka && .venv313/bin/python -m pytest -q tests/touch/test_current_script.py tests/touch/test_install_files.py && bash -n touch/jabuka-current touch/install.sh touch/uninstall.sh && grep -c "jabuka-current" docs/WEATHER-PACK.md</automated>
  </verify>
  <done>All behaviors above are covered by passing tests; a failed Copernicus/import/coverage step, a pack modified during the run (simulated completed prerace swap) and a failing swap mv provably leave the live pack byte-identical (or put back) and the Wi-Fi back on the AP; no Wi-Fi switch is attempted while prerace is active; the installer installs jabuka-current and a separate pinned copernicusmarine venv and degrades to a clear message without internet; docs note present; committed as `feat(touch): jabuka-current robuste (Wi-Fi, refus, attente de prerace) et installation de copernicusmarine dans son venv` with the Co-Authored-By line.</done>
</task>

<task type="auto" tdd="true">
  <name>Task 3: menu chains prerace -> current, shows the current result and presence, journal of both units, README; full gate</name>
  <files>touch/jabuka_touch/actions.py, touch/jabuka_touch/ui.py, touch/jabuka_touch/status.py, touch/jabuka_touch/config.py, tests/touch/test_current_menu.py, tests/touch/test_actions.py, tests/touch/test_status.py, touch/README.md</files>
  <read_first>touch/jabuka_touch/status.py (Collector._prerace_step, collect_once, EXTRA_QUERIES, parse_prerace_last, pack_item), touch/jabuka_touch/config.py (Paths), touch/jabuka_touch/ui.py prep_lines and lines(), tests/touch/test_status.py lines 240-362, tests/touch/test_actions.py lines 130-179, touch/README.md</read_first>
  <behavior>
    - prerace action, nothing running, wall clock injected as 1794560000: calls exactly ["systemctl", "is-active", "jabuka-current.service"], ["/usr/local/sbin/prerace"], ["/usr/local/sbin/jabuka-current", "--after-prerace", "1794560000"]; outcome ok, lines include "Prerace lancé : suivre le journal" and a line saying the current follows if prerace ends with code 0 or 3.
    - prerace launch fails (rc 1): jabuka-current is never called and the failure lines are unchanged.
    - prerace launch ok but jabuka-current fails or is missing: outcome still ok (prerace runs) with a line "Courant non programmé (...)" pointing at the COURANT button.
    - jabuka-current.service active: prerace refused with "Courant en cours : attendre la fin (JOURNAL)", prerace not run. Demo active: refused before any command (existing test kept).
    - Collector: with current-last.txt (first line "courant : 2026-11-11T18:02:33Z", "résultat : OK : ...", "code : 0") and current.npz present, snapshot.extra["current"] has running False, present True and the parsed last result; the MÉTÉO (pack) item detail ends with a mention "courant : présent (téléchargé 2026-11-11T18:02:33Z)"; with no current.npz it mentions "courant : absent"; reading errors never raise.
    - prep info lines: second line is "Courant : <résultat> · <date> · code <n>", or "Courant : en cours (JOURNAL pour suivre)" when the unit is active, or "Courant : en attente de la fin de prerace" when both units are active, or "Courant : aucun téléchargement (bouton COURANT)".
    - journal extra query is journalctl with -u jabuka-prerace.service and -u jabuka-current.service; the journal header reads "Journal prerace + courant :".
  </behavior>
  <action>
Implements U3 (chaining, info line, MÉTÉO details) and the README half of U4. Tests first.

A. touch/jabuka_touch/actions.py: add CURRENT_UNIT = "jabuka-current.service". Change
prerace(runner, demo_active, wall=time.time): keep the demo refusal first; then
runner.run(["systemctl", "is-active", CURRENT_UNIT], 10.0) and refuse when its stdout is active /
activating / reloading; capture since = int(wall()) BEFORE launching prerace; launch prerace as
today; on failure return cmd_outcome unchanged; on success run [CURRENT, "--after-prerace",
str(since)] with 30 s and return Outcome(True, ...) with "Prerace lancé : suivre le journal", the
prerace tail (2 lines) and either "Courant : suivra prerace (si code 0 ou 3)" or "Courant non
programmé (<describe>) : bouton COURANT après prerace". The detached jabuka-current waits by
itself, so the single-flight worker is never blocked for the prerace duration and a menu restart
does not lose the chain. Update tests/touch/test_actions.py::test_prerace_and_wifi_argv to the new
call list (inject the wall clock through build_registry or test prerace() directly).

B. touch/jabuka_touch/config.py: add Paths fields current_last =
/var/lib/jabuka/current-last.txt and current_npz = /var/lib/jabuka/racepack/current.npz (defaults
for the Pi; tests always pass tmp paths).

C. touch/jabuka_touch/status.py: import CURRENT_UNIT and CURRENT; generalise parse_prerace_last
into parse_last(text, key) (keep parse_prerace_last as the key "prerace" wrapper for the existing
tests) and add parse_current_last (key "courant"; also treats an "en attente" first line as
running). Journal query: add "-u", CURRENT_UNIT after the prerace unit. Collector: a
`_current_step` called from _system (separate `systemctl is-active jabuka-current.service` call,
so existing FakeRunner prefixes keep working; read paths.current_last; current_npz existence in a
try/except OSError) storing {"running", "present", "last"}; publish it as extra["current"]. A pure
function pack_current(item, cur) returns the pack Item with " ; courant : présent (téléchargé
DATE)" (present and last code 0), " ; courant : présent" (present, no successful local download,
e.g. a laptop-built pack), " ; courant : téléchargement en cours" (running) or " ; courant :
absent" appended to the detail, level unchanged (current is optional); apply it in collect_once
when building the items tuple without mutating self._items (no accumulating suffix). Update the
Paths built in tests/touch/test_status.py fixtures to point current_last / current_npz into
tmp_path, and the journalctl argv assertion.

D. touch/jabuka_touch/ui.py: prep_lines inserts the current line (behavior block) right after the
prerace line, reading extra["current"] and snap.prerace_running; reduce the action tail to the last
2 lines so the 36-152 info band keeps the essentials; journal header "Journal prerace + courant :".
Update CONFIRM_TEXTS["prerace"] detail to "Météo puis courant Copernicus par le partage du
téléphone : Wi-Fi bateau coupé 10 à 30 min (deux fois)."

E. tests/touch/test_current_menu.py: add the behaviors above (FakeRunner with prefix responses,
Collector with tmp Paths and a fake fetch, UI prep_lines from a snapshot).

F. touch/README.md (French): in "Ce que montre et fait le menu", MÉTÉO / WI-FI now lists LANCER
PRERACE (météo puis courant si prerace finit en code 0 ou 3), COURANT, JOURNAL (prerace + courant);
add a section "Courant Copernicus (jabuka-current)": one-time `sudo
/opt/copernicusmarine/venv/bin/copernicusmarine login` (identifiants gardés par l'outil dans
/root/.copernicusmarine, jamais lus par jabuka), `sudo jabuka-current`, `sudo jabuka-current
status`, journalctl -fu jabuka-current, what it changes (staging, racepack.prev = the pack just
before; after a prerace + courant chain the pack from before prerace is no longer kept), refusals
(prerace, démo, déjà en cours), the second Wi-Fi drop when chained after prerace, after an SSH
`sudo prerace` run `sudo jabuka-current` once prerace is finished, and that starting a demo during a
current run makes it stop without installing anything. Add an explicit warning: never run `sudo
prerace` over SSH while COURANT / jabuka-current runs (prerace does not know about it: the boat
Wi-Fi may be switched back under it and its download fail; jabuka-current then refuses to install
« pack modifié pendant le courant : pack inchangé, relancer COURANT »); from the menu this cannot
happen (LANCER PRERACE is refused while the current runs). Installation section: install.sh now also
installs jabuka-current and copernicusmarine (needs internet once, else re-run later).

G. Gate: run the full gate and the freeze guard; rerun the two known flaky tests alone if they
fail. Run the render selftest with the system python and look at the prep PNG (the three-button row
must be legible).
  </action>
  <verify>
    <automated>cd /home/drico/git/jabuka && .venv313/bin/python -m pytest -q tests/touch && (cd touch && /usr/bin/python3 -m jabuka_touch selftest --out "$(mktemp -d)") && bash scripts/check.sh && frz_diff="$(/usr/bin/git diff --name-only 7c61a53 -- src deploy pyproject.toml)" && test -z "$frz_diff" && frz_st="$(/usr/bin/git status --porcelain -- src deploy pyproject.toml)" && test -z "$frz_st"</automated>
  </verify>
  <done>LANCER PRERACE chains the current step through `jabuka-current --after-prerace`, COURANT runs it alone, the prep info lines and the MÉTÉO details show the current state, the journal follows both units, README updated; tests/touch green on both venvs via scripts/check.sh (flaky UI tests rerun alone if needed), selftest prints « selftest : ok », freeze guard empty; committed as `feat(touch): LANCER PRERACE enchaîne le courant, état du courant dans le menu, README` with the Co-Authored-By line.</done>
</task>

</tasks>

<threat_model>
## Trust Boundaries

| Boundary | Description |
|----------|-------------|
| Copernicus servers -> Pi | NetCDF and catalogue responses from the internet (untrusted input) |
| Touch screen -> root scripts | taps become whitelisted argv run as root by the menu |
| root credentials file -> copernicusmarine | the user's Copernicus secret, root-only (0600) |
| PyPI -> /opt/copernicusmarine/venv | third-party packages installed as root |
| concurrent root jobs -> /var/lib/jabuka/racepack | prerace, jabuka-current and the demo all read or swap the live pack |

## STRIDE Threat Register

| Threat ID | Category | Component | Severity | Disposition | Mitigation Plan |
|-----------|----------|-----------|----------|-------------|-----------------|
| T-vew-01 | Information disclosure | touch/jabuka-current, CREDS | high | mitigate | Only `[ -f "$CREDS" ]` and `--credentials-file "$CREDS"`; never read, printed, copied or logged; static test on every non-comment use of the variable + a SECRET-token test over stdout, stderr, result and log (Task 1/2) |
| T-vew-02 | Tampering | NetCDF import | high | mitigate | Parsed only by jabuka-prep as user jabuka (runuser, nice) into a staging copy; swap only after import + check return 0/3 and the coverage gate; failures leave the live pack byte-identical (tested) |
| T-vew-03 | Elevation of privilege | actions.py -> jabuka-current | medium | mitigate | Executable whitelist + /usr/local/sbin only, argv lists without shell (test_isolation AST check), the only formatted value is int(wall()); the script rejects a non-numeric --after-prerace value (exit 2); the window one-liner runs with python -I so the jabuka-writable cwd cannot shadow imports |
| T-vew-04 | Denial of service | boat Wi-Fi | high | mitigate | Prerace's exact pattern: SWITCHED=1 before the switch, `_switch ap` in the EXIT trap, TERM/INT/HUP -> exit -> trap; RuntimeMaxSec=5400 on the unit, `timeout 900` on copernicusmarine, bounded prerace wait; local checks run before any Wi-Fi switch (tested) |
| T-vew-05 | Tampering | racepack swap races | medium | mitigate | systemd unit name as a lock; `guard` refusals (prerace active, demo drop-in) at launch, body start, before the internet probe/Wi-Fi switch, after download, after staging and before the swap; live-pack identity (PACK inode, sha256 of *.json sidecars, prerace-last.txt mtime) recorded at staging and re-checked before the swap, so a prerace that ran entirely during the current run is never overwritten by a stale staging copy (tested); `mv PREV PACK` rollback when the swap's second mv fails (tested); the menu refuses LANCER PRERACE while jabuka-current is active; distinct staging dir racepack.current-new; README warns against SSH `sudo prerace` during a current run (frozen prerace cannot check jabuka-current) |
| T-vew-06 | Denial of service | Pi 3B memory/CPU during copernicusmarine | low | accept | Run only before the race at the dock, nice -n 10, jabuka-core restarted only after a successful install; the orchestrator watches `free -m` during the on-Pi trial |
| T-vew-07 | Spoofing | internet probe / Copernicus endpoints | low | accept | HTTPS only (curl default certificate checks); a spoofed probe only decides whether to try the download |
| T-vew-SC | Tampering | pip install of copernicusmarine + dependencies | high | mitigate | Legitimacy: official Copernicus Marine Toolbox, in the project stack (CLAUDE.md, PyPI checked 2026-11-05) and used on the laptop to produce today's validated file. Exact pins for all 64 packages (laptop-validated constraints), copernicusmarine==2.5.1, --only-binary=:all: (no build scripts run), separate venv /opt/copernicusmarine/venv, never the race venvs; installed by the orchestrator, not by the executor |
</threat_model>

<verification>
- `.venv313/bin/python -m pytest -q tests/touch` and `bash scripts/check.sh` green (rerun
  tests/ui/test_start_ui.py::test_start_zone_and_times_on_the_map and
  test_switch_to_slovenian_then_english_persists_and_fits alone if they flake).
- Freeze guard: `/usr/bin/git diff --name-only 7c61a53 -- src deploy pyproject.toml` and
  `/usr/bin/git status --porcelain -- src deploy pyproject.toml` both empty.
- `cd touch && /usr/bin/python3 -m jabuka_touch selftest --out DIR` prints « selftest : ok ».
- `git ls-files -s touch/jabuka-current` shows mode 100755.
- Nothing was written to the Pi, nothing installed anywhere, the credentials file never read.
</verification>

<success_criteria>
- One command (`sudo jabuka-current`) or one confirmed tap (COURANT) fetches the Copernicus
  current for the race window and installs it only when it is valid and covers the window;
  LANCER PRERACE does weather then current in one confirmed tap.
- Every failure path leaves the live pack untouched, puts the boat Wi-Fi back and explains itself
  in French in current-last.txt and on the menu.
- copernicusmarine lives in its own pinned venv; the race venvs and every frozen file are
  unchanged.
</success_criteria>

<output>
Create `.planning/quick/261111-vew-etape-courant-copernicus-dans-le-prerace/261111-vew-SUMMARY.md`
when done. Staging: explicit paths only (no git add -A, stash, reset, clean); never stage
docs/I18N-SL-REVIEW.md.bak, deploy/secrets.env, uv.lock, orc/, var/, .gsd/, .planning/state.json,
cad/, stl/, hardware/, docs/SOAK.md, nor the quick-tasks table of .planning/STATE.md; no push.

Include an "On-Pi trial steps (for the orchestrator)" section:
1. Copy touch/ to the Pi; with internet (dock or `sudo jabuka-wifi phone`), `sudo bash
   touch/install.sh`: expect the copernicusmarine install message, then
   `/opt/copernicusmarine/venv/bin/copernicusmarine --version` = 2.5.1 and `ls -l
   /usr/local/sbin/jabuka-current`. Back to the AP if switched.
2. Record `sha256sum /var/lib/jabuka/racepack/*`, then `sudo jabuka-current`, follow
   `journalctl -fu jabuka-current` (watch `free -m`), then `sudo jabuka-current status`: OK, code 0,
   window 2026-11-13T11:00:00 -> 2026-11-15T11:00:00, "Courant : 49 échéances …"; `grep -i courant
   /var/lib/jabuka/racepack/coverage.txt` has no "désactivé"/"absent"; racepack.prev exists;
   `systemctl is-active jabuka-core` active; Wi-Fi back on the AP.
3. Menu: MÉTÉO / WI-FI shows the "Courant : OK …" line; COURANT -> OUI opens the journal; the
   MÉTÉO tile details say "courant : présent (téléchargé …)".
4. Failure trial: with no internet and the phone sharing off, COURANT -> OUI: result ÉCHEC, the AP
   comes back, sha256sum of the pack unchanged.
5. Optional: LANCER PRERACE -> OUI: the journal shows prerace then jabuka-current waiting, then the
   current run (boat Wi-Fi drops twice).
Never display the credentials file at any step.
</output>

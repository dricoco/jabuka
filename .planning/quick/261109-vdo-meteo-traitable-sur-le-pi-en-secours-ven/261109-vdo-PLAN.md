---
phase: quick-261109-vdo
plan: 01
type: execute
wave: 1
depends_on: []
files_modified:
  - deploy/prep.in
  - deploy/prep.lock
  - scripts/build-wheelhouse.sh
  - deploy/provision.sh
  - tests/deploy/test_lock.py
  - deploy/prerace
  - tests/deploy/test_prerace.py
  - tests/deploy/test_provisioning_files.py
  - deploy/PI-SETUP.md
  - docs/WEATHER-PACK.md
autonomous: true
requirements: [QUICK-261109-vdo]

estimate:
  tokens: 110000
  raw_tokens: 110000
  tasks: 3
  confidence: low

must_haves:
  truths:
    - "U-01/U-04: a Pi provisioned from a wheelhouse that contains prep/ gets /opt/jabuka-prep/venv with jabuka-prep, pygrib, shapely and netCDF4, installed offline with --no-index --require-hashes; the step never names /opt/jabuka/venv, so the app venv is untouched"
    - "U-02/U-03: `bash scripts/build-wheelhouse.sh` (WITHOUT --relock) creates deploy/prep.lock (aarch64/cp313, hashed, compiled with -c deploy/requirements.lock) and deploy/wheelhouse/prep/, and its offline install simulations (prep alone, app+prep union) pass; deploy/requirements.lock and deploy/fastnet2ip.lock are byte-identical before and after"
    - "U-04/U-07: `provision.sh --dry-run` prints step g2 (venv, two hash-locked pip installs, jabuka wheel --no-deps, jabuka-prep-pi symlink, prerace install) between Plan B and the systemd step, and `+ nmcli connection up jabuka-ap` is still the last mutating command"
    - "U-10: `sudo prerace` re-launches itself as transient unit jabuka-prerace (--collect), prints `suivre : journalctl -fu jabuka-prerace ; résultat : sudo prerace status` and exits; it refuses while jabuka-prerace is active"
    - "U-11..U-14: the detached body switches to the phone only when there is no internet and the jabuka-phone profile exists (otherwise it aborts with `lancer d'abord sudo jabuka-wifi phone une fois pour enregistrer le mot de passe`), ALWAYS returns to the AP if it switched, builds in racepack.new, installs on code 0 or 3 with exactly one racepack.prev, keeps the old pack untouched on 2/other, restarts jabuka-core only after an install, and writes /var/lib/jabuka/prerace-last.txt, which `sudo prerace status` shows"
    - "U-06/U-15: deploy/PI-SETUP.md §8 documents `sudo prerace` first and the manual commands as fallback; docs/WEATHER-PACK.md has one line pointing to it"
    - "U-09: no change under src/, deploy/systemd/, cad/, stl/, hardware/, docs/SOAK.md or the quick-task table/logs of .planning/STATE.md; the src/jabuka fingerprint is unchanged"
  artifacts:
    - path: deploy/prep.in
      provides: "Top-level pins of the Pi emergency weather-prep venv (pyproject `prep` extra minus osmium)"
    - path: deploy/prep.lock
      provides: "Hash lock aarch64/cp313 of the prep venv, constrained by deploy/requirements.lock"
    - path: scripts/build-wheelhouse.sh
      provides: "Locks, downloads, checks and simulates deploy/wheelhouse/prep like fastnet2ip"
    - path: deploy/provision.sh
      provides: "Step g2: /opt/jabuka-prep/venv + jabuka-prep-pi symlink + /usr/local/sbin/prerace"
    - path: deploy/prerace
      provides: "One-command weather prep on the Pi (detached, Wi-Fi switch, staging, swap, restart, status)"
    - path: tests/deploy/test_prerace.py
      provides: "Stubbed-PATH behaviour tests of deploy/prerace"
    - path: tests/deploy/test_lock.py
      provides: "prep.in/prep.lock checks (pins, hashes, Pi platform, shared packages identical to the app lock)"
    - path: tests/deploy/test_provisioning_files.py
      provides: "Dry-run tokens and ordering for step g2, AP still last"
    - path: deploy/PI-SETUP.md
      provides: "§8 Weather on the Pi (sudo prerace first, manual fallback)"
    - path: docs/WEATHER-PACK.md
      provides: "One line pointing to PI-SETUP §8"
  key_links:
    - from: scripts/build-wheelhouse.sh
      to: deploy/prep.lock
      via: "lock deploy/prep.in -> deploy/prep.lock with `-c deploy/requirements.lock` (only when absent or --relock)"
    - from: deploy/provision.sh
      to: "/opt/jabuka/wheelhouse/prep + /opt/jabuka/prep.lock"
      via: "step g2 pip install --no-index --require-hashes into /opt/jabuka-prep/venv"
    - from: deploy/prerace
      to: /usr/local/sbin/jabuka-wifi
      via: "`jabuka-wifi _switch phone` (synchronous) and `_switch ap` from the EXIT trap"
    - from: deploy/prerace
      to: /opt/jabuka-prep/venv/bin/jabuka-prep
      via: "runuser -u jabuka: wind / waves / [grib] / check with --out racepack.new --cache /var/lib/jabuka/cache/prep"
    - from: deploy/prerace
      to: /var/lib/jabuka/racepack
      via: "rename swap (racepack -> racepack.prev, racepack.new -> racepack) then systemctl restart jabuka-core"
---

<objective>
Make race-weather preparation possible ON the Raspberry Pi as an emergency fallback if the laptop dies, without touching the app.

1. A separate, hash-locked venv `/opt/jabuka-prep/venv` holds the GRIB/NetCDF tools. It is built exactly like the Plan B fastnet2ip venv: `deploy/prep.in` -> `deploy/prep.lock` -> `deploy/wheelhouse/prep`, installed by a new provision step g2.
2. One root command, `sudo prerace` (`deploy/prerace` -> `/usr/local/sbin/prerace`), does the whole job unattended: switch to the phone hotspot if needed, download and check the wind and waves into a staging copy, swap it in, restart jabuka-core, and always return to the boat AP.
3. Docs (PI-SETUP §8, WEATHER-PACK pointer) and tests are updated.

Purpose: the core value ("trustworthy steer-this from live data") needs a fresh weather pack on race day. Today only the laptop can build it, which is a single point of failure.
Output: the 10 files in `files_modified` and 3 commits. Nothing is pushed or deployed to the Pi; the orchestrator deploys.
</objective>

<user_locked_requirements>
These are user-locked (NON-NEGOTIABLE). There is no CONTEXT.md in quick mode, so they are numbered here for traceability.

- U-01: Separate venv `/opt/jabuka-prep/venv`. NEVER touch the app venv `/opt/jabuka/venv`. No `src/` edits; the src/jabuka fingerprint must not change.
- U-02: Follow EXACTLY the Plan B fastnet2ip pattern of `scripts/build-wheelhouse.sh` (in -> lock via `uv pip compile` for aarch64/cp313 with hashes, wheels downloaded into a wheelhouse subdir, wheel check, offline simulate). The lock is committed like `fastnet2ip.lock`; `deploy/wheelhouse/` is gitignored (verified: `.gitignore` line 12).
- U-03: New `deploy/prep.in` with `pygrib==2.1.8`, `shapely==2.2.0`, `netCDF4==1.7.5.1.post1` (the pyproject `prep` extra pins, NOT osmium). Compile `deploy/prep.lock` with `-c deploy/requirements.lock` so numpy etc. match the app lock. Wheels go to `deploy/wheelhouse/prep`.
- U-04: New provision step before the AP step (`nmcli connection up jabuka-ap` stays the LAST mutating command). It creates `/opt/jabuka-prep/venv` and installs `--no-index --require-hashes` from `requirements.lock` (wheelhouse `/opt/jabuka/wheelhouse`) and `prep.lock` (`/opt/jabuka/wheelhouse/prep`), then the jabuka wheel `--no-deps` (the same wheel as the app). Add the convenience symlink `/usr/local/bin/jabuka-prep-pi`. Warn (do not fail) if `wheelhouse/prep` is absent. `--dry-run` prints the commands.
- U-05: How pip `--require-hashes` handles two `-r` files that share packages. VERIFIED AT PLANNING TIME (2026-11-09):
  - The trial `uv pip compile deploy/prep.in -c deploy/requirements.lock ...` locks certifi, cftime, netcdf4, numpy, packaging, pygrib, pyproj, shapely.
  - numpy is the only package shared with the app lock, and its 66 hashes are byte-identical in both locks.
  - pip 26 accepts identical duplicate entries across two `-r` files (exit 0).
  - A hash-locked install of an already-satisfied package exits 0 ("Requirement already satisfied").
  - Decision: provision uses TWO separate pip invocations, which is robust to whatever pip the Pi venv bundles. build-wheelhouse.sh adds one combined app+prep dry-run simulate as the consistency proof.
- U-06: Docs. `deploy/PI-SETUP.md` gets a short section in English (the file is English) covering:
  - `sudo jabuka-wifi phone`
  - `sudo -u jabuka /opt/jabuka-prep/venv/bin/jabuka-prep wind --out /var/lib/jabuka/racepack`
  - `sudo systemctl restart jabuka-core`
  - `sudo jabuka-wifi ap`
  - about 100 MB of mobile data per ICON-EU run, and slower on a Pi 3
  - `jabuka-prep grib FILE` also works

  `docs/WEATHER-PACK.md` gets one line pointing to it.
- U-07: Update `tests/deploy/test_provisioning_files.py`: dry-run tokens for the new step, ordering, AP still last.
- U-08: Verify:
  - the build-wheelhouse run (relevant mode: WITHOUT `--relock`, see Task 1)
  - `.venv313/bin/pytest tests/deploy tests/commissioning` green
  - `bash -n deploy/provision.sh`
  - the provision `--dry-run` output
- U-09: Constraints:
  - NEVER touch `cad/`, `stl/`, `hardware/`, `docs/SOAK.md`, or the quick-task table/logs in `.planning/STATE.md`.
  - Stage by explicit paths only. Never use `git add -A`, `git stash`, `git reset` or `git clean`.
  - Do not push. Do not deploy to the Pi.
  - Every commit ends with `Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>`.
  - The pytest venv is `.venv313`.
- U-10 (coordinator addition): `deploy/prerace`, installed by provision.sh as `/usr/local/sbin/prerace` (mode 0755). `sudo prerace`:
  - re-launches itself detached via `systemd-run --unit=jabuka-prerace --collect`
  - prints `suivre : journalctl -fu jabuka-prerace ; résultat : sudo prerace status`, then exits
  - refuses if a jabuka-prerace unit is already running
- U-11: Detached body, Wi-Fi handling:
  - If there is no internet (`curl -sfI https://opendata.dwd.de` fails), require an existing jabuka-phone profile. Otherwise abort with `lancer d'abord sudo jabuka-wifi phone une fois pour enregistrer le mot de passe`.
  - Switch synchronously with `jabuka-wifi _switch phone`, then wait up to 60 s for internet.
  - ALWAYS return to the AP via a trap (`jabuka-wifi _switch ap`) if it switched.
- U-12: Build:
  - `rsync -a /var/lib/jabuka/racepack/` -> `/var/lib/jabuka/racepack.new/` (owned jabuka)
  - as jabuka: `jabuka-prep wind --out <staging>` (fatal on exit 2), then `jabuka-prep waves --out <staging>` (non-fatal), then `jabuka-prep check --out <staging>`
  - exit 0 = OK; 3 = MÉTÉO INCOMPLÈTE (install anyway, report loudly); 2/other = abort and keep the old pack untouched
- U-13: Install by rename swap: old -> `racepack.prev` (exactly one .prev kept), staging -> `racepack`. Then `chown jabuka` and `systemctl restart jabuka-core`.
- U-14: Write `/var/lib/jabuka/prerace-last.txt` (time, run used, exit status, tail of coverage.txt); `sudo prerace status` shows it. `sudo prerace --organiser FILE` adds `jabuka-prep grib FILE --name wind_organiser`, kept beside the pack and not used as wind.npz.
- U-15: Docs mention `sudo prerace` FIRST in the PI-SETUP section, with the manual steps as fallback. Tests:
  - a provision dry-run token for the prerace install
  - `bash -n deploy/prerace`
  - a stubbed-PATH behaviour test (included)
</user_locked_requirements>

<planning_findings>
Facts read from the code that the executor must honour:

- **jabuka-prep CLI** (`src/jabuka/prep/cli.py`):
  - Subcommands `wind`, `waves`, `grib FILE [--name N]`, `check` all take `--out` (default `var/racepack`) and `--cache` (default `var/cache/prep`, RELATIVE to cwd). Exit codes are `EXIT_OK, EXIT_USAGE, EXIT_INCOMPLETE = 0, 2, 3`.
  - `wind` already runs the coverage check and returns 3 when the chosen run is incomplete.
  - `check` returns 0 or 3 and writes `<out>/coverage.txt`. A `PrepError` returns 2.
  - The `grib --name` value must match `[a-z][a-z0-9_]{0,40}` (`wind_organiser` is valid).
- **Cache path deviation (U-06):** the locked manual command `sudo -u jabuka .../jabuka-prep wind --out /var/lib/jabuka/racepack` would fail. The default `--cache var/cache/prep` resolves against the caller's cwd (e.g. /home/drico), which the jabuka user cannot write. The docs and prerace therefore ALWAYS add `--cache /var/lib/jabuka/cache/prep`. This makes the locked command work; it does not reduce it.
- **Sidecar fields:** `wind.json` / `waves.json` carry `"model"` and `"run"` keys (e.g. `{"model":"ICON-EU","run":"2026-11-13T12:00:00Z",...}`). jq is installed on the Pi (provision APT_PACKAGES).
- **Pack location:** jabuka-core reads `/var/lib/jabuka/racepack` (default `<data-dir>/racepack`, `--data-dir /var/lib/jabuka`) and indexes it once at startup, so a restart after the swap is required.
- **jabuka-wifi** (`deploy/jabuka-wifi`, commit aa61b90):
  - `_switch phone` runs `nmcli -w 45 connection up jabuka-phone`. On failure it brings the AP back itself, and its exit status does NOT reliably signal failure, so prerace must re-test internet after the switch.
  - `_switch ap` runs `nmcli -w 30 connection up jabuka-ap`.
  - Both require root.
  - The phone profile name is `jabuka-phone`; detect it with `nmcli -g NAME connection show` and an exact line match.
- **Wheelhouse checks:** `check_wheels` in build-wheelhouse.sh globs `*.whl` non-recursively, so `wheelhouse/prep/` does not disturb the app wheelhouse check (same as `wheelhouse/fastnet2ip/`). The same holds for `test_wheelhouse` in test_lock.py.
- **Do NOT run `--relock`:** it would re-resolve `deploy/requirements.lock` and `deploy/fastnet2ip.lock` (transitive deps could move), which breaks U-01 and freeze-check F5 (sha256 of requirements.lock). The script locks a file only when it is missing, so a plain run creates only `deploy/prep.lock`.
- **No new file under `deploy/systemd/`:** prerace uses a transient unit. freeze-check F4 compares deploy/systemd at HEAD against the Pi's installed units.
- **Doc numbering:** `tests/commissioning/test_runbook_docs.py` resolves `PI-SETUP §N` references against `^## N.` headings, and checks that §7 links SOAK/COMMISSIONING/SPARE-SD/FREEZE. Append a NEW `## 8.` at the end of PI-SETUP.md and renumber nothing.
- **AP-stack scan:** `test_no_competing_ap_stack` scans every file under deploy/ (except the wheelhouse) for the names of the two legacy AP daemons listed in CLAUDE.md "What NOT to Use". `deploy/prerace` and `deploy/prep.in` must not mention them.
</planning_findings>

<execution_context>
@/home/drico/.claude/gsd-core/workflows/execute-plan.md
@/home/drico/.claude/gsd-core/templates/summary.md
</execution_context>

<context>
@.claude/CLAUDE.md
@scripts/build-wheelhouse.sh
@deploy/provision.sh
@deploy/jabuka-wifi
@deploy/fastnet2ip.in
@tests/deploy/test_provisioning_files.py
@tests/deploy/test_lock.py
@tests/deploy/conftest.py
@src/jabuka/prep/cli.py
@deploy/PI-SETUP.md
@docs/WEATHER-PACK.md
</context>

<tasks>

<task type="tracer">
  <name>Task 1: Hash-locked prep venv end to end (prep.in -> prep.lock -> wheelhouse/prep -> provision step g2)</name>
  <files>deploy/prep.in, deploy/prep.lock, scripts/build-wheelhouse.sh, deploy/provision.sh, tests/deploy/test_lock.py</files>
  <read_first>scripts/build-wheelhouse.sh (whole file), deploy/provision.sh steps f and g (lines 217-273), deploy/fastnet2ip.in, tests/deploy/test_lock.py (whole file), pyproject.toml [project.optional-dependencies] prep</read_first>
  <action>
**1. `deploy/prep.in`** (U-03): model the header on `deploy/fastnet2ip.in` (3 comment lines).
- Header says: Pi emergency weather prep (`jabuka-prep` wind/waves/grib/current/check on the Pi if the laptop dies), installed into its own venv `/opt/jabuka-prep/venv` from `deploy/wheelhouse/prep/` with --require-hashes; compiled with `-c deploy/requirements.lock` so shared packages (numpy) match the app; osmium is laptop-only and deliberately absent; re-lock with `bash scripts/build-wheelhouse.sh --relock`.
- Then exactly three requirement lines in this order: `pygrib==2.1.8`, `shapely==2.2.0`, `netCDF4==1.7.5.1.post1`.

**2. `scripts/build-wheelhouse.sh`** (U-02). Mirror the fastnet2ip pattern:
- Add `PREP_IN=deploy/prep.in`, `PREP_LOCK=deploy/prep.lock`, `PREP_WH=deploy/wheelhouse/prep` next to the F2I_* variables.
- Extend `lock()` to forward optional extra arguments (`"${@:3}"`) to `uv pip compile`, placed after the input file. This keeps the existing two calls byte-identical in effect.
- After the app-lock line add: `if [ "$RELOCK" -eq 1 ] || [ ! -f "$PREP_LOCK" ]; then lock "$PREP_IN" "$PREP_LOCK" -c "$LOCK"; fi`. It must come after the app lock so `$LOCK` exists.
- Add `download "$PREP_LOCK" "$PREP_WH"`, `check_wheels "$PREP_LOCK" "$PREP_WH" 0` and `simulate "$PREP_LOCK" "$PREP_WH"` beside the fastnet2ip calls.
- Add ONE combined dry-run simulate of the prep venv's union. Use the same pip flags as `simulate()`, but with `--find-links "$WH" --find-links "$PREP_WH"` and `-r "$LOCK" -r "$PREP_LOCK"`, preceded by an echo line saying it simulates the prep venv (app lock + prep lock). This proves the two provision installs resolve to one consistent set; identical duplicates were verified to be accepted (U-05).
- Update the header comment to mention `deploy/prep.in` -> `deploy/prep.lock` (constrained by requirements.lock), `deploy/wheelhouse/prep/`, and provision steps f, g and g2.
- If the header grows, update the `sed -n '2,12p'` range of `--help` so it still prints exactly the header comment block.

**3. `deploy/provision.sh`** (U-01, U-04):
- Add `PREP_VENV=/opt/jabuka-prep/venv` next to `F2I_VENV`.
- Insert a new step after step g (after the two fastnet2ip unit `install_file` lines) and before `step "h. systemd units and drop-ins"`. Title it `step "g2. emergency weather prep venv /opt/jabuka-prep/venv (separate from the app venv)"`, with a 2-line comment: hash-locked from the wheelhouse like Plan B; used only by `prerace` / `jabuka-prep-pi` when the laptop is unavailable (PI-SETUP section 8).
- Body, copying step g's structure exactly:
  - `PREP_LOCK="$SCRIPT_DIR/prep.lock"`, with the same missing-lock handling as `F2I_LOCK`: `die 3` in a real run, `warn` and continue in a dry run.
  - Then `if [ "$DRY_RUN" -eq 1 ] || [ -d "$OPT/wheelhouse/prep" ]; then`, containing in this order, each through `run`:
    - `install -m 0644 "$PREP_LOCK" "$OPT/prep.lock"`
    - `python3 -m venv "$PREP_VENV"`
    - `"$PREP_VENV/bin/pip" install --no-index --find-links "$OPT/wheelhouse" --require-hashes -r "$OPT/requirements.lock"`
    - `"$PREP_VENV/bin/pip" install --no-index --find-links "$OPT/wheelhouse/prep" --require-hashes -r "$OPT/prep.lock"`
    - `"$PREP_VENV/bin/pip" install --no-index --no-deps --force-reinstall "$OPT/wheelhouse/$JABUKA_WHEEL_NAME"` (the same wheel name computed in step f)
    - `ln -sfn "$PREP_VENV/bin/jabuka-prep" /usr/local/bin/jabuka-prep-pi`
  - `else` `warn "no prep/ in the wheelhouse: emergency weather prep NOT installed (re-run scripts/build-wheelhouse.sh)"`.
- These are two pip invocations, not one combined `-r -r` (U-05 decision: robust to the Pi venv's bundled pip).
- Nothing in this step may reference `$VENV` or `/opt/jabuka/venv` (U-01).
- Do not touch steps a-f, h-k or the AP block.

**4. Generate the lock and wheelhouse** (U-08). Run `bash scripts/build-wheelhouse.sh` WITHOUT `--relock` (the laptop has internet). It must end with `build-wheelhouse: ok`. Because `deploy/prep.lock` does not exist yet, only it gets locked; requirements.lock and fastnet2ip.lock are reused.
- Confirm `git diff --exit-code -- deploy/requirements.lock deploy/fastnet2ip.lock` is clean.
- The script also rebuilds the gitignored jabuka wheel from unchanged src; that is expected.
- If a prep package has no aarch64/cp313 wheel, STOP and report it. Do not loosen `--only-binary` and do not change pins.

**5. `tests/deploy/test_lock.py`.** Add a "Pi emergency weather prep" block modelled on the Plan B block:
- `EXPECTED_PREP_LOCKED`: the package set actually present in the generated lock. Planning-time trial: certifi, cftime, netcdf4, numpy, packaging, pygrib, pyproj, shapely. If the generated set differs, use the generated one and list the difference in the SUMMARY.
- A `prep_lock` fixture.
- `test_prep_in_is_the_pyproject_prep_extra_without_osmium`: `_requirements(prep.in)` equals the pyproject `prep` extra minus entries starting with `osmium`.
- `test_prep_lock_is_hashed_pinned_constrained_and_for_the_pi`:
  - every entry has hashes
  - pins from prep.in are honoured (normalised names)
  - the header contains `--python-platform aarch64-unknown-linux-gnu`, `--python-version 3.13`, `--generate-hashes` and `-c deploy/requirements.lock`
  - the set equals `EXPECTED_PREP_LOCKED`
  - there is no osmium
- `test_prep_lock_shares_packages_identically_with_the_app_lock`: every name present in both prep.lock and requirements.lock has the same version and the same sorted hash list.
- `test_prep_wheelhouse`: skip when `deploy/wheelhouse/prep` is absent; otherwise exactly one wheel per locked package at the locked version (copy the fastnet2ip wheelhouse test).
  </action>
  <verify>
    <automated>cd /home/drico/git/jabuka && bash -n scripts/build-wheelhouse.sh && bash -n deploy/provision.sh && git diff --exit-code -- deploy/requirements.lock deploy/fastnet2ip.lock && .venv313/bin/pytest -q tests/deploy/test_lock.py tests/deploy/test_provisioning_files.py && P=$(mktemp) && printf 'JABUKA_PSK=Dry-Run-Passphrase-01\n' > "$P" && bash deploy/provision.sh --dry-run --psk-file "$P" > "$P.out" && grep -F '/opt/jabuka-prep/venv/bin/pip install --no-index --find-links /opt/jabuka/wheelhouse/prep --require-hashes -r /opt/jabuka/prep.lock' "$P.out" && test "$(grep '^+ ' "$P.out" | tail -n 1)" = "+ nmcli connection up jabuka-ap" && rm -f "$P" "$P.out"</automated>
  </verify>
  <done>
- `bash scripts/build-wheelhouse.sh` ended with `build-wheelhouse: ok`: prep lock created, prep wheels downloaded and checked, prep-alone and app+prep union simulations passed. The SUMMARY records this as executor evidence; the run is too slow and network-bound for the automated gate.
- `deploy/prep.lock` exists, is hashed, and its header shows `-c deploy/requirements.lock`.
- `deploy/wheelhouse/prep/` holds one aarch64/cp313-compatible wheel per pin.
- requirements.lock and fastnet2ip.lock are unchanged.
- The provision dry-run shows the g2 commands and the AP is still last.
- test_lock.py (with the new prep tests) and the existing test_provisioning_files.py pass.
- Commit 1, staged by explicit paths only (`git add deploy/prep.in deploy/prep.lock scripts/build-wheelhouse.sh deploy/provision.sh tests/deploy/test_lock.py`). Message in French, e.g. `feat(deploy): venv météo de secours /opt/jabuka-prep sur le Pi (prep.lock, wheelhouse/prep)`, ending with the Co-Authored-By line.
  </done>
</task>

<task type="auto" tdd="true">
  <name>Task 2: `sudo prerace` — one command that prepares the race weather on the Pi (detached, Wi-Fi switch, staging, swap, status)</name>
  <files>deploy/prerace, tests/deploy/test_prerace.py, deploy/provision.sh, tests/deploy/test_provisioning_files.py</files>
  <read_first>deploy/jabuka-wifi (whole file: style, root check, detach(), do_switch(), French messages), deploy/provision.sh step g2 written in Task 1, tests/deploy/test_provisioning_files.py, tests/deploy/conftest.py, src/jabuka/prep/cli.py lines 31, 60-118, 128-147, 227-261, 301-347 (exit codes, --out/--cache, wind/check/grib)</read_first>
  <behavior>
All behaviours run `bash deploy/prerace` with a stubbed PATH; see the test harness in the action.
- Test 1 (launch, U-10): no args while jabuka-prerace is inactive.
  - exit 0
  - exactly one fake systemd-run call, containing `--unit=jabuka-prerace`, `--collect`, the absolute path of the script, and `_run`
  - stdout contains `suivre : journalctl -fu jabuka-prerace ; résultat : sudo prerace status`
  - no jabuka-prep call
- Test 2 (refuse, U-10): systemctl is-active reports active. Non-zero exit, stderr mentions the running preparation, no systemd-run call.
- Test 3 (launch with organiser, U-14): `--organiser rel/file.grb` (an existing file). The systemd-run args contain `--organiser` followed by the ABSOLUTE path. A missing file yields a non-zero exit and no systemd-run call.
- Test 4 (happy path, internet up, U-12/U-13): `_run` with an existing racepack containing marker file `old.txt`.
  - exit 0
  - racepack has the new `wind.json`; racepack.prev has `old.txt`; no racepack.new is left
  - call order: prep wind < prep waves < prep check < `systemctl restart jabuka-core`
  - every prep call carries `--out <data>/racepack.new` and `--cache <data>/cache/prep`
  - no jabuka-wifi call
  - prerace-last.txt contains `OK`, `ICON-EU run 2026-11-13T12:00:00Z`, `code : 0` and the fake coverage line
- Test 5 (exactly one .prev, U-13): two successive `_run` calls. racepack.prev holds the pack of the first run, not the original marker, and there is no second .prev-like directory.
- Test 6 (incomplete, U-12): fake check exits 3. Exit 3, the pack is installed, the restart happened, and prerace-last.txt contains `MÉTÉO INCOMPLÈTE`.
- Test 7 (wind fatal, U-12): fake wind exits 2.
  - exit 2
  - racepack still holds `old.txt` and no new wind.json; no racepack.prev was created
  - no restart call, no racepack.new left
  - prerace-last.txt contains `ÉCHEC`
- Test 8 (waves non-fatal): fake waves exits 2. Exit 0 and installed; prerace-last.txt mentions the waves failure.
- Test 9 (no internet, no phone profile, U-11):
  - exit 2
  - output (stdout or stderr) contains `lancer d'abord sudo jabuka-wifi phone une fois pour enregistrer le mot de passe`
  - no jabuka-wifi call, pack untouched
- Test 10 (no internet, profile exists, internet comes back after the switch, U-11):
  - calls contain `wifi _switch phone` before the prep calls
  - the LAST jabuka-wifi call is `wifi _switch ap`, after `systemctl restart jabuka-core`
  - exit 0
- Test 11 (no internet, profile exists, internet never comes, U-11):
  - exit 2, pack untouched
  - `wifi _switch ap` is still called (trap)
  - the wait loop polled internet a bounded number of times (fake sleep, so the test is instant)
- Test 12 (status, U-14): after a `_run`, `prerace status` prints the content of prerace-last.txt. With no result file it prints a "no run recorded" message and exits 0.
  </behavior>
  <action>
**A. Write `deploy/prerace`** (bash, mode 0755; commit it with the executable bit), in the style of `deploy/jabuka-wifi`: `#!/usr/bin/env bash`, `set -euo pipefail`, French user messages, English comments.

**Header comment** (`-h|--help` prints it with the same `sed -n` idiom as jabuka-wifi) documents:
- `sudo prerace`
- `sudo prerace --organiser FILE`
- `sudo prerace status`
- that it is installed by deploy/provision.sh as `/usr/local/sbin/prerace`
- PI-SETUP section 8

**Settings:**
- Overridable ONLY for the test harness via environment, and say so in a comment: sudo's env_reset and systemd-run both drop them in real use. The variables are:
  - `DATA="${PRERACE_DATA_DIR:-/var/lib/jabuka}"`
  - `PREP="${PRERACE_PREP:-/opt/jabuka-prep/venv/bin/jabuka-prep}"`
  - `WIFI="${PRERACE_WIFI:-/usr/local/sbin/jabuka-wifi}"`
- Fixed: `UNIT=jabuka-prerace`, `URL=https://opendata.dwd.de`.
- Derived paths, built with `${DATA:?}` so an empty DATA can never expand to `/racepack`:
  - `PACK=$DATA/racepack`, `STAGE=$DATA/racepack.new`, `PREV=$DATA/racepack.prev`
  - `CACHE=$DATA/cache/prep`, `RESULT=$DATA/prerace-last.txt`, `LOG=$DATA/prerace-last.log`
- `SELF="$(readlink -f "$0")"`.
- Every external tool is called by name through PATH (id, systemctl, systemd-run, nmcli, curl, runuser, chown, rsync, sleep, jq, nice) so the test can stub them.

**Root check:** `[ "$(id -u)" -eq 0 ]`, else die with `lancer avec sudo : sudo prerace ...`. It applies to every subcommand, because `/var/lib/jabuka` is 0750 jabuka.

**Dispatch:** `status` | `_run [--organiser ABS]` | `-h|--help` | default launch (no args, or `--organiser FILE`). Anything else dies with the usage line and exit 2.

**Launch (U-10):**
- If `systemctl is-active --quiet "$UNIT.service"` succeeds, print `une préparation est déjà en cours : journalctl -fu jabuka-prerace` to stderr and exit 1.
- If `--organiser FILE` was given, resolve it with `readlink -f` and require a regular file (otherwise die).
- If `$PREP` is not executable, die with a message saying the Pi weather venv is missing: re-run deploy/provision.sh with deploy/wheelhouse/prep (PI-SETUP §8).
- Run `systemd-run --quiet --unit="$UNIT" --collect --property=RuntimeMaxSec=3600 "$SELF" _run [--organiser ABS]`. RuntimeMaxSec is a safety cap: on timeout SIGTERM triggers the trap and the AP comes back.
- Print exactly `suivre : journalctl -fu jabuka-prerace ; résultat : sudo prerace status`, then exit 0.

**`_run` body (U-11..U-14):**

1. **Start:**
   - `cd "$DATA"`.
   - Truncate `$LOG`.
   - Initialise globals: `SWITCHED=0`, `INSTALLED=0`, `OUTCOME="ÉCHEC : interrompu"`, `NOTES=""`, `WIFI_NOTE="non utilisé"`.
   - Set `trap cleanup EXIT` and `trap 'exit 143' TERM INT HUP`, so a systemctl stop or RuntimeMaxSec still runs the cleanup.
   - Echo the Pi UTC time (`date -u`) so a wrong clock is visible in the journal.

2. **Internet check (U-11):** `have_internet` = `curl -sfI --max-time 10 -o /dev/null "$URL"`. If curl is absent, fall back to `python3 -c` with urllib.request.urlopen(URL, timeout=10).
   - If there is no internet:
     - Require the profile via `nmcli -g NAME connection show` with an exact-line grep for `jabuka-phone`. If it is missing, set OUTCOME to `ÉCHEC : pas d'internet et aucun profil jabuka-phone : lancer d'abord sudo jabuka-wifi phone une fois pour enregistrer le mot de passe`, echo the same to stderr, and exit 2.
     - Set `SWITCHED=1` BEFORE calling `"$WIFI" _switch phone || true`, so the trap returns to the AP even after a half-failed switch.
     - Poll have_internet up to 12 times with `sleep 5` between attempts (about 60 s). If still offline, set OUTCOME to `ÉCHEC : pas d'internet par le partage du téléphone (partage activé ?)` and exit 2.
     - Set `WIFI_NOTE="partage du téléphone"`.

3. **Staging (U-12):**
   - `rm -rf "$STAGE"`, then `mkdir -p "$CACHE"`.
   - If `$PACK` is a directory, copy it with `rsync -a "$PACK/" "$STAGE/"`, falling back to `cp -a "$PACK" "$STAGE"` when rsync is absent. Otherwise `mkdir -p "$STAGE"`.
   - `chown -R jabuka:jabuka "$STAGE" "$DATA/cache"`.

4. **prep helper** (`prep CMD ARGS...`): `runuser -u jabuka -- nice -n 10 "$PREP" CMD ARGS... --out "$STAGE" --cache "$CACHE" 2>&1 | tee -a "$LOG"`.
   - Capture the exit status without tripping set -e: `rc=0; pipeline || rc=$?`. With pipefail this yields jabuka-prep's code.
   - nice keeps jabuka-core responsive on the Pi 3. jabuka-prep never runs as root, because GRIB parsing is untrusted input.

5. **Steps:**
   - `wind`: a code outside {0,3} sets OUTCOME `ÉCHEC : vent (code N), ancien pack conservé` and exits 2.
   - `waves`: a code outside {0,3} only appends `vagues : échec (code N), pack sans vagues à jour` to NOTES.
   - If `--organiser ABS` was given:
     - copy the file into `$CACHE/<basename>` and chown it jabuka
     - run `prep grib "$CACHE/<basename>" --name wind_organiser` (non-fatal; append a note on failure)
     - remove the copied input afterwards
   - `check`: a code outside {0,3} sets OUTCOME `ÉCHEC : contrôle du pack (code N), ancien pack conservé` and exits 2.
   - `STATUS=3` if the wind or check code is 3, else 0.

6. **Install (U-13):**
   - `rm -rf "$PREV"`
   - if `$PACK` exists, `mv "$PACK" "$PREV"`
   - `mv "$STAGE" "$PACK"`
   - `chown -R jabuka:jabuka "$PACK"`
   - `INSTALLED=1`
   - `systemctl restart jabuka-core.service`
   - `rm -rf "$CACHE"`: purge downloads only after a successful install. On failure they stay, so a retry resumes; this keeps about 100 MB per run off the SD card.
   - OUTCOME is `OK : pack installé, jabuka-core redémarré` for 0, or `MÉTÉO INCOMPLÈTE : pack installé quand même, lire la couverture` for 3.
   - For 3, also echo a loud banner line starting with `!!! MÉTÉO INCOMPLÈTE`.
   - `exit "$STATUS"`.

7. **cleanup (EXIT trap), in this order:**
   - capture rc
   - `trap - EXIT`
   - if SWITCHED is 1: `"$WIFI" _switch ap`, setting WIFI_NOTE to `partage du téléphone puis retour au point d'accès` on success or `... ÉCHEC du retour AP : sudo jabuka-wifi ap ou redémarrer` on failure
   - write the result file
   - if INSTALLED is 0, `rm -rf "$STAGE"`
   - cat the result file to stdout (journal)
   - `exit "$rc"`

   Every command inside cleanup is guarded with `|| true` so cleanup itself can never abort halfway.

8. **Result file (U-14):** write `$RESULT.tmp`, then `mv` it to `$RESULT`. Lines:
   - `prerace : <date -u +%Y-%m-%dT%H:%M:%SZ>`
   - `résultat : $OUTCOME`
   - `code : $rc`
   - `vent : <model> run <run>`, read with `jq -r` from the INSTALLED pack's wind.json, or the staging one if not installed. Use `?` if jq or the file is missing.
   - `vagues : <model> run <run>`, same rule for waves.json
   - `Wi-Fi : $WIFI_NOTE`
   - `notes : $NOTES` (only if non-empty)
   - a separator line `--- coverage.txt (fin) ---` and `tail -n 20` of the matching coverage.txt
   - on a non-zero, non-3 rc, also `--- journal (fin) ---` and `tail -n 15 "$LOG"`

**`status`:**
- If `systemctl is-active --quiet "$UNIT.service"` succeeds, print `en cours : journalctl -fu jabuka-prerace`.
- Then cat `$RESULT`, or print `aucune préparation enregistrée (sudo prerace pour en lancer une)`.
- Exit 0.

The script must not contain the names of the two legacy AP daemons (test_no_competing_ap_stack) and must never print or handle the phone PSK.

**B. `deploy/provision.sh`:** at the end of step g2, OUTSIDE the `if -d wheelhouse/prep` block, install prerace exactly like jabuka-wifi in step f: `if [ -f "$SCRIPT_DIR/prerace" ]; then run install -m 0755 "$SCRIPT_DIR/prerace" /usr/local/sbin/prerace; fi`. prerace itself reports a missing venv at run time.

**C. `tests/deploy/test_prerace.py`** (write the tests first, RED, then the script, GREEN).

Fixture `env(tmp_path)`:
- creates `data/racepack/old.txt` and a `fakebin/` dir of small executable bash stubs that append one line (`<name> <args>`) to `$FAKE_CALLS`. The stubs are:
  - `id`: prints 0 for `-u`, otherwise execs the real id
  - `systemctl`: for `is-active` exits `${FAKE_ACTIVE_RC:-3}`, else 0
  - `systemd-run`: exits 0
  - `nmcli`: prints `jabuka-ap` plus `jabuka-phone` when `FAKE_PHONE=1`
  - `curl`: uses a counter file. It fails while the count is below `FAKE_CURL_FAILS` (default 0; `always` = never succeeds), then exits 0
  - `runuser`: drops `-u USER --` and execs the rest
  - `chown`, `sleep`: no-op
  - `jabuka-wifi`: records `wifi <args>`
  - `jabuka-prep` parses `--out` and acts on the subcommand:
    - `wind`: writes `wind.json` `{"model":"ICON-EU","run":"2026-11-13T12:00:00Z"}` plus `wind.npz` and exits `FAKE_RC_WIND`, writing nothing on 2
    - `waves`: writes `waves.json` (model EWAM) and exits `FAKE_RC_WAVES`
    - `grib`: writes `wind_organiser.json`
    - `check`: writes `coverage.txt` with `COUVERTURE MÉTÉO : OK` (or `MÉTÉO INCOMPLÈTE : test` when `FAKE_RC_CHECK=3`) and exits `FAKE_RC_CHECK`
- Run with env: `PATH=fakebin:<real PATH>`, `PRERACE_DATA_DIR`, `PRERACE_PREP`, `PRERACE_WIFI`, `FAKE_CALLS`, a 60 s timeout. Real rsync/jq/nice/tee are used when present; the script falls back to `cp -a` without rsync, and the tests do not depend on jq beyond the `?` fallback, so skip only the run-line assertion if jq is absent.

Implement Tests 1-12 from `<behavior>`. Also:
- `test_bash_syntax` (`bash -n deploy/prerace`)
- `test_prerace_is_executable` (`os.access(X_OK)`)

**D. `tests/deploy/test_provisioning_files.py`** (U-07, U-15):
- Add to `test_dry_run_prints_every_required_step`:
  - `python3 -m venv /opt/jabuka-prep/venv`
  - `/opt/jabuka-prep/venv/bin/pip install --no-index --find-links /opt/jabuka/wheelhouse --require-hashes -r /opt/jabuka/requirements.lock`
  - `/opt/jabuka-prep/venv/bin/pip install --no-index --find-links /opt/jabuka/wheelhouse/prep --require-hashes -r /opt/jabuka/prep.lock`
  - `--no-deps --force-reinstall /opt/jabuka/wheelhouse/jabuka-` (prefix: the wheel name depends on whether the local wheelhouse exists)
  - `prep.lock /opt/jabuka/prep.lock`
  - `ln -sfn /opt/jabuka-prep/venv/bin/jabuka-prep /usr/local/bin/jabuka-prep-pi`
  - `/usr/local/sbin/prerace`
- In `test_dry_run_order`, insert `/opt/jabuka-prep/venv/bin/pip install` and `/usr/local/sbin/prerace` between `/opt/fastnet2ip/venv/bin/pip install` and `systemctl enable jabuka-ingest-fastnet.service`. Keep the AP-last assertion.
- Add `test_prep_venv_is_hash_locked_and_separate`:
  - exactly 3 `+ ` lines contain `/opt/jabuka-prep/venv/bin/pip install`, each with `--no-index`
  - the two `-r` ones carry `--require-hashes`; the wheel one carries `--no-deps`
  - exactly 2 `+ ` lines still contain `/opt/jabuka/venv/bin/pip install` (step f only)
  - no `+ ` line between the `== g2.` and `== h.` headers contains `/opt/jabuka/venv/`
- Add `test_prep_step_warns_when_wheelhouse_prep_absent`: a static text check that provision.sh contains `"$OPT/wheelhouse/prep"` and `emergency weather prep NOT installed`.
  </action>
  <verify>
    <automated>cd /home/drico/git/jabuka && bash -n deploy/prerace && test -x deploy/prerace && .venv313/bin/pytest -q tests/deploy/test_prerace.py tests/deploy/test_provisioning_files.py tests/deploy/test_lock.py</automated>
  </verify>
  <done>
- All 12 behaviours pass, plus syntax and executable checks.
- The provision dry-run tests cover g2 and the prerace install, and the AP is still last.
- `git ls-files -s deploy/prerace` shows mode 100755 after staging.
- Commit 2, staged by explicit paths only (`git add deploy/prerace tests/deploy/test_prerace.py deploy/provision.sh tests/deploy/test_provisioning_files.py`). French message, e.g. `feat(deploy): sudo prerace prépare la météo sur le Pi (partage téléphone, pack en staging, retour AP)`, ending with the Co-Authored-By line.
  </done>
</task>

<task type="auto">
  <name>Task 3: Docs (PI-SETUP §8 with `sudo prerace` first, WEATHER-PACK pointer) and the full verification gate</name>
  <files>deploy/PI-SETUP.md, docs/WEATHER-PACK.md</files>
  <read_first>deploy/PI-SETUP.md sections 3, 6 and 7 (lines 104-137, 297-386), docs/WEATHER-PACK.md lines 48-75 and 124-171, tests/commissioning/test_runbook_docs.py lines 86-110, 215-260, 316-323 (section numbering and §-reference rules)</read_first>
  <action>
**1. `deploy/PI-SETUP.md`** (U-06, U-15). Append a NEW section at the very end, after section 7, titled `## 8. Weather on the Pi (laptop dead): sudo prerace`. Renumber nothing; §7 must keep its four doc links. Write it in English, consistent with the file, keeping prerace's French messages verbatim in backticks.

Content, in order:
- **When to use it.** The laptop is dead or absent at the dock. The Pi carries its own copy of the prep tools in `/opt/jabuka-prep/venv`, separate from the app venv `/opt/jabuka/venv`. Provision step g2 installs it from `deploy/wheelhouse/prep`, which `bash scripts/build-wheelhouse.sh` builds with the rest. The app is never modified by it.
- **Check after provisioning.** `/opt/jabuka-prep/venv/bin/python -c "import pygrib, shapely, netCDF4"` and `jabuka-prep-pi --help`.
- **One-time prerequisite.** `sudo jabuka-wifi phone` to save the hotspot password, then `sudo jabuka-wifi ap` (see section 6).
- **Main path, first.** `sudo prerace`. Describe in a short numbered list what it does:
  - It runs detached as unit `jabuka-prerace`, so an SSH session over the boat AP that drops does not stop it.
  - It uses the phone hotspot only if the Pi has no internet, and always comes back to the `jabuka` AP at the end, even on failure.
  - It copies the current pack to `/var/lib/jabuka/racepack.new`, then runs ICON-EU `wind` (fatal on error), EWAM `waves` (optional) and `check`.
  - It swaps the new pack in, keeps the previous one as `racepack.prev`, and restarts jabuka-core.
- **Follow it and read the result.** `journalctl -fu jabuka-prerace`, then `sudo prerace status`. What the result means:
  - OK = installed.
  - `MÉTÉO INCOMPLÈTE` = installed anyway; read the coverage lines and the WEATHER-PACK.md section "Reading the coverage report".
  - `ÉCHEC` = the old pack is untouched.
- **Cost and timing.** About 100 MB of mobile data per ICON-EU run, plus a few MB for waves. It is several times slower on the Pi 3 than on the laptop, so start well before the weather window. The SSH session drops when the Wi-Fi switches; reconnect afterwards.
- **Organiser forecast.** `sudo prerace --organiser FILE` writes `wind_organiser` beside the pack, unused. Rename it per WEATHER-PACK.md to use it.
- **Rollback.** A command block that, as root:
  - moves `/var/lib/jabuka/racepack` to `racepack.bad`
  - moves `racepack.prev` to `racepack`
  - runs `sudo systemctl restart jabuka-core`
- **Manual fallback** (if prerace itself fails). A command block with the four locked commands, in order:
  - `sudo jabuka-wifi phone`
  - `sudo -u jabuka /opt/jabuka-prep/venv/bin/jabuka-prep wind --out /var/lib/jabuka/racepack --cache /var/lib/jabuka/cache/prep`
  - `sudo systemctl restart jabuka-core`
  - `sudo jabuka-wifi ap`

  Then add three notes:
  - Why `--cache` is required: the default cache path is relative to the current directory, which the jabuka user cannot write.
  - The manual path writes the live pack in place (no staging, no .prev).
  - `jabuka-prep grib FILE` works the same way, with FILE readable by jabuka (e.g. copied to /tmp) and the same `--out`/`--cache`, optionally with `--name wind_organiser`.

In section 6, append one sentence to the existing "Internet on the Pi through a phone hotspot" bullet: to build the race weather on the Pi itself, see section 8 (`sudo prerace`).

**2. `docs/WEATHER-PACK.md`** (U-06). Add exactly one bullet to the French list under `### Si DWD est en retard`:
- Portable en panne : le Pi prépare la météo lui-même avec `sudo prerace` (partage du téléphone, ~100 Mo par run ICON-EU) ; voir [deploy/PI-SETUP.md §8](../deploy/PI-SETUP.md).

Nothing else changes in that file.

**3. Full gate** (U-08):
- `bash -n` on provision.sh, prerace and build-wheelhouse.sh.
- `.venv313/bin/pytest -q tests/deploy tests/commissioning` must be all green.
- `.venv313/bin/ruff check tests/deploy` (if ruff is in .venv313).
- A provision dry-run with a temporary PSK file (never `deploy/secrets.env`). Inspect step g2 and confirm the last `+ ` line is `+ nmcli connection up jabuka-ap`.
- `git diff --quiet HEAD~2 -- src deploy/systemd deploy/requirements.lock deploy/fastnet2ip.lock cad stl hardware docs/SOAK.md`. HEAD~2 is relative to the base before commit 3; adjust to the pre-task base commit aa61b90 if simpler.
- `git status --short` shows no unintended modified tracked files. Pre-existing untracked files (`.gsd/`, `uv.lock`, `orc/`, `*.bak`, `.planning/research/.cache`, ...) are left alone and never staged.

**4. Commit 3,** staged by explicit paths only (`git add deploy/PI-SETUP.md docs/WEATHER-PACK.md`). French message, e.g. `docs: météo sur le Pi en secours, sudo prerace (PI-SETUP §8, WEATHER-PACK)`, ending with the Co-Authored-By line. Do not push. Do not deploy.
  </action>
  <verify>
    <automated>cd /home/drico/git/jabuka && bash -n deploy/provision.sh && bash -n deploy/prerace && bash -n scripts/build-wheelhouse.sh && grep -q '^## 8\. Weather on the Pi' deploy/PI-SETUP.md && grep -q 'sudo prerace' deploy/PI-SETUP.md && grep -q -- '--cache /var/lib/jabuka/cache/prep' deploy/PI-SETUP.md && grep -q 'sudo prerace' docs/WEATHER-PACK.md && .venv313/bin/pytest -q tests/deploy tests/commissioning && git diff --quiet aa61b90 -- src deploy/systemd deploy/requirements.lock deploy/fastnet2ip.lock docs/SOAK.md</automated>
  </verify>
  <done>
- PI-SETUP.md has §8 with `sudo prerace` first, the follow/status/codes, the cost and timing note, organiser use, rollback, and the manual fallback (the four locked commands, with `--cache` explained).
- §6 points to §8, and WEATHER-PACK.md has the single pointer bullet.
- `tests/deploy` and `tests/commissioning` are fully green.
- src/, deploy/systemd, both pre-existing locks and docs/SOAK.md are unchanged since aa61b90.
- 3 commits exist, none pushed.
  </done>
</task>

</tasks>

<threat_model>
## Trust Boundaries

| Boundary | Description |
|----------|-------------|
| PyPI -> laptop wheelhouse -> Pi | Third-party wheels (pygrib, shapely, netCDF4 + pyproj, cftime, certifi, packaging) enter the appliance |
| Internet (DWD over the phone hotspot) -> jabuka-prep | Downloaded GRIB bytes are untrusted input parsed on the Pi |
| sudo user -> prerace (root) | prerace runs as root and calls nmcli, rename/rm under /var/lib/jabuka, and systemctl |
| prerace (root) -> jabuka-prep (jabuka) | Privilege drop before any download or parse |
| Wi-Fi mode | While on the phone, tablets lose the `jabuka` AP (availability at the helm) |

## STRIDE Threat Register

| Threat ID | Category | Component | Severity | Disposition | Mitigation Plan |
|-----------|----------|-----------|----------|-------------|-----------------|
| T-vdo-SC | Tampering | deploy/prep.lock, wheelhouse/prep | high | mitigate | No new top-level package: the three pins are the pyproject `prep` extra already used on the laptop since Phase 3. Transitive deps are mainstream (pyproj, cftime, certifi, packaging). Everything is installed offline with `--no-index --require-hashes` from a hash lock compiled with `-c requirements.lock`. test_lock asserts the exact package set (any new name fails the test and forces a review). Shared packages must be hash-identical to the app lock. No live PyPI on the Pi. |
| T-vdo-01 | Elevation of privilege | deploy/prerace -> jabuka-prep | high | mitigate | Every jabuka-prep call (download plus GRIB/NetCDF parse) runs via `runuser -u jabuka -- nice -n 10`, never as root. The venv is root-owned and read-only to jabuka. |
| T-vdo-02 | Denial of service | Wi-Fi left on the phone hotspot | high | mitigate | SWITCHED is set before the switch. The EXIT trap plus TERM/INT/HUP -> exit run `jabuka-wifi _switch ap`. The transient unit has RuntimeMaxSec=3600. jabuka-wifi already falls back to the AP if the phone disappears, and a reboot starts on the AP. Tests 10/11 assert that the AP return is the last Wi-Fi action, including on abort. |
| T-vdo-03 | Tampering | /var/lib/jabuka/racepack (half-built pack) | high | mitigate | Build in racepack.new; install only on exit 0/3 by rename swap; keep exactly one racepack.prev; abort (2/other) leaves the live pack untouched and removes staging. Paths use `${DATA:?}`. Tests 4-8 cover this. |
| T-vdo-04 | Elevation of privilege | PRERACE_* env overrides | low | accept | They exist only for the stubbed-PATH tests. sudo env_reset drops them, systemd-run does not forward them, and anyone able to set them for a root process is already root. |
| T-vdo-05 | Information disclosure | phone hotspot PSK | medium | mitigate | prerace never reads, prompts for or prints the PSK. It only uses the jabuka-phone profile that jabuka-wifi stores 0600 in NetworkManager. |
| T-vdo-06 | Information disclosure | `--organiser FILE` copy (root reads, jabuka parses) | low | accept | Only a sudoer (already root) can name the file. It is copied to the jabuka cache only for the parse and removed right after. |
| T-vdo-07 | Denial of service | concurrent runs / SD space | low | mitigate | The fixed unit name plus an is-active refusal gives one run at a time. The download cache is purged after a successful install, and the router keeps priority via nice and OOMScoreAdjust (core -500). |
</threat_model>

<verification>
- `bash scripts/build-wheelhouse.sh` (no --relock) ends with `build-wheelhouse: ok`, and `deploy/requirements.lock` and `deploy/fastnet2ip.lock` are unchanged.
- `bash -n deploy/provision.sh deploy/prerace scripts/build-wheelhouse.sh` (each file).
- `.venv313/bin/pytest -q tests/deploy tests/commissioning`: all green.
- The provision dry-run shows step g2 (venv, two hash-locked installs, jabuka wheel --no-deps, jabuka-prep-pi, prerace), and its last mutating command is `+ nmcli connection up jabuka-ap`.
- No change under src/, deploy/systemd/, cad/, stl/, hardware/, docs/SOAK.md; the .planning/STATE.md quick-task table is untouched.
</verification>

<success_criteria>
- If the laptop dies, the owner types `sudo prerace` on the Pi; the boat AP always comes back; a fresh (or loudly flagged incomplete) pack is live with jabuka-core restarted; `sudo prerace status` explains the outcome.
- The Pi prep venv is hash-locked and offline-installed exactly like Plan B, and the app venv and code fingerprint are unchanged.
- 3 atomic commits staged by explicit paths, none pushed, nothing deployed.
</success_criteria>

<output>
Create `.planning/quick/261109-vdo-meteo-traitable-sur-le-pi-en-secours-ven/261109-vdo-SUMMARY.md` when done. Include:
- the generated prep.lock package set (vs the planning-time trial)
- the build-wheelhouse output tail
- the dry-run g2 excerpt
- the test counts

Also note for the orchestrator:
- (a) Copy `deploy/wheelhouse/` including `prep/` to the Pi, then re-run provision.
- (b) This change touches `deploy/` (non-.md), so the freeze-check F3 git rule will flag a laptop soak report older than these commits.
- (c) Re-check the Pi 3 memory and runtime of a real `sudo prerace` at the dock.
</output>

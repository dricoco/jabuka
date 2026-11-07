---
phase: 04-race-readiness-hardening-commissioning
reviewed: 2026-11-07T14:19:03Z
depth: standard
files_reviewed: 45
files_reviewed_list:
  - pyproject.toml
  - scripts/bootstrap-dev.sh
  - scripts/commissioning-rehearsal.sh
  - scripts/freeze-check.sh
  - scripts/soak.sh
  - src/jabuka/common/atomicio.py
  - src/jabuka/core/router_service.py
  - src/jabuka/ingest/gpsd_client.py
  - src/jabuka/ingest/rawlog.py
  - src/jabuka/nav/course.py
  - src/jabuka/nav/settings.py
  - src/jabuka/route/advice.py
  - src/jabuka/sim/synth.py
  - src/jabuka/soak/__init__.py
  - src/jabuka/soak/faults.py
  - src/jabuka/soak/pack.py
  - src/jabuka/soak/probes.py
  - src/jabuka/soak/report.py
  - src/jabuka/soak/scenario.py
  - src/jabuka/soak/scenarios/ci.json
  - src/jabuka/soak/scenarios/gpsclock-ci.json
  - src/jabuka/soak/scenarios/race-36h.json
  - src/jabuka/soak/scenarios/tracer.json
  - src/jabuka/soak/supervisor.py
  - src/jabuka/soak/systemd.py
  - src/jabuka/soak/tablet.py
  - src/jabuka/tools/rehearsal.py
  - src/jabuka/tools/soak.py
  - src/jabuka/web/static/i18n.js
  - tests/commissioning/test_freeze_check.py
  - tests/commissioning/test_rehearsal.py
  - tests/commissioning/test_runbook_docs.py
  - tests/gps/test_gpsd_client_cancel.py
  - tests/nav/test_state_corruption.py
  - tests/routing/test_clock_step_back.py
  - tests/sim/test_follow_helm_faults.py
  - tests/sim/test_synth_control.py
  - tests/soak/conftest.py
  - tests/soak/test_ci_soak.py
  - tests/soak/test_soak_probes.py
  - tests/soak/test_soak_systemd.py
  - tests/soak/test_soak_tablet.py
  - tests/soak/test_soak_tracer.py
  - tests/soak/test_soak_units.py
  - tests/test_rawlog_full_disk.py
findings:
  critical: 0
  warning: 5
  info: 9
  total: 14
status: issues_found
---

# Phase 4: Code Review Report

**Reviewed:** 2026-11-07T14:19:03Z
**Depth:** standard
**Files Reviewed:** 45
**Status:** issues_found

## Narrative Findings (AI reviewer)

## Summary

The review covered the boat-side production changes (atomicio `load_json_status`, rawlog whole-line buffering, gpsd cancel fix, course/settings unreadable alerts, router route-expiry / pool watchdog / clock-step handling, advice route-time projection window) and the soak harness. The harness review focused on the `--systemd system` backend, which restarts the installed production units as root.

I found no BLOCKER. The production code is careful: rawlog rollback-to-last-whole-line is correct, `_withdrawal` and `should_replace(forced=True)` clear a restored or withdrawn route on the first good cycle, and the French server strings added this phase match the `i18n.js` FR table exactly.

The main risks are in the system-scope soak:

- Its cleanup is marked done before any work starts, so an interrupted cleanup gets no retry.
- It accepts a RAM tmpfs on the 1 GB Pi by default. An OOM kill of the root harness skips cleanup entirely, which leaves the production core on `--clock sim` with a fake gpsd until reboot.
- Its report certifies the checkout's git HEAD, while the code that actually ran is the wheel installed in `/opt/jabuka/venv`.

On the boat side, two problems stand out. A corrupted main state file silently reverts to `.bak`, which can roll back course progress. A recycled (wedged) router pool also never counts as a routing failure.

## Warnings

### WR-01: System-scope cleanup sets `cleaned = True` before doing anything, so an interrupted cleanup is never retried

**File:** `src/jabuka/soak/systemd.py:713-736`
**Issue:** `cleanup()` sets `self.cleaned = True` first, then removes the drop-ins, runs daemon-reload, unmounts, and finally restarts the production units. During `Harness.shutdown()`, `stop_all()` has already **stopped** jabuka-core and jabuka-ingest-fastnet. Suppose any exception lands after the flag is set and before the `restart` call is issued. Examples: a second Ctrl-C, or a SIGHUP from the SSH session dropping, which `_on_signal` turns into `SystemExit`. Two `umount` attempts with 30 s timeouts sit in that window. The atexit-registered `self.cleanup` then returns the cached empty report, and the production units stay stopped, or stay on the soak drop-ins, until someone runs `--systemd-cleanup` or reboots. The order is also inverted. Unmounting `data/logs` before restarting or stopping the units that hold files there forces the `umount -l` fallback whenever `stop_all` did not run (for example after a crash), which leaves a lazily detached loop or tmpfs still in use.
**Fix:** Mark completion per step and only at the end. Restart before unmounting, and re-raise after completing the critical steps:
```python
def cleanup(self) -> dict[str, Any]:
    if self.cleaned:
        return self.cleanup_report
    self._stop.set()
    ...
    removed = [...]                       # unlink drop-ins
    self._ctl("daemon-reload")
    self._ctl("restart", *[UNITS[r] for r in ("ingest", "core")], timeout=180.0)
    unmounted = [str(m) for m in self.mounts if unmount(m)]
    left = soak_lines_in(self._ctl("cat", UNITS["core"]).stdout)
    self.cleanup_report = {...}
    self.cleaned = True                   # only once everything ran
    return self.cleanup_report
```
Also consider blocking SIGHUP and SIGTERM (`signal.pthread_sigmask`) for the duration of `cleanup()`.

### WR-02: System scope on the Pi defaults to a RAM tmpfs for the logs. An OOM kill of the root harness leaves production on the soak config

**File:** `src/jabuka/tools/soak.py:495-519`, `src/jabuka/soak/scenarios/race-36h.json:13`
**Issue:** `race-36h` declares `"logs_fs": "tmpfs:256M"`. In `--systemd system`, `mount_logs_tmpfs()` passes that straight to `sd.mount_logs(..., "tmpfs")` in the **host** mount namespace. The whole run's logs live in RAM, and `disk_full` then fills the tmpfs completely with ballast, which pins about 256 MB of the Pi 3B's 1 GB. The units are protected (`OOMScoreAdjust=-500` and `-700`), while the root harness at score 0 (plus its tablet client and sampler) is a natural OOM victim. SIGKILL runs no `finally` and no atexit, so the drop-ins stay in `/run` and jabuka-core keeps running with `--clock sim`, the fake gpsd port, and the soak data dir until a reboot. The tmpfs also stays mounted and keeps holding its RAM. `docs/SOAK.md` tells the operator to pass `--logs-fs loop:512M`, but nothing enforces it, and a run that omits the flag gets the risky default.
**Fix:** In system scope, refuse `tmpfs` or map it to `loop`:
```python
if self.scope == "system" and mode == "tmpfs":
    raise SoakAbort("--systemd system: use --logs-fs loop:SIZE (a tmpfs pins RAM on the 1 GB Pi)")
```
Separately, protect the harness from the OOM killer the way the units are protected: write -900 to `/proc/self/oom_score_adj` at harness start, so the kernel kills something else first. As a belt-and-braces measure, have the core log loudly or alert when it starts with `--clock sim` under systemd (`INVOCATION_ID` set).

### WR-03: The Pi soak report certifies the checkout's git HEAD, not the code that ran

**File:** `src/jabuka/tools/soak.py:1009`, `scripts/freeze-check.sh:104-116`
**Issue:** In `--systemd system`, the units run `/opt/jabuka/venv/bin/jabuka-core` and `/opt/jabuka/venv/bin/jabuka-ingest-fastnet` from the installed wheel. The harness itself is run with `--python /opt/jabuka/venv/bin/python`. Yet `report["git"] = rep.git_info(self.repo)` records the HEAD and dirty state of `~/jabuka`, the checkout that happens to be the cwd. freeze-check F4 then prints "PASS sur <head>, code identique à HEAD". If the Pi's venv was installed from an older or different wheel (for example the checkout was pulled but `provision.sh` was not re-run), F4 certifies code that never ran in the soak.
**Fix:** Record the installed jabuka in the report. For example, add a sha256 over the files of the installed `jabuka` package (or the wheel's RECORD hash) under `report["installed"]`. Then have F4 (or F6, which already compares the wheel to `src/jabuka`) require that the installed hash equals the hash of the wheel built from HEAD. At minimum, in system scope compare `importlib.metadata.files("jabuka")` contents against `src/jabuka` at `git.head`, and set `git.dirty = True` (forcing F4 to FAIL) when they differ.

### WR-04: A corrupted main state file silently falls back to `.bak`, and schema-invalid mains never try `.bak`

**File:** `src/jabuka/nav/course.py:234-249`, `src/jabuka/nav/settings.py:124-136`, `src/jabuka/nav/settings.py:196-203`, `src/jabuka/common/atomicio.py:50-69`
**Issue:** `load_json_status` now reports `"bak"` when NAME is unreadable and NAME.bak loads, but every caller only acts on `"unreadable"`. `.bak` is the **previous** version. For `course.json` that can be the state before the last rounding or "activate" edit, so after an SD-card corruption plus a reboot the core silently routes to an already-rounded mark, with no alert. This contradicts the docstring's own rule ("never fall back silently"). There is also the reverse case. When NAME parses as JSON but fails `Course.model_validate` / `_valid` or `Settings.model_validate`, the stores jump straight to defaults (Course A, default settings) and never try a perfectly good `.bak`.
**Fix:** Surface the fallback, and let validation fall through to `.bak`:
```python
raw, source = load_json_status(self.path, None)
if source == "bak":
    self.alerts.append("Parcours restauré depuis la sauvegarde : vérifier la marque active")
```
Add matching FR, EN and SL keys to `i18n.js` `SRV_EXACT`. Also give `load_json_status` an optional `validate` callable so it moves on to `.bak` when the main file decodes but does not validate.

### WR-05: A recycled (wedged) router pool never counts as a failed cycle, so the route stays "ok" and not stale for up to 40 min

**File:** `src/jabuka/core/router_service.py:861-878`, `src/jabuka/core/router_service.py:913-919`
**Issue:** `_recycle_pool()` cancels every `_run` task, and a `_run` whose pool was replaced returns early (`if self.pool is not pool: return`). In both paths `_failed()` is never called. As a result:
- `_fail_streak` stays 0, so `block["stale"]` is never set and the `FAIL_WITHDRAW_N` / `ROUTE_FAIL_AGE_S` withdrawal (10 min) never triggers. Only the 40 min `ROUTE_STALE_S` age limit withdraws the route.
- The retry path (`_fail_streak > 0`) does not fire.
- `_missed_failed` is never set for a missed-tack reroute lost this way.

During a repeated wedge, the helm shows a normal green route between the 5-minute "ROUTEUR RELANCÉ" alerts. This is exactly the failure the CR-01 watchdog was added for.
**Fix:** Count the lost cycles as failures when recycling:
```python
def _recycle_pool(self, why: str) -> None:
    ...
    if self.last_request is not None and self._inflight > 0:
        self._failed(self.last_request, f"routeur relancé : {why}")
    for t in list(self._tasks):
        t.cancel()
```
Or record the request in `_run` and call `self._failed(req, ...)` on `CancelledError` when `self.pool is not pool`.

## Info

### IN-01: `RotatingAppendLog.dropped_bytes` is never surfaced, and lines lost at rotation are not counted

**File:** `src/jabuka/ingest/rawlog.py:83`, `src/jabuka/ingest/rawlog.py:149-175`
**Issue:** The new loss counter is not exported to Diag or health anywhere (no reference outside rawlog.py), so lost log data stays invisible on board. When `_close_file()` raises during rotation on a full disk, the incoming line in `_write()` is lost before it is appended, and `dropped_bytes` does not include it. While the disk stays full, every `_write` with `len(_pending) >= 8192` copies and retries the whole pending buffer (up to 4 MB). That costs CPU on the Pi 3B at bus rate.
**Fix:** Export `dropped_bytes` (and the raw, gps and derived equivalents) in the ingest and core health. Count the line lost on rotation failure. Rate-limit retries after a failed flush, for example to `flush_s`.

### IN-02: The system-scope soak dir is never removed and sits outside the retention policy

**File:** `src/jabuka/tools/soak.py:162`, `src/jabuka/tools/soak.py:1186-1188`
**Issue:** `/var/lib/jabuka/soak-<ts>/` holds the data, the race pack and `logs.img` (up to 1 GB once disk-full has filled it). It sits on the production data volume. Nothing deletes it, even after a PASS (only `run_dir/racepack` in the checkout is removed), and `retention` only manages `<data-dir>/logs`. Removal depends on a manual step in docs/SOAK.md §7.
**Fix:** On PASS (without `--keep`), remove `logs.img` and `racepack/` after unmounting, or print a prominent reminder in the verdict line.

### IN-03: Root runs a user-writable interpreter with the checkout on `sys.path`

**File:** `scripts/soak.sh:22`, `scripts/soak.sh:52`, `scripts/soak.sh:76`
**Issue:** Under `sudo`, the default `PY=.venv313/bin/python` is a user-owned venv, and `python -m` from the checkout cwd puts `~/jabuka` first on `sys.path`. Any module file dropped there, such as `json.py`, runs as root.
**Fix:** In system scope, require `--python` to be root-owned (for example `/opt/jabuka/venv/bin/python`) and run with `-I` or `-P` (`PYTHONSAFEPATH=1`).

### IN-04: `commissioning-rehearsal.sh --out` check is a string-prefix test only

**File:** `scripts/commissioning-rehearsal.sh:31-34`
**Issue:** `var/../../tmp/x` passes the `var/*` pattern and `rehearsal.main` resolves it anywhere. `soak.sh` already does the `realpath` containment check.
**Fix:** Reuse the `VAR_REAL` / `OUT_REAL` realpath check from `scripts/soak.sh:63-68`.

### IN-05: freeze-check aborts mid-report when the F6 helper fails

**File:** `scripts/freeze-check.sh:141-183`
**Issue:** With `set -e`, `f6="$("$PY" - ...)"` aborts the whole script if the Python helper raises. For example, when `deploy/requirements.lock` is missing, `lock.read_text` raises; and `git ls-files` with `check=True` can fail too. F7, F8 and F9 are then never printed, and the output ends in a traceback.
**Fix:** `f6="$("$PY" - ... || echo $'FAIL\thelper F6 en échec')"`, and guard `lock.exists()` in the helper.

### IN-06: Test hazards against the real host

**File:** `tests/soak/test_soak_systemd.py:282-289`, `tests/soak/test_soak_systemd.py:334-355`
**Issue:**
- `test_systemd_cleanup_alone_removes_stale_dropins` calls `cleanup_system()` with the default `proc_mounts=/proc/mounts` and an unfaked `umount`. Run as root on a host with a live `/var/lib/jabuka/soak-*` mount, it really unmounts it.
- `test_user_scope_transient_unit_copies_the_shipped_policy` calls `b.start()`, which registers an atexit cleanup, and never calls `cleanup()`. At interpreter exit, after monkeypatch has restored `PATH`, the real `systemctl --user stop/reset-failed` runs.

**Fix:** Pass `proc_mounts=tmp_path / "mounts"` and fake `umount` in `fake_bin`. Call `b.cleanup()` (or `atexit.unregister`) at the end of the user-scope test.

### IN-07: Pack-changed alert latches forever, and the clock-step-back retry is duplicated

**File:** `src/jabuka/core/router_service.py:815-817`, `src/jabuka/core/router_service.py:586-589`
**Issue:** `_pack_changed` is never cleared when the on-disk pack returns to the loaded fingerprint (for example a copy that was reverted), so "PACK DE COURSE MODIFIÉ" stays until restart. The `now < _last_req_t - CLOCK_BACK_TOL_S` retry in `_maybe_request` duplicates the forced `"clock"` trigger that `Triggers.check` (advice.py:488-491) already emits.
**Fix:** Set `self._pack_changed = fp != self.pack_fp` (unless a worker FAIL_PACK set it). Drop the duplicate retry condition, or comment why both are needed.

### IN-08: The root-level systemd soak tool ships in the race wheel

**File:** `pyproject.toml:60`
**Issue:** `jabuka-soak` (which rewrites `/run/systemd/system` drop-ins and restarts the production units as root) is installed as `/opt/jabuka/venv/bin/jabuka-soak` on the race Pi. Running it by mistake on race day restarts the production units under the soak config, `--clock sim` included.
**Fix:** Keep the console script for the dev venv only (an extras or dev entry point). Or add a race-window guard that refuses `--systemd system` when `settings.race_start_local` is less than 24 h away.

### IN-09: The disk-full ballast is created as root without `O_NOFOLLOW` in a directory owned by the service user

**File:** `src/jabuka/soak/faults.py:799-806`
**Issue:** `inside()` resolves `logs/ballast.bin`, then `os.open(ballast, O_WRONLY|O_CREAT|O_TRUNC)` runs as root. The directory belongs to `jabuka`, and the network-facing core runs as that user, so a compromised core could swap in a symlink between the check and the open (TOCTOU), and root would then truncate the symlink's target.
**Fix:** `os.open(ballast, os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW, 0o644)`, or open it relative to a directory fd with `dir_fd=`.

---

_Reviewed: 2026-11-07T14:19:03Z_
_Reviewer: Claude (gsd-code-reviewer)_
_Depth: standard_

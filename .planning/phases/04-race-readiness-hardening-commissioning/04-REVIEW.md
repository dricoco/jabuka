---
phase: 04-race-readiness-hardening-commissioning
reviewed: 2026-11-07T23:38:30Z
depth: standard
scope: incremental (424671c..HEAD, gap-closure plans 04-04 and 04-05)
files_reviewed: 20
files_reviewed_list:
  - deploy/PI-SETUP.md
  - docs/FREEZE.md
  - docs/I18N-SL-REVIEW.md
  - docs/SOAK.md
  - docs/SPARE-SD.md
  - scripts/freeze-check.sh
  - src/jabuka/common/atomicio.py
  - src/jabuka/core/router_service.py
  - src/jabuka/nav/course.py
  - src/jabuka/nav/settings.py
  - src/jabuka/soak/report.py
  - src/jabuka/soak/systemd.py
  - src/jabuka/tools/soak.py
  - src/jabuka/web/static/i18n.js
  - tests/commissioning/test_freeze_check.py
  - tests/nav/test_state_corruption.py
  - tests/routing/test_supervisor.py
  - tests/soak/test_soak_identity.py
  - tests/soak/test_soak_probes.py
  - tests/soak/test_soak_systemd.py
findings:
  critical: 1
  warning: 4
  info: 6
  total: 11
status: issues_found
---

# Phase 4: Code Review Report (incremental, 04-04 + 04-05)

**Reviewed:** 2026-11-07T23:38:30Z
**Depth:** standard (diff 424671c..HEAD plus the surrounding code)
**Files Reviewed:** 20
**Status:** issues_found

## Narrative Findings (AI reviewer)

## Summary

This review covers the two gap-closure plans:

- **04-04:** the soak code-identity fingerprint, the F3/F4 fingerprint rule in freeze-check, refusing to start without an identity, refusing tmpfs in system scope, OOM protection for the harness, and the reordered, retryable system-scope cleanup with signal deferral.
- **04-05:** "restauré" alerts on a `.bak` restore, schema-invalid main files falling through to `.bak`, and a recycled router pool counted as a failed cycle.

The race-path changes are sound. When `course.json`, `settings.json` or `wind_manual.json` is valid, it loads exactly as before with no alert, because the validate hook only runs on candidates that decode. The new French server strings match the FR, EN and SL `SRV_EXACT` keys byte for byte, with no NBSP drift. WR-05 is counted once per recycle, with the correct `"routeur relancé : …"` reason, and nothing is counted twice when the cancelled `_run` unwinds.

The issues are in the freeze gate and the soak harness:

- **F4 can still PASS a Pi report that never fingerprinted the installed units** (CR-01). I reproduced this against the real `scripts/freeze-check.sh` using the test fixture.
- A failed `systemctl restart` during cleanup is silently accepted, and the run counts as done (WR-01).
- A signal deferred during cleanup is re-raised before `report.json` is written, so the 2–4 h Pi soak evidence is lost (WR-02).
- The new "restauré" alerts are red badges that cannot be cleared (WR-03).
- The fingerprint PASS path is narrower than the git rule it replaces (WR-04).

## Prior findings (424671c 04-REVIEW)

| ID | Status | Notes |
|---|---|---|
| WR-01 (cleanup marked done first, wrong order) | **resolved** | `cleaned` is set only after `_cleanup_system` returns. The order is now restart, then unmount. SIGINT, SIGTERM and SIGHUP are deferred. Residual defects: a failed restart is still accepted as done (WR-01 below), and the re-raised deferred signal loses the report (WR-02 below). |
| WR-02 (RAM tmpfs in system scope, OOM kill skips cleanup) | **resolved** | tmpfs (explicit, scenario default or `auto`) is refused in `main()` before the root check and again in `prepare_system`. The harness sets `oom_score_adj=-900`. The optional "core alerts when started with `--clock sim` under systemd" belt-and-braces was not implemented. A side effect of the OOM change is IN-02. |
| WR-03 (report certifies the checkout HEAD, not the installed code) | **partially** | System scope now fingerprints the units' own venv plus both unit files, and refuses to start without them. But freeze-check F4 still accepts aarch64 reports with `code.source = "children"` or no `code` block at all, through the legacy git rule (CR-01). |
| WR-04 (silent `.bak` fallback; schema-invalid main never tries `.bak`) | **resolved** | `load_json_status(validate=…)` falls through to `.bak`. All three stores announce `bak` and `unreadable`, and i18n is complete. Residual: the alerts can never be cleared (WR-03 below), and a later write moves the corrupt main into `.bak` (IN-01). |
| WR-05 (recycled pool never counts as failed) | **resolved** | `_recycle_pool` calls `_failed(last_request, …)` when `_inflight > 0`. Stale, retry, withdrawal after 10 min, and `_missed_failed` are all covered by new tests. Residual: the forced flag of the lost cycle is not carried over (IN-05). |

## Critical Issues

### CR-01: F4 passes a Pi report that has no unit fingerprint (shim or user scope) or no `code` block at all, which is fail-open

**File:** `scripts/freeze-check.sh:121-143`, `scripts/freeze-check.sh:180-191`
**Issue:** `code_state()` checks `code.units` only when `code.source == "units"`. Any other source, such as `"children"` from a shim-mode or `--systemd user` run on the Pi, returns `match` once `code.sha256` equals the HEAD fingerprint. Line 180 then prints `PASS … paquet installé = src/jabuka à HEAD` whenever `head` is `-`, which is exactly the no-`.git` Pi copy that PI-SETUP §3 now prescribes. freeze-check never looks at `mode` or `code.source` for F4.

I confirmed this against the real script using the `Frozen` fixture. An aarch64 race-36h report with `code = code_identity(pkg, source="children")`, `git.head = null` and `mode = "shim"` gives `[PASS] F4 Pi : … PASS, paquet installé = src/jabuka à HEAD`. The same holds when the report's `units` would mismatch, because they are never read.

Concretely, an operator who runs `bash scripts/soak.sh --python /opt/jabuka/venv/bin/python` on the Pi and forgets `sudo … --systemd system` gets a green F4. That run never exercised the installed units, their hardening, WatchdogSec or Restart=, and never hashed the unit files. This contradicts FREEZE.md ("mode `--systemd`") and the 04-04 goal that a missing fingerprint must never PASS.

Separately, a report with no `code` block (`cstate=absent`) still falls back to the legacy git rule (lines 182-191) for both F3 and F4. After 04-04, every new report carries `code`, and system scope refuses to run without it. An absent block therefore means either the identity failed (`identity_messages` lets shim and user scope continue with `code none`) or a stale pre-04-04 harness was used. Neither should certify.
**Fix:** Make the fingerprint mandatory, and for F4 require the systemd-system source:
```python
# in the helper, after loading r:
code = r.get("code")
state, detail = code_state(code)
if machine == "aarch64" and state == "match":
    if r.get("mode") != "systemd" or (code or {}).get("source") != "units":
        state, detail = "not-units", f"mode {r.get('mode')}, source {(code or {}).get('source')}"
```
```bash
elif [ "$cstate" = absent ]; then
    say FAIL "$id" "$label : $path sans empreinte code.sha256 : refaire le soak avec le banc 04-04"
elif [ "$cstate" = not-units ]; then
    say FAIL "$id" "$label : $path pas un soak --systemd system ($detail) : sudo bash scripts/soak.sh --systemd system …"
```
Add tests: an aarch64 report with `source="children"` must FAIL F4, and an x86_64 or aarch64 report with no `code` must FAIL. Note that `test_f4_non_git_report_without_code_still_fails` only passes today because `head` is null there.

## Warnings

### WR-01: A failed or interrupted `systemctl restart` in cleanup is accepted as done, so the production units can stay stopped with no retry, no FAIL and exit 0

**File:** `src/jabuka/soak/systemd.py:270-275`, `src/jabuka/soak/systemd.py:777-794`, `src/jabuka/tools/soak.py:785-793`, `src/jabuka/tools/soak.py:1329-1333`
**Issue:** `_ctl` never raises. `OSError` and `SubprocessError`, including `TimeoutExpired` after 180 s, become `CompletedProcess(rc=1)`. `_cleanup_system` therefore always reaches the end, and `cleanup()` sets `cleaned = True` even when `restart` returned non-zero. By then `Harness.shutdown()` → `stop_all()` has already run `systemctl stop jabuka-ingest-fastnet jabuka-core`. A failed restart leaves the production units stopped or failed, and:

- `cleanup()` is idempotent from then on, so the atexit call does not retry.
- `Harness.run()` only turns `soak_lines_left` into a FAIL. `restarted: False` does not affect the verdict.
- `--systemd-cleanup` (`cleanup_system`) returns `soak_lines_left`, so `main()` exits 0 after a failed restart.
- The only trace is `(rc N)` buried in a stdout line, which may go to a dead `tee` after an SSH drop.

A terminal Ctrl-C during cleanup also reaches the `systemctl restart` child, because it shares the foreground process group. That kills the client, reports `restarted: False`, and lets the unmount run while the restart job is still queued. The "interrupted cleanup is redone" guarantee in the docstring and in docs/SOAK.md only covers Python exceptions, not this failure mode, which is the one that matters ("production units must never stay stopped").
**Fix:** Verify the outcome rather than trusting the rc, and keep the cleanup retryable until the units are actually up:
```python
r = self._ctl("restart", *units, timeout=180.0)
active = self._ctl("is-active", *units).stdout.split()
ok = r.returncode == 0 and active == ["active"] * len(units)
...
if not ok:
    raise CleanupIncomplete(f"production units not active after restart: {active} (rc {r.returncode})")
```
Leave `cleaned` False when the restart fails, so atexit retries. Make `Harness.run()` add a `fail_reasons` entry (FAIL) when `cleanup["restarted"]` is not True. Have `--systemd-cleanup` return 1 when the units are not active. Start `systemctl` children with `start_new_session=True` (or `preexec_fn=os.setpgrp`) so a terminal Ctrl-C cannot kill them mid-restart.

### WR-02: A signal deferred during cleanup is re-raised inside `Harness.run()`, before `report.json` is written, so the soak report is lost

**File:** `src/jabuka/soak/systemd.py:740-745`, `src/jabuka/tools/soak.py:782-785`, `src/jabuka/tools/soak.py:1305-1309`
**Issue:** `_deferred_signals` re-raises the first held signal with `signal.raise_signal()` as soon as the cleanup block ends. The first and normal call site is the `finally:` at `soak.py:785`, which sits after `build_report()` but inside `h.run()`. The re-raised SIGINT, SIGTERM or SIGHUP becomes `KeyboardInterrupt` or `SystemExit(128+n)` via `_on_signal`. That exception propagates out of `run()`, `run_soak` skips `rep.write_report(run_dir, report)` and `_give_back`, and the fully built report is discarded.

So a Ctrl-C, or an SSH drop (SIGHUP, which `main()` hooks unconditionally even under `nohup`), during the minutes-long cleanup at the end of a 2–4 h Pi soak leaves no `report.json`. F4 then has nothing to read, and the soak must be redone a few days before the race. The test `test_signal_during_system_cleanup_is_deferred_until_the_units_restart` asserts this `SystemExit` escapes `cleanup()`, so the behaviour is by design but untested end to end.

Also, when the block exits with an exception (`done` False), the recorded signal is silently dropped.
**Fix:** Do not re-raise inside `cleanup()`. Record the pending signal on the backend, for example `self.pending_signal = got[0]`. Let `run_soak` write the report first, then honour it:
```python
jpath, mpath = rep.write_report(run_dir, report)
_give_back(run_dir)
...
sig = getattr(h.sup, "pending_signal", None)
if sig is not None:
    return 128 + sig
```
Alternatively, extend the deferral window in `run()` to cover `build_report()`, `cleanup()` and `write_report()`.

### WR-03: The new "restauré" alerts, like the "illisible" ones, are permanent red badges that the crew can never clear

**File:** `src/jabuka/nav/course.py:250-253`, `src/jabuka/nav/settings.py:139-142`, `src/jabuka/nav/settings.py:211-214`, `src/jabuka/core/nav_service.py:135-139`, `src/jabuka/web/static/helm.js:172-174`
**Issue:** The stores append the alerts once in `__init__`, and nothing ever removes them. `_commit` and `_clear_write_alert` only touch `WRITE_ALERT`, and the settings and manual-wind stores never touch `alerts`. `nav_service` sends them in every 1 Hz nav message, and `helm.js` renders each one as a red top-bar badge on every tab.

After a `.bak` restore, the alert tells the crew to "vérifier la marque active" or "vérifier les réglages". Once they have checked and re-confirmed (activate, select, or a settings PUT), the badge still stays for the rest of the race, up to 36 h, until jabuka-core restarts. A permanently lit red badge trains the helm to ignore red badges, which defeats the alert channel that CR-01 (phase 3) set up for real faults. The `.bak` restore is now a more common path, because schema-invalid mains fall through to it, so this matters more than before.
**Fix:** Clear the store's load alert on the first successful user write, which acknowledges the state:
```python
LOAD_ALERTS = {COURSE_FROM_BAK, COURSE_UNREADABLE}
def _commit(...):
    ...
    self._write(course, version)
    self._clear_write_alert()
    if event is not None and event.get("type") != "rounding":   # a user edit, not the FSM
        self.alerts[:] = [a for a in self.alerts if a not in LOAD_ALERTS]
```
Do the same in `SettingsStore.update` and in `ManualWindStore.set` and `clear`. An alternative is an explicit "acknowledge" (OK) API.

### WR-04: The fingerprint PASS path (no `.git` on the Pi) drops the `deploy/**` and `pyproject.toml` coverage of the git rule

**File:** `scripts/freeze-check.sh:180-181` versus `scripts/freeze-check.sh:188-189`, `docs/FREEZE.md:43-46`
**Issue:** With `git.head = null`, `cstate=match` PASSes after comparing only `src/jabuka` and the two jabuka unit files. The git rule it replaces for the Pi failed on *any* change under `src/`, `deploy/` (except `*.md`) or `pyproject.toml` between the soak and HEAD.

The following therefore no longer invalidate F4 once the Pi copy has no `.git`, which is now the documented default:

- a post-soak change to `deploy/systemd/fastnet2ip.service` or `jabuka-fastnet-relay.service` (the ingest chain and Plan B),
- `watchdog.conf` and `journald-jabuka.conf`,
- `deploy/provision.sh` (NM AP, gpsd and chrony config, udev),
- `pyproject.toml` (entry points the units' `ExecStart` depends on).

The script header (lines 6-12) and FREEZE.md describe the fingerprint as an *additional* constraint, but in practice it replaces the stronger one.
**Fix:** In system scope, also record a fingerprint of the deploy tree the Pi was provisioned from (`FINGERPRINT_SH` over `~/jabuka/deploy` minus `*.md`) and of `pyproject.toml`. F4 then compares both with `git archive HEAD deploy pyproject.toml`. A cheaper option is to hash the installed copies of every file provision.sh installs, and compare them with HEAD.

## Info

### IN-01: After a `.bak` restore, the first write moves the corrupt main into `.bak`

**File:** `src/jabuka/common/atomicio.py:35-41`, `src/jabuka/nav/course.py:247-251`
**Issue:** The restore leaves the corrupt `course.json` on disk. The next `atomic_write_bytes` hard-links that corrupt main to `course.json.bak`, which replaces the only good copy. A power cut between the two `os.replace` calls then leaves both files bad, and the next boot falls back to Course A with "illisible".
**Fix:** When `source == "bak"`, immediately rewrite the main from the restored value (or `os.replace(bak, main)` after an fsync copy), so the corrupt bytes never become the backup.

### IN-02: `oom_score_adj=-900` is inherited by the harness children, so a real OOM now prefers the production units

**File:** `src/jabuka/tools/soak.py:496-497`, `src/jabuka/soak/systemd.py:809-817`
**Issue:** The synth, the fake gpsd and logcheck are spawned after `protect_from_oom()`, so they run at -900. jabuka-core (-500) and ingest (-700) become preferred OOM victims over the test scaffolding. A leaking synth or logcheck would then show up as a core kill and a false recovery fault.
**Fix:** Reset children to 0. One option is `preexec_fn=lambda: Path("/proc/self/oom_score_adj").write_text("0")` (lowering protection needs no privilege). Another is to protect only the harness PID after the children start.

### IN-03: The soak persistence check does not require the new "restauré" alert

**File:** `src/jabuka/soak/faults.py:434-445`
**Issue:** The `"from .bak"` branches accept a `.bak` value without checking that the `*FromBak` alert is present in `/api/nav` alerts. If the WR-04 announcement regressed, the race-36h soak would still PASS.
**Fix:** In the `.bak` branches, also require `ALERT_*_FROM_BAK in alerts`.

### IN-04: In shim and user scope, the fingerprint locator ignores the environment the children actually run with

**File:** `src/jabuka/soak/report.py:272-287`, `src/jabuka/soak/supervisor.py:224`
**Issue:** `locate_package` runs `python -I`, which ignores `PYTHONPATH` and the cwd. The children inherit `os.environ` and the cwd (`python -m jabuka.…`). With `PYTHONPATH` exported, the children can import a different `jabuka` from the one fingerprinted.
**Fix:** Run the locator with the same env and cwd as the children (without `-I`), or strip `PYTHON*` variables from the children's environment.

### IN-05: The forced flag of a cycle lost to a recycled pool is not carried over to the retry

**File:** `src/jabuka/core/router_service.py:868-871`, `src/jabuka/core/router_service.py:943`
**Issue:** `superseded` outcomes carry `forced` through `_force_carry`, but `_recycle_pool` drops it. The retry is `Trigger("retry", False)`, so a lost forced cycle (for example "manuel") can be rejected by the replacement hysteresis.
**Fix:** In `_recycle_pool`, set `self._force_carry = True` when the lost request was forced (record `forced` in `_submit`).

### IN-06: Prior IN-06 is still open: `cleanup_system` test uses the real `/proc/mounts` and `umount`

**File:** `tests/soak/test_soak_systemd.py:283-290`
**Issue:** The new tests fake `unmount`, but `test_systemd_cleanup_alone_removes_stale_dropins` still calls `cleanup_system()` with the default `proc_mounts`. Run as root on a host with a live soak mount, it unmounts that mount for real.
**Fix:** Pass `proc_mounts=tmp_path / "mounts"` and apply `_fake_unmount`.

---

_Reviewed: 2026-11-07T23:38:30Z_
_Reviewer: Claude (gsd-code-reviewer)_
_Depth: standard_

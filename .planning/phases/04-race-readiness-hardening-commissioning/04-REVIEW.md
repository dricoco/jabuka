---
phase: 04-race-readiness-hardening-commissioning
reviewed: 2026-11-08T19:14:34Z
depth: standard
scope: incremental (ee6f427..HEAD, gap-closure plan 04-07)
files_reviewed: 10
files_reviewed_list:
  - docs/FREEZE.md
  - docs/SOAK.md
  - scripts/freeze-check.sh
  - src/jabuka/soak/report.py
  - src/jabuka/soak/scenario.py
  - src/jabuka/soak/systemd.py
  - src/jabuka/tools/soak.py
  - tests/commissioning/test_freeze_check.py
  - tests/soak/test_soak_identity.py
  - tests/soak/test_soak_systemd.py
findings:
  critical: 1
  warning: 0
  info: 3
  total: 4
status: issues_found
---

# Phase 4: Code Review Report (incremental, 04-07)

**Reviewed:** 2026-11-08T19:14:34Z
**Depth:** standard (diff ee6f427..HEAD plus the surrounding code)
**Files Reviewed:** 10
**Status:** issues_found

## Narrative Findings (AI reviewer)

## Summary

Plan 04-07 closes all three prior findings it targeted:

- **Prior CR-01:** F3 and F4 now require `scenario_sha256` to equal the sha256 of `race-36h.json` at HEAD, the HEAD seed, `duration_s >= 129600`, `sim_s >= 0.99 x` that, and no fault skipped "after the end of the run". Each check fails closed.
- **Prior WR-01:** F3 now FAILs a report with no `git.head`.
- **Prior WR-02:** SIGINT, SIGTERM and SIGHUP are held from the end of the main run until `report.json` has been written.

The 91 in-scope tests pass (`.venv313`).

I traced the genuine full-length paths and found no false FAIL in them. The laptop path is shim plus userns re-exec. The Pi path is `--systemd system` from the installed wheel with no `.git`, at `--speed 20`. In detail:

- The compiled race-36h timeline ends at 115200 s and has no draw past 129600, so a full run never gets a late skip.
- `sim_now()` can only reach or pass `duration` when `wait_sim` returns.
- The wheel ships `scenarios/race-36h.json` byte-identical to the source; F6 enforces that.
- On the Pi, `python -m` from the copied checkout resolves `jabuka` from the venv.

I found no new false-PASS path in freeze-check itself.

The new end-of-run signal hold does introduce a **false PASS of the soak verdict itself** (CR-01, reproduced). A Ctrl-C or SIGHUP at the end of a `--systemd system` run still kills the `journalctl` child, which shares the harness's process group. The harness, which now survives that signal, then builds the tracebacks check from a truncated or empty journal. Before 04-07 the same signal lost the report, which is fail-safe. Now it can certify PASS without the evidence.

Nothing in this plan touches the race path. The diff is limited to soak, tools, scripts, docs and tests.

## Prior findings (ee6f427 04-REVIEW)

| ID | Status | Notes |
|---|---|---|
| CR-01 (shortened or custom race-36h run PASSes F3/F4) | **resolved** | Covered by `run_state()` (freeze-check.sh:179-195): sha, seed, duration, sim_s and late skips are checked, and a missing key fails closed. The harness records `scenario_sha256` and `duration_s`, warns at start, and `report.md` marks "Essai raccourci". `SKIP_AFTER_END` parity is tested. The newest-report rule still applies, so a later short run in `var/soak/` masks a valid one. That is now a loud FAIL with instructions, not a false PASS (see IN-01). |
| WR-01 (F3 fingerprint-only shortcut when `git.head` is null) | **resolved** | The shortcut now requires `machine = aarch64` (line 258). Any other head-less report hits `git.head inconnu` FAIL (line 260). The header and FREEZE.md are updated, and a test covers it. With the git rule mandatory for F3, the compensating control that the deferred WR-04 relied on holds again for the laptop soak. |
| WR-02 (signal outside the cleanup loses report.json) | **resolved for report loss, but introduces CR-01 below** | `Harness.end_signals` (a `SignalHold`) is started after the main run and released in `run_soak`'s `finally` after `write_report` and `_give_back`. The nested cleanup hold restores `end_signals._record`, so neither hold loses a signal. A test covers the real `Harness.run` end path. |
| IN-01 (stale "second Ctrl-C" wording) | **resolved** | The `cleanup()` docstring and SOAK.md step 8 now describe the uninterruptible end and the `kill -9` plus `--systemd-cleanup` escape. |
| IN-02 (deferred-signal path not tested end to end) | **resolved (mostly)** | `test_signal_at_the_end_of_the_run_is_held_until_the_report_is_written` drives the real `Harness.run` end path (shim scope). The system-scope cleanup inside it is still only unit-tested. The outer hold now covers it anyway. |
| IN-03 (F4 identifies the Pi only by `host.machine == aarch64`) | open | Not addressed in 04-07. |
| WR-03, WR-04, IN-04, IN-05 (older, deferred) | open (deferred) | Not re-reviewed. WR-04 is mitigated again by the F3 git rule, as above. |

## Critical Issues

### CR-01: A Ctrl-C or SIGHUP at the end of a Pi soak truncates the journal dump, and the soak can then report PASS with no traceback evidence

**File:**
- `src/jabuka/soak/systemd.py:730-771` (`dump_journal`: `subprocess.run(cmd, capture_output=True, timeout=120)`, no `start_new_session`, return code ignored, `TimeoutExpired` → `out = ""`)
- `src/jabuka/tools/soak.py:795-799` (hold started, then `shutdown()` → `dump_journal`)
- `src/jabuka/tools/soak.py:953-969` (tracebacks check)

**Issue:** In system scope, the only process-output evidence the tracebacks check scans is `proc/<role>-journal.log`, written by `dump_journal`, plus `synth.log`. `journalctl` is spawned in the harness's own process group. `_ctl` uses `start_new_session=True`; `dump_journal` does not.

A terminal Ctrl-C therefore reaches `journalctl`, and the default action kills it. The same goes for SIGHUP when the SSH session drops (the sudo `use_pty` pty forwards ^C to the whole foreground group).

- **Before 04-07:** the harness also died, so no report was written. That is safe: the operator had to redo the soak.
- **Now:** `end_signals` holds the signal in the harness, so only `journalctl` dies. `subprocess.run` returns the partial stdout with rc -2. `dump_journal` ignores the rc and writes the truncated log. `scan_tracebacks` sees fewer or no blocks, `c["tracebacks"]` is `ok: True`, and the verdict can be PASS.

The report and exit code (128 + n) show that a signal was received, but nothing ties that signal to a degraded tracebacks check. F4 reads only `verdict`, so it will certify that run.

The same silent-empty path exists on `TimeoutExpired`: a journalctl run of more than 120 s gives `out = ""` and zero tracebacks. That timeout is plausible on a Pi 3B dumping 2–4 h of JSON journal for two units with dozens of restarts.

**Reproduced** with the real `SystemdBackend.dump_journal` under `SignalHold`, in a scratch dir via `setsid`, using a fake journalctl. The fake prints one line, sleeps 3 s, then prints a `Traceback` / `RuntimeError` pair. `os.killpg(getpgrp(), SIGINT)` was sent at 1 s. Result:

- held signal: `2`
- `core-journal.log` = `'1.000 started\n'`: the traceback lines are lost
- the harness carried on normally

**Fix:** Isolate the child, and make a failed dump block a PASS:

```python
# systemd.py dump_journal
self.journal_error = None
try:
    r = subprocess.run(cmd, capture_output=True, timeout=300, start_new_session=True)
    out = r.stdout.decode("utf-8", "replace")
    if r.returncode != 0:
        self.journal_error = f"journalctl rc {r.returncode}: {r.stderr.decode(errors='replace')[:200]}"
except (OSError, subprocess.SubprocessError) as exc:
    out, self.journal_error = "", repr(exc)
```

```python
# soak.py compute_checks, after classify_tracebacks
jerr = getattr(self.sup, "journal_error", None)
c["tracebacks"] = rep.check(
    False if jerr else not unexp, len(unexp), 0,
    (f"journal dump incomplete ({jerr}); " if jerr else "") + detail)
```

Also pass `start_new_session=True` to the other end-of-run children that share the group: `unmount()` in systemd.py:902 (its `umount -l` retry hides it today), and the `vcgencmd` probe in probes.py:102. Add a test that sends SIGINT to the process group during a fake journalctl in `dump_journal`. It should expect the full output, or a non-PASS tracebacks check.

## Info

### IN-01: A short run masks an older valid full soak, and the FAIL text sends the operator to redo it

**File:** `scripts/freeze-check.sh:198-209`, `scripts/freeze-check.sh:248-249`

**Issue:** The newest race-36h report of each machine is the only one judged, by run-dir name. A short run left in `var/soak/` yields "essai raccourci … le refaire sans --duration", even when an older full PASS run on the same code sits next to it. Three days before the race, that can cost a needless 2 h Pi re-soak.

Run-dir names come from the Pi clock. The Pi has no RTC, and gpsd may have no fix on the bench. If that clock goes backwards between runs, a different report than the latest one is judged.

**Fix:** Add to the short and not-scenario messages: "si un soak complet plus ancien existe, déplacer `<path>` vers var/soak-essais/ et relancer freeze-check". Optionally order by `t0_wall` or `started_utc` rather than by dir name, and print it.

### IN-02: The end-of-run hold gives no feedback, and the SOAK.md kill -9 threshold is close to the worst case

**File:** `src/jabuka/soak/systemd.py:69-71` (`SignalHold._record`), `docs/SOAK.md` step 8

**Issue:** A held Ctrl-C prints nothing. `tee` in `scripts/soak.sh` also dies on the same Ctrl-C, so later lines are not shown either. Step 8 says to `kill -9` after "~10 min sans nouvelle ligne", but the bounded worst case is close to that: stop 60 s + journal 120 s + logcheck + daemon-reload 60 s + restart 180 s + verify 20 s + umount 60 s per mount + cat 60 s. A `kill -9` also skips atexit and loses the report.

**Fix:** On the first held signal, write one line with `os.write(2, b"jabuka-soak: signal held, finishing report.json (up to ~12 min)\n")`. `os.write` is async-signal-safe, unlike `print`. Raise the SOAK.md threshold to about 15 min.

### IN-03: The userns parent still waits only 30 s after `terminate()` and then exits while the child is still finishing

**File:** `src/jabuka/tools/soak.py:1499-1503`

**Issue:** On the laptop, the soak re-execs into a user namespace. On Ctrl-C at the end of the run, the parent sends SIGTERM to the child, which now holds it. The parent then waits 30 s and re-raises. If the child's end of run takes longer, the shell prompt returns while an orphaned child is still writing `report.json`, and its final messages go to a dead pipe. On a laptop this is normally under 30 s (`STOP_TIMEOUT_S = 5`), hence Info.

**Fix:** After `terminate()`, wait for as long as the child's end of run can take (for example 600 s). Or print "le rapport s'écrit encore dans <run_dir>" before re-raising.

---

_Reviewed: 2026-11-08T19:14:34Z_
_Reviewer: Claude (gsd-code-reviewer)_
_Depth: standard_

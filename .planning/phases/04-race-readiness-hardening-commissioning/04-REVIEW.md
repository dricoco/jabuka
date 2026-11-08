---
phase: 04-race-readiness-hardening-commissioning
reviewed: 2026-11-08T20:27:39Z
depth: standard
scope: incremental (0c12a90..HEAD 1e86482, gap-closure plan 04-08)
files_reviewed: 11
files_reviewed_list:
  - docs/FREEZE.md
  - docs/SOAK.md
  - scripts/freeze-check.sh
  - scripts/soak.sh
  - src/jabuka/soak/probes.py
  - src/jabuka/soak/report.py
  - src/jabuka/soak/systemd.py
  - src/jabuka/tools/soak.py
  - tests/commissioning/test_freeze_check.py
  - tests/soak/test_soak_identity.py
  - tests/soak/test_soak_systemd.py
findings:
  critical: 0
  warning: 1
  info: 4
  total: 5
status: issues_found
---

# Phase 4: Code Review Report (incremental, 04-08)

**Reviewed:** 2026-11-08T20:27:39Z
**Depth:** standard (diff 0c12a90..HEAD plus the surrounding code)
**Files Reviewed:** 11
**Status:** issues_found

## Narrative Findings (AI reviewer)

## Summary

Plan 04-08 closes the prior CR-01. The fix works in three layers:

- `journalctl`, `umount` and `vcgencmd` now run with `start_new_session=True`. A terminal Ctrl-C or an SSH SIGHUP can no longer cut the journal copy.
- A non-zero rc, a timeout (now 300 s, with partial stdout kept), an exception, or a system-scope unit with zero entries sets `systemd.journal.complete = false`. The `tracebacks` check is then FAIL, so the verdict is FAIL.
- Any signal held at the end of the run is recorded as `end_signal`. freeze-check F3/F4 refuse a non-null or absent `end_signal`, and refuse a systemd-mode report whose `systemd.journal.complete` is not `true`.

The 104 in-scope tests pass (`.venv313`, 36 s).

I traced the genuine full-length paths and found no false FAIL, no end-of-run hang and no deterministic false PASS:

- **Laptop F3 (shim, userns re-exec):** `journal_problem()` returns None for the shim backend, and `end_signal` stays null unless a signal is actually received.
- **Pi F4 (`--systemd system --speed 20`, installed wheel, no `.git`):**
  - **Zero-entry rule:** PID 1 always logs `Started` / `Stopping` / `Stopped` with `UNIT=<unit>` after `--since @t0-1`, and `dump_journal` matches the `UNIT` field. Both the core and ingest roles therefore get at least one entry.
  - **Exit code when nothing matches:** on systemd 260, `journalctl` exits 0 with no output when nothing matches (checked for both `-u` and `--user -u`), so an empty match does not become a spurious rc error.
  - **Journal volume:** the units' journal is small. Existing copies have 79 lines for the ci scenario, so 300 s is ample on a Pi 3B.
  - **End-of-run time budget:** the worst case is about 13 min (stop 60 + journal 300 + daemon-reload 60 + restart 180 + verify 20 + umount 60 + cat 60, plus joins). That is within the "~15 min" printed by the held-signal line and stated in SOAK.md step 8.
- **`soak.sh` with `tee -i`:** bash keeps going after a held Ctrl-C because the harness exits normally with 130, not by signal. RC, REPORT and VERDICT are still parsed.

Nothing in this plan touches the race path. The diff is limited to soak, tools, scripts, docs and tests.

The remaining findings are fail-open corners of the new "journal copy is never silent" guarantee:

- **WR-01:** a `--systemd user` copy with zero entries is accepted.
- **IN-01:** a journal thinned by journald itself is accepted as complete.
- **IN-02 to IN-04:** wording and UX issues, plus one test that can become vacuous.

## Prior findings (0c12a90 04-REVIEW, plan 04-07 review)

| ID | Status | Notes |
|---|---|---|
| CR-01 (held Ctrl-C/SIGHUP kills `journalctl` → truncated journal → false PASS) | **resolved** | `dump_journal` (systemd.py:770-825) runs journalctl in its own session. The rc, timeout and exception paths are recorded and never silent. `journal_problem()` (soak.py:1209) FAILs `tracebacks` (soak.py:968-976). `end_signal` is written (soak.py:1413-1416), and freeze-check `end_state()` (freeze-check.sh:203-217) refuses interrupted runs and incomplete journals. `unmount()` and `pi_probe` were also moved to their own sessions.<br><br>**Reproduced:** the real `dump_journal` under `SignalHold` with a process-group SIGINT keeps the whole journal. The new test `test_group_sigint_during_the_journal_copy_keeps_the_whole_journal` makes this permanent.<br><br>**Residual fail-open corners:** WR-01 and IN-01 below. |
| IN-01 (short run masks an older full soak; dir-name ordering) | **resolved (message)** | The not-scenario and short FAIL texts now tell the operator to move the newer run to `var/soak-essais/`. Ordering is still by dir name (Pi clock), unchanged. That is acceptable, since the outcome is a loud FAIL, never a false PASS. |
| IN-02 (no feedback on held signal; 10 min kill -9 threshold too close) | **resolved** | The first held signal writes `HELD_SIGNAL_MESSAGE` via `os.write(2)` (async-safe, `OSError` suppressed). The SOAK.md threshold is now ~15 min. `tee -i` keeps the terminal output. See IN-02 below for the wording outside the end of a run. |
| IN-03 (userns parent waits only 30 s after `terminate()`) | open | Not addressed. Impact is now UX-only: such a run is `end_signal` ≠ null and is refused by F3 anyway. |
| IN-03 older (F4 identifies the Pi only by `host.machine == aarch64`), WR-03, WR-04, IN-04, IN-05 (older, deferred) | open (deferred) | Not re-reviewed. |

## Warnings

### WR-01: A `--systemd user` soak with an empty journal copy is "complete", so F3 can PASS with no unit-output evidence

**File:**
- `src/jabuka/soak/systemd.py:817-825` (the zero-entry rule applies only when `not self.user`)
- `scripts/freeze-check.sh:209-215` (`end_state`)
- `src/jabuka/tools/soak.py:1209-1219` (`journal_problem`)

**Issue:** In user scope, the units' stdout and stderr go only to the user journal, and the harness reads them back only through `dump_journal`. A copy with zero entries for both units is recorded as `{"complete": true, "error": null, "entries": {"core": 0, "ingest": 0}}`, so `journal_problem()` returns None. The `tracebacks` check then sees no unit blocks and is `ok: True`.

F3 (x86_64) accepts any mode, so it counts such a report. Unlike F4, there is no `not-units` rule for x86_64. The cause can be a volatile or unreadable user journal (the case the code comment itself names), a wrong `journalctl` on PATH, or `--user` mismatched to the bus. This is exactly the "no traceback evidence → PASS" class that 04-08 was meant to close. It is only kept open for the user scope.

The exemption is not needed:

- On this laptop (systemd 260), a transient `systemd-run --user` unit produces a manager entry `USER_UNIT=<unit> MESSAGE="Started …"`, which `dump_journal` already matches through `USER_UNIT`, plus its own `_SYSTEMD_USER_UNIT` output.
- The documented F3 path (`bash scripts/soak.sh`) is the shim, which does not depend on the journal. Requiring entries in user scope therefore cannot false-FAIL the documented F3.

**Reproduced** against the real code (scratch dir): a fake journalctl that exits 0 with no output, `SystemdBackend("user", …)` with core and ingest. The result was `journal = {"complete": true, "error": null, "entries": {"core": 0, "ingest": 0}}` and `journal_problem(b) = None`. Classified WARNING because the trigger depends on host journald configuration.

**Fix:** Apply the zero-entry rule in both scopes. Alternatively, make freeze-check refuse a systemd-mode report with any `entries[role] == 0`:

```python
# systemd.py dump_journal
if error is None:
    # both scopes: the soak started and stopped these units, so their manager logged them
    empty = [self.unit(r) for r, n in counts.items() if n == 0]
    if empty:
        error = "; ".join(f"no journal entry for {u}" for u in empty)
```

If a volatile laptop journal must stay usable, record `complete: None` for the user-scope empty case instead. `journal_problem()` should then return a reason for it, which keeps the verdict out of PASS. SOAK.md should state that F3 is the shim run.

## Info

### IN-01: Journal loss inside journald (32 MiB volatile vacuum, rate limiting, backward clock step) still reads as a complete copy

**File:**
- `src/jabuka/soak/systemd.py:770-825`
- `deploy/systemd/journald-jabuka.conf` (`Storage=volatile`, `RuntimeMaxUse=32M`)

**Issue:** `complete` only proves that `journalctl` exited 0 and that each unit has at least one entry. Some ways of losing entries pass both tests:

- journald vacuuming the oldest runtime files once the whole system journal exceeds 32 MiB during the soak;
- journald's per-unit rate limit ("Suppressed N messages");
- a backward clock step on the RTC-less Pi, which pushes entries below the `--since @t0-1` wall-clock bound.

In each case the early traceback disappears while the final `Stopping` / `Stopped` lines of PID 1 survive.

**Reproduced** against the real code: a fake journalctl that returns only the two "Stopped" entries gives `complete: true, entries {core: 1, ingest: 1}` and `journal_problem() = None`. A traceback logged earlier in the run would be lost silently.

It is classified Info because, at the measured unit-journal volume (tens of lines), a 32 MiB vacuum within a 2 h soak is unlikely. It does contradict the SOAK.md claim "un échec n'est jamais silencieux".

**Fix:** Cross-check the copy against what the harness itself observed. The monitor already tracks `InvocationID` (SHOW_PROPS). Require every invocation ID seen for a unit to appear in the copy, as `_SYSTEMD_INVOCATION_ID` or `INVOCATION_ID`. Alternatively, require a PID-1 `Started` entry count of at least `svc.starts`. Optionally replace `--since @t0` by a cursor captured at start (`journalctl --show-cursor -n 0`), which does not depend on the clock.

### IN-02: The held-signal line promises "report.json" also where no report will be written

**File:**
- `src/jabuka/soak/systemd.py:62-65` (`HELD_SIGNAL_MESSAGE`)
- `src/jabuka/soak/systemd.py:854` (`SignalHold()` in `_deferred_signals`, default `announce_fd=2`)
- `src/jabuka/soak/systemd.py:1009` (`cleanup_system`)

**Issue:** The nested cleanup hold announces with the same end-of-soak text in two places where that text is wrong:

- **Main-run abort:** a Ctrl-C during the main run aborts it with no report, then the atexit `cleanup()` runs. A second Ctrl-C during that cleanup prints "held until the end of the soak is finished (journal copy, checks, cleanup, report.json …)". No report.json will exist.
- **`--systemd-cleanup` repair:** pressing Ctrl-C during the repair prints the same text.

At the end of a normal run, a second signal after the first can also print the line a second time, because the nested hold's `signal` is still None. An operator following SOAK.md might then wait for a report that never comes, or go hunting for one.

**Fix:** Give `SignalHold` a message parameter. Use a cleanup-specific text in `_deferred_signals`, for example "signal held until the production units are restored". Pass `announce_fd=None` when an outer hold has already announced.

### IN-03: A signal that lands after `end_signal` is computed exits 128+n with `end_signal: null` in the report

**File:** `src/jabuka/tools/soak.py:1413-1423`

**Issue:** `report["end_signal"]` is read before `write_report` and `_give_back`, but the hold lasts until the `finally`. A Ctrl-C in that window returns 130, while `report.json` says `end_signal: null` and F4 accepts it.

The evidence is complete, so this is not a false PASS. It does contradict SOAK.md step 6, which says to bring back only a run that exited with code 0 and whose `end_signal` is null: the report then says null while the run exited with 130.

**Fix:** Either document that the report is authoritative, or re-check `h.end_signals.signal` after `write_report` and rewrite `end_signal` if it changed. That rewrite is cheap, since the report is already serialised.

### IN-04: The group-SIGINT test can pass without exercising the race on a loaded machine

**File:** `tests/soak/test_soak_systemd.py` (`_GROUP_SIGINT_DRIVER`, `fire()` sleeps 0.5 s)

**Issue:** The SIGINT is timed only by a sleep. If spawning the fake journalctl takes longer than 0.5 s, for example on a loaded CI box, the signal is delivered before the child exists. The hold records it, and the child then starts unaffected. The assertions still pass, but they no longer prove that journalctl survives a group signal. This is a regression-guard reliability issue, not a flaky failure.

**Fix:** Have the fake journalctl `touch "$MARK"` after its first line. Make `fire()` poll for that marker before `os.killpg`, and assert that the marker existed when the signal was sent.

---

_Reviewed: 2026-11-08T20:27:39Z_
_Reviewer: Claude (gsd-code-reviewer)_
_Depth: standard_

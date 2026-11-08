---
phase: 04-race-readiness-hardening-commissioning
reviewed: 2026-11-08T17:41:48Z
depth: standard
scope: incremental (8b35611..HEAD, gap-closure plan 04-06)
files_reviewed: 8
files_reviewed_list:
  - docs/FREEZE.md
  - docs/SOAK.md
  - scripts/freeze-check.sh
  - src/jabuka/soak/systemd.py
  - src/jabuka/tools/soak.py
  - tests/commissioning/test_freeze_check.py
  - tests/soak/test_soak_identity.py
  - tests/soak/test_soak_systemd.py
findings:
  critical: 1
  warning: 2
  info: 3
  total: 6
status: issues_found
---

# Phase 4: Code Review Report (incremental, 04-06)

**Reviewed:** 2026-11-08T17:41:48Z
**Depth:** standard (diff 8b35611..HEAD plus the surrounding code)
**Files Reviewed:** 8
**Status:** issues_found

## Narrative Findings (AI reviewer)

## Summary

Plan 04-06 closes the three findings it targeted:

- **Prior CR-01:** F4 now FAILs a Pi report from shim mode, from `--systemd user`, with no `code` block, or with a malformed sha.
- **Prior WR-01:** after the restart, the cleanup checks that both units are ActiveState `active`. If they are not, the run FAILs, the cleanup stays retryable through the backend's own `atexit`, and `--systemd-cleanup` exits 1.
- **Prior WR-02:** a signal held back during the cleanup is written to `pending_signal`, and the process only acts on it after `report.json` is written.

The 74 tests in scope pass (`.venv313`).

The freeze gate can still give a false PASS:

- **F3 and F4 accept any report labelled `race-36h`, however short the run was** (CR-01, reproduced). A `--duration 600` smoke run of the race-36h scenario gets verdict PASS, because faults scheduled after the end are only listed as SKIPPED. freeze-check never reads `sim_s` or `skipped`, and it takes the newest report. So a quick smoke run made after the real soak replaces it, and F4 shows green.
- **F3 skips the git rule completely when a laptop report has `git.head = null`** (WR-01, reproduced). FREEZE.md now says the git rule is mandatory for F3. Plan 04-06 also relies on that rule as the compensating control for the deferred deploy/pyproject gap.

Nothing in this plan touches the race path (nav, core, router, web).

## Prior findings (8b35611 04-REVIEW)

| ID | Status | Notes |
|---|---|---|
| CR-01 (F4 accepts a shim, `--systemd user` or code-less Pi report) | **resolved** | When `machine == "aarch64"`, the helper maps `absent` to `no-code` and anything without `mode == "systemd"` and `code.source == "units"` to `not-units`. Both give FAIL. A user-scope run cannot produce `source "units"`: `compute_code_identity` sets it only when `scope == "system"`. Tests cover shim, user, children with units, a wrong mode, git without a code block, and a malformed sha. The decision to keep the git rule for code-less F3 reports is documented and tested. A separate F3 gap remains (WR-01 below). |
| WR-01 (a failed restart is accepted as done) | **resolved** | `restarted` requires rc 0 **and** `_await_active` (polled for up to 20 s). `cleaned` stays False otherwise, and the backend's `atexit.register(self.cleanup)` (systemd.py:378-381) retries it. `cleanup_fail_reasons` makes the verdict FAIL, `--systemd-cleanup` exits 1 through `CleanupIncomplete`, and `_ctl` runs `systemctl` children with `start_new_session=True`. |
| WR-02 (a signal during cleanup loses report.json) | **resolved for the cleanup window** | The signal is recorded and never re-raised. `run_soak` writes the report, then returns 128+n. A smaller report-loss window remains outside the cleanup (WR-02 below); the plan accepts it as risk T-04-06-04. |
| WR-03 ("restauré" badges can never be cleared) | open (deferred in 04-06 with rationale) | Race-path UX. Not re-reviewed. |
| WR-04 (the git-less F4 path does not cover `deploy/**` or `pyproject.toml`) | open (deferred, T-04-06-05) | The deferral relies on "F3's git rule FAILs the laptop soak on any deploy/pyproject change". WR-01 below shows that F3 rule can be skipped, so the compensating control is weaker than stated. |
| IN-01 … IN-05 | open (deferred in 04-06) | Not re-reviewed. |
| IN-06 (cleanup_system test used the real /proc/mounts and umount) | **resolved** | Both `cleanup_system` call sites in the tests pass `proc_mounts=tmp_path / "mounts"` and use `_fake_unmount`. |

## Critical Issues

### CR-01: F3 and F4 PASS a shortened (`--duration`) or custom race-36h run, and the newest report replaces the real soak

**File:** `scripts/freeze-check.sh:153-176`, `scripts/freeze-check.sh:198-199`; also `src/jabuka/tools/soak.py:134`, `src/jabuka/tools/soak.py:713-720`, `src/jabuka/soak/report.py:342-355`

**Issue:** The helper selects reports only by `scenario == "race-36h"` and `host.machine`, and keeps the newest run directory. It then reads only verdict, mode, git and code. Two facts make a short run pass:

- `jabuka-soak --duration SIM_S` keeps `scenario = "race-36h"`.
- `run_faults` puts every fault scheduled after the shortened end into `skipped`, and `decide()` ignores `skipped`. Such a run therefore gets `verdict: "PASS"`.

docs/SOAK.md:44-47 advertises `--duration` as the "essai rapide" option and says skipped faults are "jamais comptées comme passées". freeze-check counts them anyway.

**Reproduced** against the real script with the `Frozen` fixture: a `pi_report()` with `sim_s: 600`, `faults: []` and a `skipped` power-pull gives `[PASS] F4 Pi : … PASS, paquet installé = src/jabuka à HEAD`, and `freeze-check: ok`.

Realistic path: after the real 2–4 h Pi soak (FAIL, or not yet copied back), the operator runs a 10-minute `--scenario race-36h --duration 600` sanity check on the Pi, for example after a reinstall. That run is newest, so F4 certifies a 36 h endurance run that never happened. The same applies to F3, and to `--scenario /path/custom.json` with `"name": "race-36h"`, which the code fingerprint does not cover.

**Fix:** Make the harness record what was actually run, and have freeze-check require the full scenario:

```python
# soak.py build_report: add next to "scenario"
"duration_s": self.duration,
"scenario_duration_s": self.sc.duration_s,
"scenario_source": self.sc.source,       # "scenarios/race-36h.json" when packaged
```

```python
# freeze-check helper, after picking best (stdlib only): compare with the scenario at HEAD
full = json.loads(subprocess.run([git, "-C", repo, "show",
    "HEAD:src/jabuka/soak/scenarios/race-36h.json"], capture_output=True, check=True).stdout)["duration_s"]
short = [s for s in r.get("skipped") or [] if "after the end of the run" in str(s.get("reason"))]
if (r.get("sim_s") or 0) < 0.99 * full or short or r.get("scenario_source") not in (None, "scenarios/race-36h.json"):
    state, detail = "short", f"sim_s {r.get('sim_s')} / {full}, {len(short)} panne(s) après la fin"
```

```bash
elif [ "$cstate" = short ]; then
    say FAIL "$id" "$label : $path essai raccourci ou scénario non packagé ($detail) : refaire le soak race-36h complet"
```

Better still, have `decide()` (or `run_soak`) return a non-PASS verdict such as `"SHORT"` whenever `args.duration < sc.duration_s`, so the report cannot claim PASS. Add a freeze-check test with a `pi_report()` that sets `sim_s: 600` plus a skipped "after the end of the run" fault and expects FAIL.

## Warnings

### WR-01: F3 skips the git rule when a laptop report has `git.head = null`, which contradicts FREEZE.md and the compensating control for the deferred WR-04

**File:** `scripts/freeze-check.sh:198-199`, `docs/FREEZE.md` (new "Règle par élément", F3 bullet), `scripts/freeze-check.sh:8-12`

**Issue:** The `match && head = -` shortcut on line 198 applies to F3 as well as F4. An x86_64 report with a matching `code.sha256` (source `children`) and `git.head: null` therefore PASSes without the clean-tree check and without the `src/ deploy/ pyproject.toml` diff.

FREEZE.md now says F3 is "la règle git (…), plus l'empreinte quand le rapport en porte une", so the git rule should always apply to F3. Plan 04-06 also defers WR-04 (T-04-06-05) on the grounds that "F3's git rule FAILs the laptop soak on any post-soak change under deploy/ or pyproject.toml".

**Reproduced:** commit a change to `deploy/systemd/jabuka-fastnet-relay.service` and `pyproject.toml` after the soak. Then rewrite the laptop report with `git: {head: null, dirty: null}` and a matching `children` code block. The result is `[PASS] F3 portable : … paquet installé = src/jabuka à HEAD`.

`git_info` returns null head whenever `/usr/bin/git` is missing, `rev-parse` or `status` times out (10 s), or the run's checkout has no `.git`. None of these are exotic on a dev laptop.

**Fix:** Restrict the fingerprint-only PASS to F4. For F3, require a git head:

```bash
elif [ "$cstate" = match ] && [ "$head" = - ] && [ "$machine" = aarch64 ]; then
    say PASS "$id" "$label : $path PASS, paquet installé = src/jabuka à HEAD ($detail)"
```

With this change, an x86_64 report with no head falls through to `git.head inconnu` (FAIL). Also update header lines 10-12, which still describe the Pi `units` and null-head case under F3. Add a test: an x86_64 report with a matching `code` and `head: null` must FAIL F3.

### WR-02: A signal outside the cleanup block still loses report.json at the end of the Pi soak

**File:** `src/jabuka/tools/soak.py:776-793` (`Harness.run`: `shutdown()` → `build_report()` → `cleanup()` → `cleanup_fail_reasons`), `src/jabuka/tools/soak.py:1349-1353`

**Issue:** Signals are deferred only inside `SystemdBackend.cleanup()`. The end-of-run work before it is not covered. That work is:

- `shutdown()`: stopping the units, then `dump_journal` over 2–4 h of journald JSON for two units.
- `build_report()`: `compute_checks`, which includes the final `run_logcheck("end")` over the whole soak log tree.

On a Pi 3B this plausibly takes tens of seconds or longer, not the "seconds" assumed in T-04-06-04. During that time, and in the short gap between handler restore and `write_report`, a Ctrl-C or SIGTERM becomes `KeyboardInterrupt` or `SystemExit` and escapes `run()`. The backend's atexit still restores the units, but the 2–4 h report is lost and the soak must be redone 2–3 days before the race.

The new SOAK.md text ("ne fait plus perdre le rapport") is accurate only for the cleanup itself. tmux removes the SIGHUP case, but not Ctrl-C or a `systemctl`/shutdown SIGTERM.

**Fix:** Hold signals over the whole end-of-run sequence, and act on them after the report is written. For example, expose the deferral as a public context manager and wrap it around everything from `self.shutdown()` to `write_report`:

```python
# Harness.run
finally:
    with self.sup.deferred_signals() if isinstance(self.sup, sd.SystemdBackend) else contextlib.nullcontext():
        self.shutdown()
        report = self.build_report()  # (keep the try/finally around cleanup)
        ...
```

Or record the signal in the soak's own handler (`_on_signal` sets a flag once `h.ending` is True), and check that flag after `write_report`.

## Info

### IN-01: Stale "second Ctrl-C" wording; a hung cleanup can no longer be interrupted

**File:** `src/jabuka/soak/systemd.py:774-781` (docstring: "an interrupted cleanup (exception, second Ctrl-C)"), `docs/SOAK.md:262` (step 8: "Ctrl-C deux fois")

**Issue:** `_deferred_signals` now records every SIGINT, SIGTERM and SIGHUP and never re-raises them, so a second Ctrl-C no longer interrupts the cleanup. That is the intended behaviour, but the docstring and the step-8 trigger still describe the old one. A stuck cleanup can be stopped only with `kill -9`. It is bounded by the `_ctl` timeouts: daemon-reload 60 s, restart 180 s, the verify 20 s, umount 2×30 s per mount, then cat 60 s.

**Fix:** Correct the docstring and SOAK.md step 8. For example: "the cleanup cannot be interrupted (≤ ~6 min); if it hangs: `sudo kill -9 <pid>` then `--systemd-cleanup`".

### IN-02: The deferred-signal path is never tested end to end

**File:** `tests/soak/test_soak_systemd.py` (`test_run_soak_writes_the_report_before_honouring_a_deferred_signal`)

**Issue:** The run_soak test replaces `Harness.run` with a stub that sets `pending_signal` by hand. The backend test checks `cleanup()` on its own. Nothing checks that a signal arriving during the real `Harness.run()` → `self.sup.cleanup()` reaches `run_soak` as `pending_signal`, with the report written and `128+n` returned. A future refactor could put the cleanup back outside `h.sup`, or reset the backend, and both tests would still pass.

**Fix:** Add one test that runs `Harness.run` with the fake systemctl, and sends `os.kill(os.getpid(), SIGTERM)` from a patched `_ctl("restart")`.

### IN-03: F4 identifies "the Pi" only by `host.machine == "aarch64"`

**File:** `scripts/freeze-check.sh:161`

**Issue:** Any aarch64 host (an ARM laptop, a VM, a Pi 4/5 dev board) running `--systemd system` against an `/opt/jabuka` install satisfies F4. The report already has a Pi-specific `pi` block (from `probes.pi_summary`, with `get_throttled` and temperature), and F4 does not require it. As a result, F4 can PASS without the Pi 3B CPU and RAM budgets having been exercised.

**Fix:** For F4, also require `isinstance(r.get("pi"), dict)`. Optionally also require a model string from `/proc/device-tree/model` in `host`, if one is recorded.

---

_Reviewed: 2026-11-08T17:41:48Z_
_Reviewer: Claude (gsd-code-reviewer)_
_Depth: standard_

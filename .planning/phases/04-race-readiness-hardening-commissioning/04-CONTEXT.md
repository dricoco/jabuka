# Phase 4: Race Readiness — Hardening & Commissioning - Context

**Gathered:** 2026-11-06
**Status:** Ready for planning
**Mode:** Smart discuss auto-accepted. The user asked to "continue without me" and later confirmed "corrige tout". Decisions below are Claude's recommendations, grounded in the ROADMAP Phase 4 success criteria, `.planning/research/PITFALLS.md`, and the Phase 1–3 outcomes (UAT files, REVIEW files, SUMMARYs). Revisit if the user objects.

<domain>
## Phase Boundary

This phase proves the whole stack runs about 36 h unattended and recovers from every fault we can simulate. It also gives the owner one written, rehearsed runbook to commission the system on the real boat on 12–13 Nov.

Deliverables:
- an automated accelerated soak harness, runnable on the laptop and on the Pi;
- memory, CPU and recovery budgets;
- the commissioning runbook, dry-run against a replayed capture;
- a spare-SD-card procedure;
- a freeze checklist.

Out of scope: new features (frozen 2026-11-11), the Slovenian UI (possible later request), and polar learning.
</domain>

<decisions>
## Implementation Decisions

### Soak harness (REL-02)
- **Tool:** `jabuka-soak` CLI (`src/jabuka/tools/soak.py`) plus `scripts/soak.sh`. It drives the real processes (ingest-fastnet on a pty replay, core, router worker pool, fake gpsd) under SimClock at about 60×. A 36 h race maps to about 36 min wall time, and the speed is configurable.
- **Scenario:** a scripted fault schedule. JSON, seeded and reproducible.
- **Faults:**
  - Fastnet silent (minutes);
  - garbage bytes and parity errors;
  - pty close and reopen (USB unplug);
  - GPS loss and return;
  - clock jump (±1 h, GPS time arriving late after boot);
  - kill -9 of core, of ingest, and of the router worker;
  - SIGTERM storms;
  - simulated power pulls (kill all processes, restart from persisted state);
  - truncated or corrupted state files;
  - full disk on the log partition (simulated by a quota or tmpfs);
  - a GRIB coverage gap;
  - a course change mid-leg;
  - ON RESTE toggled during a reroute.
- **Assertions, checked continuously by a WS client acting as the "tablet":**
  - live data reappears within N s after each fault clears (budget: 10 s for bus/GPS, 30 s for a process restart, 60 s for a power pull);
  - no unhandled exceptions in logs;
  - the route is recomputed after recovery, and no route ever crosses land (re-validated by the harness);
  - course and settings survive every power pull (CRSE-05, REL-01 re-check);
  - RSS of core and worker stays within budget (core ≤ 250 MB, worker ≤ 250 MB on the laptop proxy; Pi numbers to confirm), with no monotonic growth (linear fit slope below threshold);
  - fd count and thread count stay stable;
  - disk usage follows retention.
- **Output:** a JSON and Markdown soak report (`var/soak/<ts>/report.md`) with a timeline of faults and recoveries and the memory curve. Exit 0 or 1.
- **Tests:** a short CI soak (about 2 min wall, compressed schedule) in pytest, marked `soak`. The full 36 h-equivalent run is a manual command, run once on the laptop now and once on the Pi (human item, by 2026-11-10).
- **Fixes:** fixes found by the soak are in scope for this phase. They are bug fixes, not features.

### Pi specifics
- On the Pi, the harness runs against the installed systemd units (restart policy and watchdog are real) when `--systemd` is given. The laptop uses a process supervisor shim that mimics `Restart=always` with `RestartSec`.
- **Read-only overlay FS:** optional. Document how to try it once (`raspi-config nonint enable_overlayfs`) and the rollback; the default is atomic writes plus the spare SD card.
- **Spare SD:** a documented `dd`/rpi-clone procedure and verification (boot the clone, run `jabuka-logcheck` and `fastnet-probe` against the replay).

### Commissioning runbook (REL-03)
- `docs/COMMISSIONING.md`, in French (the owner is French), with a short Slovenian summary card for the skipper, optional. It is a timed checklist for 12 Nov (boat day 1) and 13 Nov (race day) that covers:
  1. **Before leaving home:** packing list (Pi, spare SD, DTECH, GPS, cables, 12 V→USB, tablet + 3D case, tools, fuses), the pack built and checked, the Pi bench result recorded.
  2. **Wiring:** tap-harness to the Fastnet bus (White = Data+, Green = Data−, no termination, listen-only), photos, swap-wires procedure driven by `fastnet-probe` exit codes (2 = no bytes, 3 = swap wires, 4 = noisy, 5 = few).
  3. **Capture:** record raw bytes first (before anything else), then cycle every B&G display page to build the channel inventory, then archive the capture.
  4. **Checks:** true vs magnetic (variation, heading offset), COG vs HDG at the dock and under way, AWA sign, BSP calibration sanity, Hercules TWD vs computed, and choose the `true_wind_source` default.
  5. **Tablet:** Wi-Fi AP join, airplane mode, Chrome flag, stay awake, night brightness, lock test, mount in the 3D case at the helm.
  6. **Race pack (Fri 13 Nov after ~15:40 UTC):** the final ICON-EU/EWAM download, live Overpass land mask, organiser GRIB if any, `racepack-dryrun.sh`, coverage report OK, copy to the Pi, restart, verify the route appears.
  7. **Course setup:** rounding sides and start/finish from the SIs; a course-change drill under 30 s.
  8. **Degraded-mode drills:** pull the Fastnet adapter (GRIB-only), enter manual wind, ON RESTE, power-pull recovery.
  9. **Go / no-go criteria and Plan B:** OpenCPN on a laptop via fastnet2ip relay; B&G displays plus paper chart.
- **Dry run:** a scripted rehearsal (`scripts/commissioning-rehearsal.sh`) runs every automatable runbook step against the replayed capture and synthetic boat on the laptop, and prints PASS/FAIL per step. Steps that need hardware print "HUMAN" with the expected observation.
- **Feature freeze 2026-11-11:** a `docs/FREEZE.md` checklist: tag `race-2026`, wheelhouse rebuilt, lock reviewed, spare SD cloned from the frozen build. After the freeze, only configuration changes.

### Claude's Discretion
- Exact module layout, fault schedule details, budget thresholds within stated ranges, report formatting.
</decisions>

<code_context>
## Existing Code Insights
- **Phase 1:** `sim/pty_replay` (with fault injection), `sim/synth`, `sim/fake_gpsd`, `tools/fastnet-probe`, `tools/logcheck`, `ingest/retention.py`, systemd units with WatchdogSec, `deploy/provision.sh --dry-run`, `scripts/check.sh`.
- **Phase 2:** the closed-loop synthetic boat (`tests/sim/test_closed_loop.py`), the course/settings persistence via atomic IO, the lock/night UI, and `docs/TABLET-SETUP.md`.
- **Phase 3:**
  - the router pool (forkserver, timeout, recreate on crash) and `jabuka-route-bench`;
  - `scripts/racepack-dryrun.sh`, `docs/ROUTING.md` (Pi bench section) and `docs/WEATHER-PACK.md` (Friday checklist).
- **Open human items already listed:** 01-UAT (8), 02-UAT (10), and the 03-06 human items. The runbook must reference rather than duplicate them.
</code_context>

<specifics>
## Specific Ideas
- The user is French; the skipper is Slovenian (a Slovenian explainer page was made for them). Runbook in French.
- Boat access only on 12–13 Nov; the night start on 13 Nov is from 20:00.
- The tablet is mounted at the helm in a 3D-printed case.
</specifics>

<deferred>
## Deferred Ideas
- Slovenian/French language switch in the UI (offered to the user, not requested yet).
- Read-only root FS as the default.
</deferred>

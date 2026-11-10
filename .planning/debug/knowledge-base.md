# GSD Debug Knowledge Base

Resolved debug sessions. Used by `gsd-debugger` to surface known-pattern hypotheses at the start of new investigations.

---

## soak-route-not-refreshed — Pi system-scope soak FAIL: "no new route (version > N)", grib-gap ValueError, manual CHANGED by a clean pull, keepalive AssertionError
- **Date:** 2026-11-10
- **Error patterns:** no new route (version > 114) within 60 s, no optimal route after On reste was switched off, route_after_recovery missing, refusing to touch ... racepack: outside the soak run dir, manual CHANGED by a clean pull, AssertionError keepalive ping failed _drain_helper assert waiter is None or waiter.cancelled(), recovery_gps/recovery_process/recovery_power NON, soak race-36h system scope
- **Root cause(s):** harness baseline tablet.max_route_version() = run-wide max while a core restart (course changed) legitimately renumbers routes from 1 (routes were in fact refreshed 4-15 s after each fault; not an app defect, under-voltage not involved); Harness.write_full_wind used run_dir instead of state_root as the pack guard root (system scope keeps the pack under /var/lib/jabuka/soak-<ts>); power_pull SIGKILLed 0.3-0.5 s after POST /api/wind/manual, inside the core's documented background-durability window (atomicio G-4-R05); uvicorn legacy websockets keepalive ping asserts on a client stalled > ws_ping_interval (20 s) during 30-s ws-stall faults (benign)
- **Fix:** last_route_version() as the "before" baseline in every fault; write_full_wind under state_root; power_pull waits (<= 10 s) for wind_manual.json on disk to equal the acknowledged value, records manual_durable_s, fails otherwise; race-36h.json expected_tracebacks["ws-stall"] for the legacy keepalive AssertionError. No app change. Post-race follow-ups: uvicorn ws='websockets-sansio'; route.js nav fallback `v !== drawn` after a same-number restart; garbage settings.json left after f11 in the soak.
- **Files changed:** src/jabuka/soak/tablet.py, src/jabuka/soak/faults.py, src/jabuka/tools/soak.py, src/jabuka/soak/scenarios/race-36h.json, tests/soak/test_soak_faults.py
- **Why not caught:** no gate existed for this class: no fake-harness tests of the fault functions; CI soak runs user scope (pack under run_dir), short ws-stalls, fast disk; first full system-scope Pi soak was the first gate able to see it
- **Recurrence guard:** tests/soak/test_soak_faults.py (13 tests, commit 35a61a7) incl. test_course_change_after_a_renumbering_restart_sees_the_new_route, test_full_wind_is_restored_under_the_state_root, test_clean_pull_waits_for_the_acknowledged_manual_wind_on_disk, test_race_36h_keepalive_rule_expects_nothing_else; runtime manual_durable_s check in faults.power_pull; this KB entry. Status: resolved-pending-soak (user's next Pi race-36h soak)
---


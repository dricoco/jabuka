---
phase: quick-261111-07n
verified: 2026-11-10T23:50:31Z
status: human_needed
score: 8/9 must-haves verified
covered_files:
  - .planning/REQUIREMENTS.md
  - .planning/quick/261111-07n-correctif-durable-ap-jabuka-retirer-wpa-/261111-07n-PLAN.md
  - .planning/quick/261111-07n-correctif-durable-ap-jabuka-retirer-wpa-/261111-07n-SUMMARY.md
  - deploy/PI-SETUP.md
  - deploy/jabuka-wifi
  - deploy/nm-dispatcher/90-jabuka-ap-keymgmt
  - deploy/provision.sh
  - tests/deploy/test_nm_dispatcher.py
  - tests/deploy/test_provisioning_files.py
covered_digest: "v1:sha256:3b334e41c9904ce5361613c6c1a48003ec5479f4325013e46f62ca9edf111c64"
behavior_unverified: 1
overrides_applied: 0
behavior_unverified_items:
  - truth: "Every path that brings the AP up goes through the same NM 'up' event and is therefore covered: boot autoconnect, provision's `nmcli connection up jabuka-ap`, `sudo jabuka-wifi ap`, jabuka-wifi's fallback after a failed phone join, and NM's autoconnect fallback when the phone hotspot disappears"
    test: "On the Pi after `sudo deploy/provision.sh`: check `sudo wpa_cli -i wlan0 status | grep key_mgmt` and `journalctl -b -t jabuka-wifi | grep key_mgmt` after (1) provision, (2) a reboot, (3) `sudo jabuka-wifi phone` then `sudo jabuka-wifi ap`, (4) phone hotspot switched off while on jabuka-phone (NM autoconnect fallback)"
    expected: "key_mgmt=WPA2-PSK each time, one dispatcher log line per activation, tablet and phone both join jabuka and open http://10.42.0.1/, the AP stays up (no repeated reset lines, no 'boucle évitée')"
    why_human: "Tests only prove the script reacts correctly to a simulated (wlan0, up, CONNECTION_ID=jabuka-ap) call against a fake wpa_cli. Whether real NetworkManager-dispatcher fires that event on each path, whether wpa_cli reaches NM's wpa_supplicant control socket, and whether NM tolerates the disconnect/select_network without tearing jabuka-ap down and re-creating the SHA256 network can only be observed on the Pi 3B"
human_verification:
  - test: "Deferred on-Pi check (plan Task 3 human-check), after the soak: run `sudo deploy/provision.sh`, then `sudo wpa_cli -i wlan0 status | grep key_mgmt`"
    expected: "key_mgmt=WPA2-PSK; `ls -l /etc/NetworkManager/dispatcher.d/90-jabuka-ap-keymgmt` shows -rwxr-xr-x root root; `systemctl is-enabled NetworkManager-dispatcher` shows enabled"
    why_human: "Requires the real Pi (NM 1.52.1, brcmfmac); the Pi is busy with a soak and must not be touched now"
  - test: "Tablet (Android 11) and phone both join `jabuka` and open http://10.42.0.1/"
    expected: "Both associate and stay associated (no drop after M3), diagnostics page shows values"
    why_human: "Real 4-way handshake with real clients; cannot be simulated"
  - test: "Reboot the Pi, then repeat the key_mgmt check and the tablet join"
    expected: "key_mgmt=WPA2-PSK and a dispatcher line in `journalctl -b -t jabuka-wifi` for this boot"
    why_human: "Boot autoconnect path of NetworkManager-dispatcher"
  - test: "`sudo jabuka-wifi phone`, then `sudo jabuka-wifi ap`; also let the phone hotspot disappear while on jabuka-phone"
    expected: "key_mgmt=WPA2-PSK again after each return to the AP; tablet rejoins; no 'boucle évitée' in the journal"
    why_human: "jabuka-wifi and NM autoconnect fallback paths; NM reaction to wpa_cli disconnect/select_network in AP mode"
---

# Quick 261111-07n: durable fix for the jabuka AP (drop WPA-PSK-SHA256) Verification Report

**Goal:** Make the field workaround for the "jabuka" AP permanent in the deployment, so the tablet and the phone can join the Pi's AP after every boot, provision run and Wi-Fi switch, with no manual wpa_cli step on the boat; must never break NetworkManager.
**Verified:** 2026-11-10T23:50:31Z
**Status:** human_needed
**Re-verification:** No, initial verification

## Goal Achievement

### Observable Truths

| # | Truth | Status | Evidence |
|---|-------|--------|----------|
| 1 | jabuka-ap up on wlan0 with SHA256 -> set_network <listed id> key_mgmt WPA-PSK, disconnect, select_network <same id>, logged under tag jabuka-wifi | VERIFIED | Script `main`/`lookup`/`pick_id`/`apply` (lines 82-180): id picked from `list_networks` by ssid then [CURRENT], all-digit check at parse and use site. `test_sha256_is_reset_to_wpa_psk_on_the_listed_id` uses id 3 next to an id-0 row, asserts order, no id 0, one `logger -t jabuka-wifi` line; `test_falls_back_to_the_current_network` (id 5). Passed. |
| 2 | Already WPA-PSK -> no change; second up event is a no-op | VERIFIED | `case "$KEY_MGMT" in *WPA-PSK-SHA256*` else logs "rien à faire" and returns (line 166-173). `test_already_wpa_psk_is_left_alone`, `test_second_up_event_is_a_no_op` (stateful fake, set_network exactly once over two runs). Passed. |
| 3 | Loop guard: max 3 fixes in 60 s, stamps under /run/jabuka-wifi | VERIFIED | `guard_allows` (lines 108-129), RUN_DIR default /run/jabuka-wifi, WINDOW_S=60, MAX_FIXES=3, best effort on unwritable dir, future/junk stamps dropped. `test_loop_guard_stops_after_three_fixes_in_60s` (4 sticky runs -> 3 set_network, 4th logs "boucle"), `test_stale_stamps_do_not_block_the_fix`, `test_future_and_junk_stamps_do_not_block_the_fix`. Passed. |
| 4 | Every other event is a silent no-op (no wpa_cli, no log) | VERIFIED | Three early `return 0` checks on $1, $2, `${CONNECTION_ID:-}` before any call (lines 154-156). `test_every_other_event_is_silent` parametrized over the 9 cases of the plan, asserts `calls() == []` (covers wpa_cli, logger, sleep). Passed. |
| 5 | Never breaks NM: always exit 0; missing wpa_cli, failing wpa_cli, FAIL replies; bounded wait <= 10 attempts 1 s apart | VERIFIED | `set -u` only, no errexit (static test + grep); `main "$@"; exit 0`; ATTEMPTS=10 with sleep only between attempts; `wpa_ok` requires exit 0 AND `OK`. Tests d1 (missing, no sleep), d2 (10 list_networks, 9 `sleep 1`), d3 (get FAIL bounded), d4 (set FAIL -> no disconnect/select), bounded-wait success (2 sleeps). Passed. |
| 6 | provision.sh installs root:root 0755 into dispatcher.d, enables NetworkManager-dispatcher.service, before `nmcli connection up jabuka-ap` (last command), also with --skip-ap | VERIFIED | provision.sh section f lines ~245-252 (outside the SKIP_AP branch). Own dry run: install line #37, enable #38, `+ nmcli connection up jabuka-ap` #77 and last `+ ` line; `--skip-ap` dry run with secrets.env.example prints install + enable and no `nmcli`. Tests `test_dry_run_installs_the_ap_keymgmt_dispatcher_before_the_ap`, skip-ap assertion, order list. Passed. |
| 7 | Every AP activation path (boot, provision, jabuka-wifi ap, phone-join fallback, NM autoconnect fallback) is covered via the NM 'up' event | PRESENT_BEHAVIOR_UNVERIFIED | Wiring present: all jabuka-wifi paths use `nmcli -w 30 connection up "$AP"` (lines 123, 128), provision ends with `nmcli connection up jabuka-ap`, script reacts to (wlan0, up, jabuka-ap). That NM-dispatcher really fires and that NM tolerates the wpa_cli re-select on each path is runtime behavior of the real Pi that no test exercises -> human verification. |
| 8 | PI-SETUP.md §4 g key_mgmt=WPA2-PSK check + why + client joining; §6 manual wpa_cli workaround instead of the PMF toggle | VERIFIED | f529445 diff: item g kept (same letter/format) with `sudo wpa_cli -i wlan0 status | grep key_mgmt`, journal check, why paragraph, tablet AND phone, re-check after phone->ap. §6 bullet keeps its title, checks dispatcher (ls/is-enabled/journal, "boucle évitée"), manual list_networks/set_network <id>/disconnect/select_network <id>, PMF toggle removed, `wifi-sec.pmf` stays `disable`. `tests/commissioning/test_runbook_docs.py`: 18 passed. |
| 9 | Gate green; no src/ change; nothing deployed | VERIFIED | `git diff --stat 9f5b55f f529445`: only the 6 planned files (no src/, docs/, cad/, stl/, hardware/); AP_PROPS/pmf untouched (provision diff is +8 lines only in section f). Scoped run here: tests/deploy 122 passed, test_runbook_docs 18 passed. Full `scripts/check.sh` not re-run per instructions (orchestrator-reported green: 2079 passed). Pi not accessed. |

**Score:** 8/9 truths verified (1 present, behavior-unverified)

### Required Artifacts

| Artifact | Expected | Status | Details |
|----------|----------|--------|---------|
| `deploy/nm-dispatcher/90-jabuka-ap-keymgmt` | bash dispatcher, 100755, contains WPA-PSK-SHA256 | VERIFIED | 183 lines, `#!/bin/bash`, git mode 100755, substantive, installed by provision |
| `deploy/provision.sh` | install root:root 0755 + enable dispatcher | VERIFIED | `run install -D -o root -g root -m 0755 ... /etc/NetworkManager/dispatcher.d/90-jabuka-ap-keymgmt`, `run_tolerant systemctl enable NetworkManager-dispatcher.service`, missing-file guard `die 3` |
| `deploy/jabuka-wifi` | comment above do_switch naming 90-jabuka-ap-keymgmt | VERIFIED | 4-line comment above `do_switch()`; header lines 2-15 untouched (no --help shift) |
| `deploy/PI-SETUP.md` | §4 g key_mgmt=WPA2-PSK + why, §6 manual fix | VERIFIED | see truth 8 |
| `tests/deploy/test_nm_dispatcher.py` | behaviour tests with stateful fake wpa_cli, JABUKA_WPA_CLI | VERIFIED | 329 lines, 24 tests, env strips FAKE_/JABUKA_/CONNECTION_ vars and always sets JABUKA_WPA_CLI to fake or non-existent path |
| `tests/deploy/test_provisioning_files.py` | dry-run install/enable/order, --skip-ap | VERIFIED | DISPATCHER_DEST/DISPATCHER_ENABLE assertions, token + order list entries |

### Key Link Verification

| From | To | Via | Status | Details |
|------|----|-----|--------|---------|
| provision.sh section f | /etc/NetworkManager/dispatcher.d/90-jabuka-ap-keymgmt | `install -D -o root -g root -m 0755` | WIRED | Present in source and in dry-run output, before AP up, also with --skip-ap |
| NM-dispatcher (wlan0 up, CONNECTION_ID=jabuka-ap) | wpa_cli list_networks -> get_network -> set_network -> disconnect -> select_network | the dispatcher script | WIRED (simulated) | `set_network "$id" key_mgmt WPA-PSK` at line 136; sequence asserted by tests against the fake; real NM invocation is human item |
| jabuka-wifi do_switch (ap, phone fallback) | the dispatcher | `nmcli -w 30 connection up "$AP"` | WIRED (by NM semantics) | Lines 123 and 128 unchanged; event delivery on the Pi is human item |

### Behavioral Spot-Checks

| Behavior | Command | Result | Status |
|----------|---------|--------|--------|
| Deploy test suite (dispatcher + provision) | `.venv313/bin/pytest -q tests/deploy` | 122 passed in 22.65s | PASS |
| Runbook item parser | `.venv313/bin/pytest -q tests/commissioning/test_runbook_docs.py` | 18 passed | PASS |
| Dry-run order | `bash deploy/provision.sh --dry-run --psk-file <tmp>` | install #37, enable #38, last `+ nmcli connection up jabuka-ap` #77 | PASS |
| --skip-ap install | `bash deploy/provision.sh --dry-run --skip-ap --psk-file deploy/secrets.env.example` | install + enable printed, no `nmcli` | PASS |
| Executable bit in git | `git ls-files -s deploy/nm-dispatcher/90-jabuka-ap-keymgmt` | 100755 | PASS |

### Probe Execution

No probes declared for this task. SKIPPED.

### Requirements Coverage

| Requirement | Source Plan | Description | Status | Evidence |
|-------------|-------------|-------------|--------|----------|
| DATA-01 | 261111-07n-PLAN | Pi AP at a fixed IP that the tablet joins | NEEDS HUMAN | Code path in place and tested against fakes; the tablet actually joining is only observable on the Pi |

### Anti-Patterns Found

| File | Line | Pattern | Severity | Impact |
|------|------|---------|----------|--------|
| (none) | - | No TBD/FIXME/XXX/TODO/HACK in the new script or test file; banned AP/DHCP daemon names absent (test_no_competing_ap_stack green) | - | - |

Info: `guard_allows` records a stamp before `apply`, so a failed set_network still counts toward the 3-in-60 s budget. Conservative and harmless (it only makes the guard trip sooner).

### Human Verification Required

1. **Provision on the Pi** - after the soak, `sudo deploy/provision.sh`, then `sudo wpa_cli -i wlan0 status | grep key_mgmt`. Expected `key_mgmt=WPA2-PSK`, script `-rwxr-xr-x root root`, NetworkManager-dispatcher enabled.
2. **Clients join** - tablet and phone join `jabuka`, stay associated, open http://10.42.0.1/.
3. **Reboot** - key_mgmt=WPA2-PSK and a dispatcher journal line for this boot.
4. **Wi-Fi switches** - `sudo jabuka-wifi phone` then `sudo jabuka-wifi ap`, plus NM autoconnect fallback when the phone hotspot disappears: key_mgmt=WPA2-PSK each time, no "boucle évitée", AP stays up (confirms NM tolerates the disconnect/select_network without re-creating the SHA256 network).

### Gaps Summary

No code gaps. Every must-have that can be checked off the Pi is present, substantive, wired and exercised by passing tests. The only open truth is the runtime behaviour of real NetworkManager-dispatcher and wpa_supplicant on the Pi 3B across all AP activation paths. By design that is deferred to the post-soak deployment, so the status is human_needed.

---

_Verified: 2026-11-10T23:50:31Z_
_Verifier: Claude (gsd-verifier)_

---
status: testing
phase: 04-race-readiness-hardening-commissioning
source: [04-VERIFICATION.md]
started: 2026-11-08T20:40:00Z
updated: 2026-11-08T20:40:00Z
---

## Current Test

number: 1
name: Laptop race-36h soak on the final pre-freeze HEAD (full length, no Ctrl-C at the end)
expected: |
  `bash scripts/soak.sh --scenario race-36h` on a clean tree, no --duration. Verdict PASS, exit 0,
  report.json end_signal null, duration_s 129600, sim_s >= 129600, scenario_sha256 = sha256 of
  race-36h.json at HEAD, no "after the end of the run" skips. freeze-check F3 PASS.
  Quick runs go to `--out var/soak-essais`, never var/soak/.
awaiting: user response

## Tests

### 1. Laptop race-36h soak on the final pre-freeze HEAD (full length, no Ctrl-C at the end)
expected: Verdict PASS, exit 0, end_signal null, duration_s 129600, sim_s >= 129600, scenario_sha256 matches HEAD, no late skips; freeze-check F3 PASS (today F3 FAILs by design: older reports predate end_signal/scenario_sha256)
result: [pending]

### 2. Pi 3B system-scope soak (ROADMAP SC1)
expected: Rebuild wheelhouse from final HEAD (`bash scripts/build-wheelhouse.sh`), re-provision the Pi (installed fingerprint = c36c79860a3a2f8d97b0f60a5721adc50e131db0760ac6e6b1f337b34a9e2c58 if src/jabuka unchanged). `sudo apt install -y tmux` while online. In `tmux new -s soak`: `cd ~/jabuka && sudo bash scripts/soak.sh --systemd system --python /opt/jabuka/venv/bin/python --scenario race-36h --speed 20 --logs-fs loop:512M`; no Ctrl-C at the end. No startup WARNING; exit 0, verdict PASS, end_signal null, systemd.journal.complete true with core > 0 and ingest > 0 entries, non-empty proc/*-journal.log, tick ratio >= 0.95, RSS <= 250 MB, no throttling/under-voltage, cleanup.restarted true. After scp of that run dir + reboot: `systemctl cat jabuka-core | grep -c 50-jabuka-soak` = 0 and both units active. freeze-check F4 PASS.
result: [pending]

### 3. Pi budgets recorded in docs/SOAK.md "Budgets Pi à confirmer"
expected: RSS, temperature and throttling filled in; numbers fit the 1 GB Pi (also closes 03-05 "Pi memory")
result: [pending]

### 4. 5 real power pulls on the Pi, each followed by jabuka-logcheck
expected: Services come back each time, logcheck OK, course and settings intact (a visible ".bak restauré" alert is acceptable)
result: [pending]

### 5. Feature freeze on 2026-11-11 per docs/FREEZE.md
expected: Lock reviewed and hashed, tag race-2026, wheelhouse from the tag, Pi re-provisioned; `bash scripts/freeze-check.sh` exit 0 (all PASS except F8 WARN and F9 HUMAN); only configuration changes afterwards
result: [pending]

### 6. Spare SD cloned per docs/SPARE-SD.md and booted (ROADMAP SC3)
expected: jabuka-core and jabuka-ingest-fastnet active, logcheck OK, fastnet-probe --file exits 0, FINGERPRINT_SH identical on both cards and equal to the Pi report's code.sha256, tablet opens http://10.42.0.1
result: [pending]

### 7. 12 Nov: replay of the boat's real Fastnet capture
expected: `bash scripts/commissioning-rehearsal.sh --steps R3.capture,R3.inventory,R3.archive,R3.replay,R3.logcheck --capture var/commissioning/capture-12nov/capture.log` gives 5 PASS lines; every decoded inventory path served by /api/state; logcheck OK
result: [pending]

### 8. On-board commissioning per docs/COMMISSIONING.md §2–§9 on 12–13 Nov (ROADMAP SC4)
expected: The helm tablet shows live wind (or MANUEL / GRIB) and laylines to the first mark over the boat Wi-Fi, readable at night
result: [pending]

### 9. Runbook timings and proofreading
expected: Owner reads docs/COMMISSIONING.md, docs/SOAK.md (Pi steps 6 and 8) and docs/FREEZE.md and adjusts 12 Nov timings; a Slovenian speaker proofreads docs/COMMISSIONING-SL.md and the SL "obnovljen iz varnostne kopije" strings
result: [pending]

## Summary

total: 9
passed: 0
issues: 0
pending: 9
skipped: 0
blocked: 0

## Gaps

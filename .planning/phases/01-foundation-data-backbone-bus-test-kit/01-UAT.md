---
status: testing
phase: 01-foundation-data-backbone-bus-test-kit
source: [01-VERIFICATION.md]
started: 2026-11-07T00:00:00Z
updated: 2026-11-07T00:00:00Z
---

## Current Test

number: 1
name: Provision the Pi from the wheelhouse (PI-SETUP §1–3)
expected: |
  Flash Raspberry Pi OS Lite 64-bit (Trixie), copy repo + deploy/wheelhouse (already built on the laptop),
  run `sudo deploy/provision.sh` over Ethernet. After a headless reboot both jabuka services are enabled and active.
awaiting: user response

## Tests

### 1. Provision the Pi (PI-SETUP §1–3)
expected: both services `active (running)` after headless reboot (`systemctl status jabuka-ingest-fastnet jabuka-core`)
result: [pending]

### 2. Tablet joins the AP
expected: SSID `jabuka`, mobile data off, http://10.42.0.1/ shows the diagnostics page with no internet
result: [pending]

### 3. Diagnostics page behaviour in a real browser
expected: rows show unit/source/age; rows go stale when the feed stops; "Event marker" acks and a line appears in var/logs/events/events-*.jsonl
result: [pending]

### 4. Serial device checks on the Pi
expected: `stty -F /dev/fastnet` → 28800 parenb parodd cs8 cstopb; device 0640 root:dialout; `lsof` shows only the ingest; `lsusb` shows 0403:6001 (DTECH) and 1546:01a7 (VK-162)
result: [pending]

### 5. fastnet-probe on hardware
expected: no bus connected → "NO BYTES", exit 2; at the boat (12 Nov) → OK, keep inventory.json + capture.log
result: [pending]

### 6. GPS time without internet
expected: `gpspipe -w` shows mode 3; `chronyc sources` shows `#* GPS`; `date -u` correct after reboot offline; diagnostics routing gate goes blocked → ok
result: [pending]

### 7. REL-01 on the Pi
expected: kill -9 of each service recovers; DTECH unplug/replug recovers without restart; 5 power pulls with `jabuka-logcheck` passing each time; hardware watchdog armed
result: [pending]

### 8. Lock review
expected: the 17 package names in deploy/requirements.lock are the expected canonical projects (fastapi, uvicorn, pyfastnet, pyserial, ...)
result: [pending]

## Summary

total: 8
passed: 0
issues: 0
pending: 8
skipped: 0

## Gaps

None yet — all automatable checks passed (295 tests). These items need the physical Pi / tablet / GPS / boat.

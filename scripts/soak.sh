#!/usr/bin/env bash
# Full soak run (plans 04-01, 04-03): the real Jabuka stack under SimClock with the seeded fault
# schedule, by default the 36 h-equivalent race-36h scenario (~36 min wall at 60x on the laptop;
# ~1.8 h at 20x, ~3.6 h at 10x on the Pi 3B). See docs/SOAK.md.
#
#   bash scripts/soak.sh [--scenario race-36h] [--speed X] [--python EXE] [--out var/soak]
#                        [--systemd user|system] [--logs-fs loop:512M] [--systemd-cleanup]
#                        [extra jabuka-soak args, e.g. --seed 7 --keep]
#
#   --python   interpreter that runs the harness and every child (default .venv313/bin/python, the
#              Pi's Python 3.13; on the Pi: --python /opt/jabuka/venv/bin/python)
#   --out      parent of the run dir; must be under var/ (same rule as racepack-dryrun.sh)
#   --systemd  user: transient user units (laptop, no sudo); system: the installed units through
#              volatile /run drop-ins (Pi, run with sudo; cleanup always restores them)
#   --systemd-cleanup  with --systemd system: repair an interrupted run (drop-ins, mounts), exit
#
# Prints the report path and the verdict; exits with the harness's code (0 PASS, 1 FAIL, 2 usage).
set -euo pipefail
cd "$(dirname "$0")/.."

SCENARIO="race-36h"
PY=".venv313/bin/python"
OUT="var/soak"
SYSTEMD=""
CLEANUP=0
EXTRA=()
while [ $# -gt 0 ]; do
    case "$1" in
        --scenario) SCENARIO="${2:?--scenario needs a value}"; shift 2 ;;
        --scenario=*) SCENARIO="${1#*=}"; shift ;;
        --python) PY="${2:?--python needs a value}"; shift 2 ;;
        --python=*) PY="${1#*=}"; shift ;;
        --out) OUT="${2:?--out needs a value}"; shift 2 ;;
        --out=*) OUT="${1#*=}"; shift ;;
        --systemd) SYSTEMD="${2:?--systemd needs user or system}"; shift 2 ;;
        --systemd=*) SYSTEMD="${1#*=}"; shift ;;
        --systemd-cleanup) CLEANUP=1; shift ;;
        -h|--help) sed -n '2,18p' "$0"; exit 0 ;;
        *) EXTRA+=("$1"); shift ;;
    esac
done

case "$SYSTEMD" in
    ""|user) ;;
    system)
        if [ "$(id -u)" -ne 0 ]; then
            echo "soak: --systemd system drives the installed units and needs root: sudo bash scripts/soak.sh --systemd system --python /opt/jabuka/venv/bin/python ..." >&2
            exit 2
        fi ;;
    *) echo "soak: --systemd must be user or system (got $SYSTEMD)" >&2; exit 2 ;;
esac
[ -x "$PY" ] || { echo "soak: $PY missing: run bash scripts/bootstrap-dev.sh" >&2; exit 2; }

if [ "$CLEANUP" -eq 1 ]; then
    [ "$SYSTEMD" = "system" ] || { echo "soak: --systemd-cleanup needs --systemd system" >&2; exit 2; }
    exec "$PY" -m jabuka.tools.soak --systemd system --systemd-cleanup
fi

case "$OUT" in
    var/*|var) ;;
    *) echo "soak: --out must be under var/ (got $OUT)" >&2; exit 2 ;;
esac
VAR_REAL="$(realpath -m var)"
OUT_REAL="$(realpath -m "$OUT")"
case "$OUT_REAL/" in
    "$VAR_REAL"/*) ;;
    *) echo "soak: --out must resolve under $VAR_REAL (got $OUT -> $OUT_REAL)" >&2; exit 2 ;;
esac
mkdir -p "$OUT"

ARGS=(--scenario "$SCENARIO" --out "$OUT")
[ -n "$SYSTEMD" ] && ARGS+=(--systemd "$SYSTEMD")
LOG="$(mktemp)"
trap 'rm -f "$LOG"' EXIT
set +e
"$PY" -m jabuka.tools.soak "${ARGS[@]}" ${EXTRA[@]+"${EXTRA[@]}"} 2>&1 | tee "$LOG"
RC=${PIPESTATUS[0]}
REPORT="$(grep -o 'jabuka-soak: report .*' "$LOG" | tail -1 | sed 's/^jabuka-soak: report //')"
VERDICT="$(grep -o 'jabuka-soak: verdict .*' "$LOG" | tail -1 | sed 's/^jabuka-soak: verdict //')"
set -e
if [ "$RC" -eq 2 ] && [ -z "$REPORT" ]; then
    exit 2  # usage / setup error: the harness already printed why
fi
echo "soak: scenario $SCENARIO, report ${REPORT:-none}, verdict ${VERDICT:-none} (exit $RC)"
exit "$RC"

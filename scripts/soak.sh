#!/usr/bin/env bash
# Full soak run (plan 04-01): the real Jabuka stack under SimClock with the seeded fault schedule,
# by default the 36 h-equivalent race-36h scenario (~36 min of simulated race per wall hour at 60x
# on the laptop; ~1.8 h at 20x, ~3.6 h at 10x on the Pi 3B). See docs/SOAK.md.
#
#   bash scripts/soak.sh [--scenario race-36h] [--speed X] [--python EXE] [--out var/soak]
#                        [extra jabuka-soak args, e.g. --seed 7 --keep]
#
#   --python   interpreter that runs the harness and every child (default .venv313/bin/python, the
#              Pi's Python 3.13; on the Pi: --python /opt/jabuka/venv/bin/python)
#   --out      parent of the run dir; must be under var/ (same rule as racepack-dryrun.sh)
#
# Prints the report path and the verdict; exits with the harness's code (0 PASS, 1 FAIL, 2 usage).
set -euo pipefail
cd "$(dirname "$0")/.."

SCENARIO="race-36h"
PY=".venv313/bin/python"
OUT="var/soak"
EXTRA=()
while [ $# -gt 0 ]; do
    case "$1" in
        --scenario) SCENARIO="${2:?--scenario needs a value}"; shift 2 ;;
        --scenario=*) SCENARIO="${1#*=}"; shift ;;
        --python) PY="${2:?--python needs a value}"; shift 2 ;;
        --python=*) PY="${1#*=}"; shift ;;
        --out) OUT="${2:?--out needs a value}"; shift 2 ;;
        --out=*) OUT="${1#*=}"; shift ;;
        -h|--help) sed -n '2,14p' "$0"; exit 0 ;;
        *) EXTRA+=("$1"); shift ;;
    esac
done

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
[ -x "$PY" ] || { echo "soak: $PY missing: run bash scripts/bootstrap-dev.sh" >&2; exit 2; }
mkdir -p "$OUT"

LOG="$(mktemp)"
trap 'rm -f "$LOG"' EXIT
set +e
"$PY" -m jabuka.tools.soak --scenario "$SCENARIO" --out "$OUT" ${EXTRA[@]+"${EXTRA[@]}"} 2>&1 | tee "$LOG"
RC=${PIPESTATUS[0]}
set -e
REPORT="$(grep -o 'jabuka-soak: report .*' "$LOG" | tail -1 | sed 's/^jabuka-soak: report //')"
VERDICT="$(grep -o 'jabuka-soak: verdict .*' "$LOG" | tail -1 | sed 's/^jabuka-soak: verdict //')"
echo "soak: scenario $SCENARIO, report ${REPORT:-none}, verdict ${VERDICT:-none} (exit $RC)"
exit "$RC"

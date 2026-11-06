#!/usr/bin/env bash
# Laptop dry run of the commissioning runbook (docs/COMMISSIONING.md, REL-03, plan 04-02).
#
#   bash scripts/commissioning-rehearsal.sh [--steps quick|all|ID,ID...] [--capture PATH]
#                                           [--out var/...] [--online] [--json]
#
# Runs every automatable runbook step ([Rn.x] tags) against a replayed Fastnet capture and the
# synthetic boat, and prints one line per step: PASS / FAIL / SKIP / HUMAN (needs the boat, the Pi
# or the tablet: the line gives the observation to make on board). Exit 0 when no step failed.
#
#   quick (default)  the gate's run, about 30 s: probes on files, §2-§4, §5 offline, §7 drill
#   all              the full rehearsal, about 4 min: live probe drills, route, degraded drills
#   --capture FILE   on 12 Nov: the boat's capture.log, to show it replays cleanly
#
#   PY=.venv/bin/python   interpreter of the dev venv (bash scripts/bootstrap-dev.sh)
# Writes only under var/ (default var/rehearsal/<UTC timestamp>).
set -euo pipefail
cd "$(dirname "$0")/.."

PY="${PY:-.venv/bin/python}"
[ -x "$PY" ] || { echo "commissioning-rehearsal: $PY missing: run bash scripts/bootstrap-dev.sh" >&2; exit 2; }

prev=""
for arg in "$@"; do
    out=""
    case "$arg" in
        --out=*) out="${arg#--out=}" ;;
        *) [ "$prev" = "--out" ] && out="$arg" ;;
    esac
    if [ -n "$out" ]; then
        case "$out" in
            var/*) ;;
            *) echo "commissioning-rehearsal: --out must be under var/ (got $out)" >&2; exit 2 ;;
        esac
    fi
    prev="$arg"
done

exec "$PY" -m jabuka.tools.rehearsal "$@"

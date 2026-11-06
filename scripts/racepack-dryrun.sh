#!/usr/bin/env bash
# Laptop end-to-end dry run of the race pack (plan 03-06, GRIB-01 + ROUT-01), with internet:
#   1. jabuka-prep wind   ICON-EU (DWD), window now + 3 h -> now + 27 h (local time), so the
#                         current DWD runs can cover it
#   2. jabuka-prep waves  EWAM (DWD), same window
#   3. jabuka-prep land   land mask from OSM (Overpass), reusing the prep cache when present
#   4. jabuka-prep geofields  with the shipped marks.json
#   5. jabuka-prep check  same loader and rules as the Pi
#   6. jabuka-route-bench --quick (L0, L1) on this pack -> OUT/bench.json
#   7. tests/routing/test_real_pack_e2e.py with JABUKA_REAL_PACK=OUT (Course A from Vodice, real
#      worker, polyline re-validated on the pack's own mask, instruments and GRIB-only)
# then prints a one-screen summary (run, coverage, recommended level, route ETA).
#
# Idempotent: re-running reuses the download cache (var/cache/prep) and overwrites OUT. Writes only
# under var/. Exits non-zero on the first failing step, with its name.
#
#   OUT=var/racepack-dryrun   pack directory (default; must be under var/)
#   PY=.venv/bin/python       interpreter of the dev venv (prep extra: pygrib, shapely)
#   JABUKA_DRYRUN_LANDMASK=DIR  only when Overpass is unreachable and the OSM cache is empty:
#       reuse landmask.npz + landmask.json from DIR (e.g. tests/fixtures/route/landmask_race_25m,
#       built from OSM on 2026-11-06). The summary says so; never a substitute on race day.
set -euo pipefail
cd "$(dirname "$0")/.."

OUT="${OUT:-var/racepack-dryrun}"
PY="${PY:-.venv/bin/python}"
BIN="$(dirname "$PY")"
CACHE="var/cache/prep"
MARKS="src/jabuka/nav/data/marks.json"
LOG="$OUT/dryrun.log"

case "$OUT" in
    var/*) ;;
    *) echo "racepack-dryrun: OUT must be under var/ (got $OUT)" >&2; exit 2 ;;
esac
# resolved too (03-REVIEW LO-07): var/../../tmp/x or a symlink out of var/ is refused
VAR_REAL="$(realpath -m var)"
OUT_REAL="$(realpath -m "$OUT")"
case "$OUT_REAL/" in
    "$VAR_REAL"/?*/) ;;
    *) echo "racepack-dryrun: OUT must resolve under $VAR_REAL (got $OUT -> $OUT_REAL)" >&2; exit 2 ;;
esac
for tool in "$PY" "$BIN/jabuka-prep" "$BIN/jabuka-route-bench"; do
    [ -x "$tool" ] || { echo "racepack-dryrun: $tool missing: run bash scripts/bootstrap-dev.sh" >&2; exit 2; }
done
mkdir -p "$OUT" "$CACHE"
: > "$LOG"

# window in local race time (Europe/Zagreb), as the prep tool expects
WSTART="$(TZ=Europe/Zagreb date -d '+3 hours' +%Y-%m-%dT%H:00)"
WEND="$(TZ=Europe/Zagreb date -d '+27 hours' +%Y-%m-%dT%H:00)"
WINDOW=(--window-start "$WSTART" --window-end "$WEND")
LAND_NOTE="OSM (Overpass ou cache $CACHE)"

T_ALL=$SECONDS
step() {
    local name="$1"
    shift
    local t=$SECONDS
    echo "== $name"
    if "$@" 2>&1 | tee -a "$LOG"; then
        echo "   $name : OK ($((SECONDS - t)) s)"
    else
        echo "racepack-dryrun: ÉCHEC à l'étape « $name » ($((SECONDS - t)) s), voir $LOG" >&2
        exit 1
    fi
}

net_check() {
    "$PY" - "$1" <<'PY'
import sys, urllib.request
try:
    urllib.request.urlopen(sys.argv[1], timeout=15).close()
except Exception as exc:  # noqa: BLE001
    sys.exit(f"injoignable : {sys.argv[1]} ({exc})")
PY
}

echo "racepack-dryrun: pack $OUT, fenêtre $WSTART -> $WEND (heure locale)"
step "réseau DWD" net_check "https://opendata.dwd.de/weather/nwp/icon-eu/grib/"
step "vent ICON-EU" "$BIN/jabuka-prep" wind --out "$OUT" --cache "$CACHE" "${WINDOW[@]}"
step "vagues EWAM" "$BIN/jabuka-prep" waves --out "$OUT" --cache "$CACHE" "${WINDOW[@]}"

land_build() {
    "$BIN/jabuka-prep" land build --out "$OUT" --cache "$CACHE"
}
t=$SECONDS
echo "== masque terre"
if land_build 2>&1 | tee -a "$LOG"; then
    echo "   masque terre : OK ($((SECONDS - t)) s)"
elif [ -n "${JABUKA_DRYRUN_LANDMASK:-}" ]; then
    src="${JABUKA_DRYRUN_LANDMASK%.npz}"
    if [ -d "$src" ]; then src="$src/landmask"; fi
    [ -f "$src.npz" ] && [ -f "$src.json" ] || {
        echo "racepack-dryrun: JABUKA_DRYRUN_LANDMASK : $src.npz/.json introuvables" >&2
        exit 1
    }
    cp "$src.npz" "$OUT/landmask.npz"
    cp "$src.json" "$OUT/landmask.json"
    LAND_NOTE="REPRIS de $src (Overpass injoignable, cache OSM vide)"
    echo "   masque terre : $LAND_NOTE ($((SECONDS - t)) s)"
else
    echo "racepack-dryrun: masque terre impossible : Overpass injoignable et pas de cache OSM" >&2
    echo "  dans $CACHE. Réessayer avec internet, ou (répétition seulement) :" >&2
    echo "  JABUKA_DRYRUN_LANDMASK=tests/fixtures/route/landmask_race_25m bash $0" >&2
    exit 1
fi

step "champs géo" "$BIN/jabuka-prep" geofields --marks "$MARKS" --out "$OUT"
step "contrôle du pack" "$BIN/jabuka-prep" check --out "$OUT" --cache "$CACHE" "${WINDOW[@]}"
step "banc de routage" "$BIN/jabuka-route-bench" --pack "$OUT" --quick --json "$OUT/bench.json"
step "routage de bout en bout" env JABUKA_REAL_PACK="$OUT" "$PY" -m pytest \
    tests/routing/test_real_pack_e2e.py -q -s -p no:cacheprovider

# -- summary ----------------------------------------------------------------------------------
"$PY" - "$OUT" "$LOG" "$LAND_NOTE" "$WSTART" "$WEND" "$((SECONDS - T_ALL))" <<'PY'
import json, re, sys
from pathlib import Path
out, log, land, ws, we, secs = Path(sys.argv[1]), Path(sys.argv[2]), *sys.argv[3:]
def sidecar(name):
    try:
        return json.loads((out / f"{name}.json").read_text())
    except (OSError, ValueError):
        return {}
wind, waves = sidecar("wind"), sidecar("waves")
cov = ""
try:
    lines = (out / "coverage.txt").read_text().splitlines()
    cov = next((l for l in lines if "COUVERTURE" in l or "INCOMPLÈTE" in l), lines[0] if lines else "")
except OSError:
    cov = "coverage.txt absent"
try:
    bench = json.loads((out / "bench.json").read_text())
except (OSError, ValueError):
    bench = {}
text = log.read_text()
etas = re.findall(r"real pack \(([^)]+)\): (.*)", text)
print()
print("=" * 72)
print(f"RÉPÉTITION PACK DE COURSE : {out}   ({secs} s)")
print(f"  fenêtre          : {ws} -> {we} (heure locale)")
print(f"  vent             : {wind.get('model', '?')} run {wind.get('run', '?')}, "
      f"{wind.get('t_first', '?')} -> {wind.get('t_last', '?')}")
print(f"  vagues           : {waves.get('model', '?')} run {waves.get('run', '?')}")
print(f"  masque terre     : {land}")
print(f"  couverture       : {cov.strip()}")
print(f"  niveau recommandé: {bench.get('recommended') or 'AUCUN'} (banc rapide, ce portable)")
for mode, line in etas:
    print(f"  route ({mode:11s}): {line}")
print("=" * 72)
PY

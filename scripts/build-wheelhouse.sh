#!/usr/bin/env bash
# Build the offline wheelhouse for the Pi (aarch64, CPython 3.13) into deploy/wheelhouse/.
#
#   bash scripts/build-wheelhouse.sh [--relock]
#
# --relock   re-resolve deploy/requirements.in into the hash-locked deploy/requirements.lock (and
#            deploy/fastnet2ip.in into deploy/fastnet2ip.lock, deploy/prep.in into deploy/prep.lock
#            constrained by requirements.lock) first. Without it, only a MISSING lock is created.
#
# Needs internet (pypi.org). The Pi then installs with --no-index --require-hashes only
# (deploy/provision.sh steps f, g and g2). deploy/wheelhouse/ is gitignored; copy it to the Pi with
# the repo. Plan B (fastnet2ip and its dependencies) goes to deploy/wheelhouse/fastnet2ip/, the Pi
# emergency weather prep (pygrib, shapely, netCDF4) to deploy/wheelhouse/prep/.
# `uv pip download` does not exist in uv 0.6.6 and uv venvs have no pip, so the download uses the
# system python3's pip (override with PYTHON=...).
set -euo pipefail
cd "$(dirname "$0")/.."

IN=deploy/requirements.in
LOCK=deploy/requirements.lock
WH=deploy/wheelhouse
F2I_IN=deploy/fastnet2ip.in
F2I_LOCK=deploy/fastnet2ip.lock
F2I_WH=deploy/wheelhouse/fastnet2ip
PREP_IN=deploy/prep.in
PREP_LOCK=deploy/prep.lock
PREP_WH=deploy/wheelhouse/prep
PY="${PYTHON:-python3}"
PI_PLATFORMS=(--implementation cp --python-version 3.13 --platform manylinux2014_aarch64
    --platform manylinux_2_17_aarch64 --platform manylinux_2_28_aarch64)

RELOCK=0
for arg in "$@"; do
    case "$arg" in
        --relock) RELOCK=1 ;;
        -h | --help)
            sed -n '2,15p' "$0" | sed 's/^# \{0,1\}//'
            exit 0
            ;;
        *)
            echo "build-wheelhouse: unknown argument: $arg" >&2
            exit 2
            ;;
    esac
done

lock() { # IN LOCK [EXTRA uv pip compile ARGS...]
    echo "build-wheelhouse: locking $1 -> $2 (aarch64, cp313, hashes)"
    uv pip compile "$1" "${@:3}" --python-platform aarch64-unknown-linux-gnu --python-version 3.13 \
        --generate-hashes -o "$2"
}
if [ "$RELOCK" -eq 1 ] || [ ! -f "$LOCK" ]; then lock "$IN" "$LOCK"; fi
if [ "$RELOCK" -eq 1 ] || [ ! -f "$F2I_LOCK" ]; then lock "$F2I_IN" "$F2I_LOCK"; fi
# after the app lock: the prep venv shares numpy & co. with the app, at the app's pinned versions
if [ "$RELOCK" -eq 1 ] || [ ! -f "$PREP_LOCK" ]; then lock "$PREP_IN" "$PREP_LOCK" -c "$LOCK"; fi

download() { # LOCK DIR
    mkdir -p "$2"
    echo "build-wheelhouse: downloading aarch64/cp313 wheels for $1 into $2"
    "$PY" -m pip download --only-binary=:all: --no-deps "${PI_PLATFORMS[@]}" \
        --require-hashes -r "$1" -d "$2"
}
download "$LOCK" "$WH"
download "$F2I_LOCK" "$F2I_WH"
download "$PREP_LOCK" "$PREP_WH"

echo "build-wheelhouse: building the jabuka wheel"
rm -f "$WH"/jabuka-*.whl
uv build --wheel --out-dir "$WH"

# Every package in the lock must have exactly one wheel (names normalised per PEP 503/427).
check_wheels() { # LOCK DIR JABUKA(0|1)
python3 - "$1" "$2" "$3" <<'PY'
import hashlib
import re
import sys
from pathlib import Path

lock, wh, want_jabuka = Path(sys.argv[1]), Path(sys.argv[2]), sys.argv[3] == "1"
norm = lambda s: re.sub(r"[-_.]+", "_", s).lower()  # noqa: E731
pins = {}
for line in lock.read_text().splitlines():
    m = re.match(r"^([A-Za-z0-9][A-Za-z0-9._-]*)==([^\s\\;]+)", line)
    if m:
        pins[norm(m.group(1))] = m.group(2)
wheels = sorted(wh.glob("*.whl"))
by_name = {}
for w in wheels:
    name, version = w.name.split("-")[:2]
    by_name.setdefault(norm(name), []).append((version, w))
bad = []
for name, version in sorted(pins.items()):
    found = by_name.get(name, [])
    if len(found) != 1 or found[0][0] != version:
        bad.append(f"{name}=={version}: found {[w.name for _, w in found]}")
extra = sorted(set(by_name) - set(pins) - ({"jabuka"} if want_jabuka else set()))
if extra:
    bad.append(f"wheels not in the lock: {extra}")
if want_jabuka and len(by_name.get("jabuka", [])) != 1:
    bad.append("expected exactly one jabuka-*.whl")
for w in wheels:
    print(f"{hashlib.sha256(w.read_bytes()).hexdigest()}  {w.name}")
if bad:
    print("build-wheelhouse: MISMATCH\n  " + "\n  ".join(bad), file=sys.stderr)
    sys.exit(1)
print(f"build-wheelhouse: {wh}: {len(pins)} locked packages, {len(wheels)} wheels")
PY
}
check_wheels "$LOCK" "$WH" 1
check_wheels "$F2I_LOCK" "$F2I_WH" 0
check_wheels "$PREP_LOCK" "$PREP_WH" 0

# Simulate the Pi's installs (provision.sh steps f, g and g2) offline, as aarch64/cp313: resolve only.
TARGET="$(mktemp -d)"
trap 'rm -rf "$TARGET"' EXIT
simulate() { # LOCK DIR
    echo "build-wheelhouse: simulating the offline --require-hashes install of $1"
    "$PY" -m pip install --dry-run --quiet --ignore-installed --no-index --find-links "$2" \
        --require-hashes -r "$1" --only-binary=:all: "${PI_PLATFORMS[@]}" --target "$TARGET"
}
simulate "$LOCK" "$WH"
simulate "$F2I_LOCK" "$F2I_WH"
simulate "$PREP_LOCK" "$PREP_WH"
# Step g2 installs the app lock then the prep lock into the same venv: prove the union resolves to
# one consistent set (shared packages are identical duplicates, which pip accepts).
echo "build-wheelhouse: simulating the prep venv (app lock + prep lock) offline --require-hashes install"
"$PY" -m pip install --dry-run --quiet --ignore-installed --no-index --find-links "$WH" \
    --find-links "$PREP_WH" --require-hashes -r "$LOCK" -r "$PREP_LOCK" --only-binary=:all: \
    "${PI_PLATFORMS[@]}" --target "$TARGET"
echo "build-wheelhouse: ok"

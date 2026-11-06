#!/usr/bin/env bash
# Build the offline wheelhouse for the Pi (aarch64, CPython 3.13) into deploy/wheelhouse/.
#
#   bash scripts/build-wheelhouse.sh [--relock]
#
# --relock   re-resolve deploy/requirements.in into the hash-locked deploy/requirements.lock first.
#
# Needs internet (pypi.org). The Pi then installs with --no-index --require-hashes only
# (deploy/provision.sh step f). deploy/wheelhouse/ is gitignored; copy it to the Pi with the repo.
# `uv pip download` does not exist in uv 0.6.6 and uv venvs have no pip, so the download uses the
# system python3's pip (override with PYTHON=...).
set -euo pipefail
cd "$(dirname "$0")/.."

IN=deploy/requirements.in
LOCK=deploy/requirements.lock
WH=deploy/wheelhouse
PY="${PYTHON:-python3}"

RELOCK=0
for arg in "$@"; do
    case "$arg" in
        --relock) RELOCK=1 ;;
        -h | --help)
            sed -n '2,12p' "$0" | sed 's/^# \{0,1\}//'
            exit 0
            ;;
        *)
            echo "build-wheelhouse: unknown argument: $arg" >&2
            exit 2
            ;;
    esac
done

if [ "$RELOCK" -eq 1 ] || [ ! -f "$LOCK" ]; then
    echo "build-wheelhouse: locking $IN -> $LOCK (aarch64, cp313, hashes)"
    uv pip compile "$IN" --python-platform aarch64-unknown-linux-gnu --python-version 3.13 \
        --generate-hashes -o "$LOCK"
fi

mkdir -p "$WH"
echo "build-wheelhouse: downloading aarch64/cp313 wheels into $WH"
"$PY" -m pip download --only-binary=:all: --no-deps --implementation cp --python-version 3.13 \
    --platform manylinux2014_aarch64 --platform manylinux_2_17_aarch64 \
    --platform manylinux_2_28_aarch64 \
    --require-hashes -r "$LOCK" -d "$WH"

echo "build-wheelhouse: building the jabuka wheel"
rm -f "$WH"/jabuka-*.whl
uv build --wheel --out-dir "$WH"

# Every package in the lock must have exactly one wheel (names normalised per PEP 503/427).
python3 - "$LOCK" "$WH" <<'PY'
import hashlib
import re
import sys
from pathlib import Path

lock, wh = Path(sys.argv[1]), Path(sys.argv[2])
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
extra = sorted(set(by_name) - set(pins) - {"jabuka"})
if extra:
    bad.append(f"wheels not in the lock: {extra}")
if len(by_name.get("jabuka", [])) != 1:
    bad.append("expected exactly one jabuka-*.whl")
for w in wheels:
    print(f"{hashlib.sha256(w.read_bytes()).hexdigest()}  {w.name}")
if bad:
    print("build-wheelhouse: MISMATCH\n  " + "\n  ".join(bad), file=sys.stderr)
    sys.exit(1)
print(f"build-wheelhouse: {len(pins)} locked packages + jabuka, {len(wheels)} wheels")
PY

# Simulate the Pi's install (provision.sh step f) offline, as aarch64/cp313: resolve only.
echo "build-wheelhouse: simulating the offline --require-hashes install for aarch64/cp313"
TARGET="$(mktemp -d)"
trap 'rm -rf "$TARGET"' EXIT
"$PY" -m pip install --dry-run --quiet --ignore-installed --no-index --find-links "$WH" \
    --require-hashes -r "$LOCK" --only-binary=:all: --implementation cp --python-version 3.13 \
    --platform manylinux2014_aarch64 --platform manylinux_2_17_aarch64 \
    --platform manylinux_2_28_aarch64 --target "$TARGET"
echo "build-wheelhouse: ok"

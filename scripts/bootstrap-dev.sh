#!/usr/bin/env bash
# Idempotent dev bootstrap: creates .venv (Python 3.14) and .venv313 (/usr/bin/python3.13)
# and installs this checkout editable with the dev and prep extras into both (prep = osmium, pygrib,
# shapely, netCDF4: laptop race-pack tooling; skipped with a warning where no wheel exists, then
# pygrib + shapely alone are tried so the race-pack tests still run; netCDF4 stays optional).
# Safe in git worktrees: an existing venv is only reused when jabuka resolves inside THIS src/.
set -euo pipefail
cd "$(dirname "$0")/.."
ROOT="$(pwd)"

ensure_venv() {
    local venv="$1" python_spec="$2"
    if [ ! -x "$venv/bin/python" ]; then
        echo "bootstrap: creating $venv ($python_spec)"
        uv venv -p "$python_spec" "$venv"
    fi
    if "$venv/bin/python" - "$ROOT/src" <<'PY' >/dev/null 2>&1
import os, sys
import fastapi, fastnet_decoder, numpy, pmtiles, playwright, pygrib, pytest, shapely  # noqa: F401
import jabuka
src = os.path.realpath(sys.argv[1])
ok = os.path.realpath(jabuka.__file__).startswith(src + os.sep)
sys.exit(0 if ok else 1)
PY
    then
        echo "bootstrap: $venv already up to date"
    else
        echo "bootstrap: installing jabuka[dev,prep] into $venv"
        if ! uv pip install --python "$venv/bin/python" -e ".[dev,prep]"; then
            echo "bootstrap: WARNING: prep extra not installable here, installing [dev] + pygrib/shapely"
            uv pip install --python "$venv/bin/python" -e ".[dev]"
            uv pip install --python "$venv/bin/python" "pygrib==2.1.8" "shapely==2.2.0" ||
                echo "bootstrap: WARNING: pygrib/shapely not installable: race-pack tests will skip"
        fi
    fi
}

ensure_venv .venv 3.14
ensure_venv .venv313 /usr/bin/python3.13
echo "bootstrap: ok"

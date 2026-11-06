#!/usr/bin/env bash
# Local demo: jabuka-core + synthetic boat + ingest on this computer, open the printed URL in a
# browser (default http://127.0.0.1:8080/). Options are passed through to jabuka.tools.demo:
#   --port N   --speed X   --shift DEG_PER_H   --lan   --out DIR   --map DIR
# Data under var/demo/ (wiped on every start). Ctrl-C stops everything.
set -euo pipefail
cd "$(dirname "$0")/.."
PY=.venv/bin/python
if [ ! -x "$PY" ]; then
    echo "demo: .venv absent, lancer d'abord : bash scripts/bootstrap-dev.sh" >&2
    exit 1
fi
exec "$PY" -m jabuka.tools.demo "$@"

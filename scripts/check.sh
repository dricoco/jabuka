#!/usr/bin/env bash
# Full local gate: bootstrap, ruff lint + format check, test suite on Python 3.14 and 3.13.
set -euo pipefail
cd "$(dirname "$0")/.."
bash scripts/bootstrap-dev.sh
.venv/bin/ruff check src tests
.venv/bin/ruff format --check src tests
.venv/bin/python -m pytest -q
.venv313/bin/python -m pytest -q
echo "check: ok"

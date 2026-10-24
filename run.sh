#!/usr/bin/env bash
# Population -> shared data -> simulator results -> dashboard on http://127.0.0.1:8765/
set -euo pipefail
cd "$(dirname "$0")"
[ -x .venv/bin/python ] || { python3 -m venv .venv && .venv/bin/python -m pip install -q -r data/requirements.txt; }
if [ -f data/raw/archives/Census2022HouseholdExcelDataset.7z ]; then
  .venv/bin/python generation/run.py               # synthetic population (Census 2022 + HIES 2019, seed 42)
else
  echo "Census archives not in data/raw/archives/: using the committed population (data/processed/population/)"
fi
.venv/bin/python data/build.py                     # facilities and shared database
uv sync -q
uv run python -m simulator.export_dashboard        # model results for the dashboard
exec uv run python -m simulator.server ${PORT:+--port $PORT}             # engine API + dashboard

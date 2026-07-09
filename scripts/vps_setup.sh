#!/usr/bin/env bash
set -euo pipefail

PROJECT_DIR="${1:-/opt/polymarket-weather-edge}"

python3 -m venv "$PROJECT_DIR/.venv"
"$PROJECT_DIR/.venv/bin/pip" install -r "$PROJECT_DIR/requirements.txt"
"$PROJECT_DIR/.venv/bin/python" -m unittest discover -s "$PROJECT_DIR/tests" -v
"$PROJECT_DIR/.venv/bin/python" -m weather_edge.cli backtest \
  --file "$PROJECT_DIR/data/sample_backtest.json" \
  --config "$PROJECT_DIR/config/risk.example.json"

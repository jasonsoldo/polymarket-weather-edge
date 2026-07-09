#!/usr/bin/env bash
set -euo pipefail

PROJECT_DIR="${1:-/opt/polymarket-weather-edge}"

python3 -m venv "$PROJECT_DIR/.venv"
"$PROJECT_DIR/.venv/bin/pip" install -r "$PROJECT_DIR/requirements.txt"
"$PROJECT_DIR/.venv/bin/python" -m unittest discover -s "$PROJECT_DIR/tests" -v
"$PROJECT_DIR/.venv/bin/python" -m weather_edge.cli backtest \
  --file "$PROJECT_DIR/data/sample_backtest.json" \
  --config "$PROJECT_DIR/config/risk.example.json"

if command -v cmake >/dev/null 2>&1; then
  cmake -S "$PROJECT_DIR/cpp/pnl_curve_engine" -B "$PROJECT_DIR/build/pnl_curve_engine"
  cmake --build "$PROJECT_DIR/build/pnl_curve_engine"
  "$PROJECT_DIR/build/pnl_curve_engine/pnl_curve_engine" "$PROJECT_DIR/data/sample_buckets.csv"
fi

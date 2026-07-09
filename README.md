# Polymarket Weather Edge

Polymarket Weather Market analysis and simulation toolkit.

This project is not a risk-free arbitrage bot. It is a weather data model,
market mispricing detector, multi-bucket PnL curve calculator, and risk-gated
simulation/backtest runner.

## Current Scope

- Multi-bucket PnL curve
- Model probability vs market price edge
- Death gap detection
- Pre-trade risk checks
- Simulation mode
- JSON-file backtest mode
- SQLite analysis log
- VPS-friendly Python CLI
- C++ PnL curve engine source for performance-sensitive calculation
- Read-only live Polymarket market discovery
- Read-only Open-Meteo and NWS forecast snapshots
- Settlement rule parsing for source, unit, station/grid, timezone, and bucket bounds
- Bucket probability curve from live forecasts

No live Polymarket order is sent by the current code.

## Quick Start

```powershell
python -m unittest discover -s tests -v
python -m weather_edge.cli analyze --plan data/sample_plan.json --config config/risk.example.json
python -m weather_edge.cli simulate --plan data/sample_plan.json --winning-bucket 88F --config config/risk.example.json
python -m weather_edge.cli backtest --file data/sample_backtest.json --config config/risk.example.json
```

Read-only live data smoke tests:

```powershell
python -m weather_edge.cli live-tags
python -m weather_edge.cli live-markets --limit 20 --pages 5
python -m weather_edge.cli live-weather --city "New York" --lat 40.7128 --lon -74.0060 --date 2026-07-10
python -m weather_edge.cli live-monitor --city "New York" --lat 40.7128 --lon -74.0060 --date 2026-07-10 --limit 20 --pages 5
python -m weather_edge.cli live-monitor-loop --city "New York" --lat 40.7128 --lon -74.0060 --date 2026-07-10 --output logs/live_monitor.jsonl --interval 300 --limit 20 --pages 2 --max-runs 1
```

If you already know a Polymarket event or market slug, prefer slug lookup:

```powershell
python -m weather_edge.cli live-markets --slug POLYMARKET_EVENT_OR_MARKET_SLUG
```

`live-markets` follows the current Polymarket docs: it uses Gamma keyset
pagination where possible, caps page size at 100, and can filter by tag, slug,
city, or query text. Current live data commands are read-only and do not create
orders.

Optional C++ PnL engine build on a machine with CMake:

```bash
cmake -S cpp/pnl_curve_engine -B build/pnl_curve_engine
cmake --build build/pnl_curve_engine
./build/pnl_curve_engine/pnl_curve_engine data/sample_buckets.csv
```

Optional SQLite log:

```powershell
python -m weather_edge.cli init-db --db data/weather_edge.sqlite
python -m weather_edge.cli analyze --plan data/sample_plan.json --config config/risk.example.json --db data/weather_edge.sqlite
```

## Strategy Structure

Weather markets are multi-bucket mutually exclusive markets. A position can be:

- `main_only`: one bucket only
- `multi_bucket_dutching_with_tail_or_neighbor_protection`: main bucket plus neighbor/tail protection
- `full_coverage`: all listed buckets have shares

Full coverage is not automatically arbitrage. It is only near-arbitrage when:

```text
sum(all_bucket_prices) < 1 - safety_margin
```

## Formula

```text
bucket_cost_i = bucket_price_i * bucket_shares_i
total_cost = sum(bucket_cost_i)
PnL_if_bucket_i_wins = bucket_shares_i - total_cost
edge_i = model_probability_i - bucket_price_i
```

Every analysis returns bucket-level:

```text
Bucket | Price | Shares | Cost | Model Probability | Edge | PnL if wins
```

## Death Gap

A death gap is an uncovered bucket with meaningful model probability:

```text
shares_i == 0 and model_probability_i > max_uncovered_probability
```

The risk manager blocks new positions when a death gap is detected.

## Repository Layout

```text
weather_edge/
  pnl_curve.py      Bucket-level PnL curve and death gap detection
  risk_manager.py   Pre-trade risk checks
  simulator.py      Dry settlement simulation
  backtest.py       JSON scenario backtest runner
  storage.py        SQLite analysis log
  cli.py            Command line entrypoint
  market_scanner.py Read-only Gamma event/market discovery
  orderbook.py      Read-only CLOB /book summary
  settlement_rules.py Parse market rule text and bucket bounds
  bucket_probability.py Convert forecasts into bucket probabilities
  weather_sources.py Open-Meteo and NWS forecast snapshots
  monitor.py        Combined read-only market + weather snapshot
cpp/
  pnl_curve_engine/ C++ bucket PnL calculator; no order execution
data/
  sample_plan.json
  sample_backtest.json
  sample_buckets.csv
config/
  risk.example.json
docs/
  deploy_vps.md
scripts/
  vps_setup.sh
```

## GitHub Upload

After creating a GitHub repository, run:

```powershell
git init
git add .
git commit -m "Initial weather edge simulation project"
git branch -M main
git remote add origin https://github.com/YOUR_USER/YOUR_REPO.git
git push -u origin main
```

If using GitHub CLI:

```powershell
gh repo create YOUR_USER/YOUR_REPO --private --source . --remote origin --push
```

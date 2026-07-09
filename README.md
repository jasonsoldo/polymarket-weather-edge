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

No live Polymarket order is sent by the current code.

## Quick Start

```powershell
python -m unittest discover -s tests -v
python -m weather_edge.cli analyze --plan data/sample_plan.json --config config/risk.example.json
python -m weather_edge.cli simulate --plan data/sample_plan.json --winning-bucket 88F --config config/risk.example.json
python -m weather_edge.cli backtest --file data/sample_backtest.json --config config/risk.example.json
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
data/
  sample_plan.json
  sample_backtest.json
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

# Official Sources and Validation

WeatherEdge never substitutes a weather provider for the source named in a
Polymarket settlement rule.

## Environment-backed adapters

The configured adapters use strict `date` and `station` checks. Configure only
the source named by the market rule:

```bash
export JMA_API_KEY='...'
export JMA_SETTLEMENT_URL='https://official.example/{station}/{date}'
export KMA_API_KEY='...'
export KMA_SETTLEMENT_URL='https://official.example/{station}/{date}'
export CWA_API_KEY='...'
export CWA_SETTLEMENT_URL='https://official.example/{station}/{date}'
export METOFFICE_API_KEY='...'
export METOFFICE_SETTLEMENT_URL='https://official.example/{station}/{date}'
```

The endpoint must return machine-readable daily high/low data and identify the
requested date and station. Missing credentials, a wrong date, a wrong station,
or missing values remain blocked.

## Historical validation

Create one JSONL row per station/date with the raw source comparisons, then run:

```bash
python -m weather_edge.cli validate-history \
  --file data/validation/hko.jsonl \
  --min-days 30 \
  --min-exact-match-rate 0.90 \
  --max-missing-rate 0.10
```

The result is not `verified` until the minimum number of days, exact-match,
missing-data, and (when supplied) resolved-bucket thresholds pass.

## Resolution backfill

The backfill keeps the original market row and adds the final outcome from an
audited resolution export:

```bash
python -m weather_edge.cli settlement-backfill \
  --input data/market_history.jsonl \
  --resolutions data/polymarket_resolutions.jsonl \
  --output data/market_history_backfilled.jsonl
```

## Accounting

Live reconciliation now records every newly observed fill in the orders SQLite
database. Sell fills calculate realized PnL against the position average price;
the portfolio combines realized and current bid-marked unrealized PnL.

Weather Underground and retired/unavailable provider APIs stay `monitor_only`
until their own source validation passes.

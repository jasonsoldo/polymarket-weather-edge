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

For Hong Kong, create day-level Polymarket settlement comparisons from the
official HKO observations. A day is comparable only when every discovered,
closed temperature bucket has a final outcome and agrees with the HKO value:

```bash
python -m weather_edge.cli hko-backfill-polymarket \
  --input data/validation/hko.jsonl \
  --output data/validation/hko_polymarket.jsonl

python -m weather_edge.cli validate-history \
  --file data/validation/hko_polymarket.jsonl
```

Missing historical Polymarket events remain explicit missing records and never
count as a match.

## Persistent market data and calibration

`live-monitor-loop` and `live-monitor-all` already write to
`data/market_history.sqlite`. Each snapshot now also records normalized forecast,
market, bucket-curve, and settlement rows. Add HKO finalized records to that same
database when collecting history:

```bash
python -m weather_edge.cli hko-collect-history \
  --start-date 2025-06-01 --end-date 2025-06-30 \
  --output data/validation/hko.jsonl \
  --history-db data/market_history.sqlite

# Import an existing JSONL file without collecting or appending it again.
python -m weather_edge.cli hko-import-history \
  --input data/validation/hko.jsonl \
  --history-db data/market_history.sqlite

python -m weather_edge.cli history-summary --db data/market_history.sqlite
python -m weather_edge.cli calibration-summary --db data/market_history.sqlite
```

The calibration report is observational only. It reports source-level high/low
bias and mean absolute error after official settlement; it does not modify live
probabilities until enough audited samples exist.

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

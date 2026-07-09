# VPS Deployment

The default deployment is dry-run and read-only. Adding a private key does not
enable live trading unless the explicit live config and environment switch are
both enabled.

## Ubuntu Setup

```bash
sudo apt-get update
sudo apt-get install -y git python3 python3-venv build-essential cmake
git clone https://github.com/YOUR_USER/YOUR_REPO.git
cd YOUR_REPO
python3 -m venv .venv
. .venv/bin/activate
pip install -r requirements.txt
python -m unittest discover -s tests -v
python -m weather_edge.cli backtest --file data/sample_backtest.json --config config/risk.example.json
python -m weather_edge.cli live-weather --city "New York" --lat 40.7128 --lon -74.0060 --date 2026-07-10
python -m weather_edge.cli live-markets --limit 20 --pages 5
python -m weather_edge.cli live-dry-run --city "New York" --lat 40.7128 --lon -74.0060 --date 2026-07-10 --strategy-config config/strategy.example.json --risk-config config/risk.example.json --limit 20 --pages 2
cmake -S cpp/pnl_curve_engine -B build/pnl_curve_engine
cmake --build build/pnl_curve_engine
./build/pnl_curve_engine/pnl_curve_engine data/sample_buckets.csv
```

## Keep a Read-Only Monitor Running

For a simple first VPS monitor test:

```bash
python -m weather_edge.cli live-monitor-loop \
  --city "New York" \
  --lat 40.7128 \
  --lon -74.0060 \
  --date 2026-07-10 \
  --output logs/live_monitor.jsonl \
  --interval 300 \
  --limit 20 \
  --pages 2
```

This command is read-only. It does not create orders.

## Real Data Dry-Run

Use this before any live trading switch:

```bash
python -m weather_edge.cli live-dry-run \
  --city "New York" \
  --lat 40.7128 \
  --lon -74.0060 \
  --date 2026-07-10 \
  --strategy-config config/strategy.example.json \
  --risk-config config/risk.example.json \
  --orders-db data/orders.sqlite \
  --positions-db data/positions.sqlite \
  --limit 20 \
  --pages 2
```

This uses real Polymarket market discovery, real CLOB orderbooks, and real
Open-Meteo/NWS weather, but it records simulated orders only.

Supplying `POLYMARKET_PRIVATE_KEY` is not enough to trade. Live mode requires:

```bash
export POLYMARKET_PRIVATE_KEY="..."
export LIVE_TRADING_ENABLED=true
pip install py-clob-client
python -m weather_edge.cli live-dry-run \
  --city "New York" \
  --lat 40.7128 \
  --lon -74.0060 \
  --date 2026-07-10 \
  --strategy-config config/strategy.live.example.json \
  --risk-config config/risk.example.json
```

Live mode still passes through `risk_manager`, `pnl_curve`, duplicate order
guard, and persistent order logging.

## systemd Example

Create `/etc/systemd/system/weather-edge-monitor.service`:

```ini
[Unit]
Description=Weather Edge read-only monitor
After=network-online.target

[Service]
Type=simple
WorkingDirectory=/opt/polymarket-weather-edge
ExecStart=/opt/polymarket-weather-edge/.venv/bin/python -m weather_edge.cli live-monitor-loop --city "New York" --lat 40.7128 --lon -74.0060 --date 2026-07-10 --output logs/live_monitor.jsonl --interval 300 --limit 20 --pages 2
Restart=on-failure
RestartSec=30

[Install]
WantedBy=multi-user.target
```

Then:

```bash
sudo systemctl daemon-reload
sudo systemctl enable weather-edge-monitor
sudo systemctl start weather-edge-monitor
sudo systemctl status weather-edge-monitor
tail -f /opt/polymarket-weather-edge/logs/live_monitor.jsonl
```

## Required Before Live Trading

- Historical data collection for serious backtests
- Stronger weather probability model
- Real partial fill reconciliation from CLOB order status
- Alerting for data disagreement, death gaps, and stale orderbooks

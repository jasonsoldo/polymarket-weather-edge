# VPS Deployment

The current deployment is simulation/backtest only. Do not add live keys until
the market scanner, position manager, and trade executor are implemented and
tested.

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

- Polymarket market scanner
- Weather data source adapters
- Settlement rule parser for market descriptions and official source fields
- Bucket probability model
- Orderbook freshness checks from live data
- Position manager
- Duplicate order guard with persistent client order ids
- Partial fill handling
- Slippage limits
- Dry-run to live switch protected by explicit config

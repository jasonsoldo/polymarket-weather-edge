# VPS Deployment

The current deployment is simulation/backtest only. Do not add live keys until
the market scanner, position manager, and trade executor are implemented and
tested.

## Ubuntu Setup

```bash
sudo apt-get update
sudo apt-get install -y git python3 python3-venv
git clone https://github.com/YOUR_USER/YOUR_REPO.git
cd YOUR_REPO
python3 -m venv .venv
. .venv/bin/activate
pip install -r requirements.txt
python -m unittest discover -s tests -v
python -m weather_edge.cli backtest --file data/sample_backtest.json --config config/risk.example.json
```

## Keep a Simulation Process Running

For a simple first VPS smoke test:

```bash
while true; do
  date
  python -m weather_edge.cli backtest --file data/sample_backtest.json --config config/risk.example.json
  sleep 300
done
```

For production-like operation, use a systemd service after replacing the sample
input files with generated market snapshots.

## systemd Example

Create `/etc/systemd/system/weather-edge-sim.service`:

```ini
[Unit]
Description=Weather Edge simulation loop
After=network-online.target

[Service]
Type=simple
WorkingDirectory=/opt/polymarket-weather-edge
ExecStart=/opt/polymarket-weather-edge/.venv/bin/python -m weather_edge.cli backtest --file data/sample_backtest.json --config config/risk.example.json
Restart=on-failure
RestartSec=30

[Install]
WantedBy=multi-user.target
```

Then:

```bash
sudo systemctl daemon-reload
sudo systemctl enable weather-edge-sim
sudo systemctl start weather-edge-sim
sudo systemctl status weather-edge-sim
```

## Required Before Live Trading

- Polymarket market scanner
- Weather data source adapters
- Bucket probability model
- Orderbook freshness checks from live data
- Position manager
- Duplicate order guard with persistent client order ids
- Partial fill handling
- Slippage limits
- Dry-run to live switch protected by explicit config

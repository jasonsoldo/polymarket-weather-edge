import json
import os
import subprocess
import time
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
PYTHON = str(ROOT / ".venv" / "bin" / "python")
INTERVAL = int(os.getenv("WU_SCAN_INTERVAL", "3600"))
MARKETS_FILE = ROOT / "data" / "live_markets.json"


def run(command):
    return subprocess.run(command, cwd=ROOT, check=False).returncode


def main():
    while True:
        with MARKETS_FILE.open("w", encoding="utf-8") as handle:
            scan_code = subprocess.run([PYTHON, "-m", "weather_edge.cli", "live-markets", "--limit", "100", "--max-pages", "20", "--scan-all-pages"], cwd=ROOT, stdout=handle, check=False).returncode
        if scan_code == 0:
            run([PYTHON, "-m", "weather_edge.cli", "wunderground-collect-discovered", "--markets-file", str(MARKETS_FILE), "--unit", "C", "--output", str(ROOT / "data" / "wunderground_discovered.jsonl"), "--artifact-dir", str(ROOT / "data" / "wunderground_artifacts"), "--interval", "15"])
        time.sleep(INTERVAL)


if __name__ == "__main__":
    main()

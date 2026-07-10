"""Batch collection for Wunderground markets discovered from Polymarket."""
import json
import re
import time
from datetime import datetime
from pathlib import Path

from .settlement_sources.wunderground_browser import fetch_wunderground_browser


def discovered_wu_targets(payload):
    targets = {}
    for market in payload.get("markets", []):
        source = str(market.get("resolution_source", "") or market.get("description", ""))
        if "wunderground.com" not in source.lower() and "weather underground" not in source.lower():
            continue
        station = str(market.get("station_code", "") or market.get("target_station_or_data_source", "")).upper()
        if not station:
            station_match = re.search(r"/([A-Z0-9]{4})(?:[/?#.]|$)", source.upper())
            station = station_match.group(1) if station_match else ""
        target_date = str(market.get("target_date", "") or market.get("date", ""))[:10]
        if not re.fullmatch(r"\d{4}-\d{2}-\d{2}", target_date):
            match = re.search(r"\b(20\d{2}-\d{2}-\d{2})\b", " ".join(str(market.get(key, "")) for key in ("event_slug", "market_slug", "question", "description")))
            target_date = match.group(1) if match else ""
        if not target_date:
            text = " ".join(str(market.get(key, "")) for key in ("event_slug", "market_slug", "question", "description"))
            match = re.search(r"(\d{1,2})\s+([A-Za-z]{3})\s+'?(\d{2,4})", text)
            if match:
                year = int(match.group(3))
                year += 2000 if year < 100 else 0
                target_date = datetime.strptime(f"{match.group(1)} {match.group(2)} {year}", "%d %b %Y").date().isoformat()
        url = market.get("resolution_source", "")
        if "http" not in url:
            match = re.search(r"https?://[^\s)]+wunderground\.com[^\s)]*", source, re.I)
            url = match.group(0) if match else ""
        if not station or not target_date or "http" not in url:
            continue
        targets[(station, target_date, url)] = {"station": station, "date": target_date, "url": url, "city": market.get("city_guess", "")}
    return list(targets.values())


def collect_discovered_markets(markets_file, output, artifact_dir, unit="C", interval=15.0):
    payload = json.loads(Path(markets_file).read_text(encoding="utf-8"))
    targets = discovered_wu_targets(payload)
    target_path = Path(output)
    target_path.parent.mkdir(parents=True, exist_ok=True)
    rows = []
    existing = {}
    if target_path.exists():
        for line in target_path.read_text(encoding="utf-8").splitlines():
            try:
                row = json.loads(line)
                existing[_target_key(row)] = row
            except json.JSONDecodeError:
                continue
    for index, target in enumerate(targets):
            result = fetch_wunderground_browser(target["url"], target["station"], target["date"], unit, artifact_dir)
            row = {**target, **result.to_dict()}
            existing[_target_key(row)] = row
            rows.append(row)
            if result.status in {"wu_unavailable", "wu_source_mismatch"} and any(code in result.reason for code in ("403", "429", "CAPTCHA")):
                break
            if index + 1 < len(targets):
                time.sleep(max(0.0, interval))
    target_path.write_text("".join(json.dumps(row, sort_keys=True) + "\n" for row in existing.values()), encoding="utf-8")
    return rows


def _target_key(row):
    return (row.get("station", ""), row.get("date", ""), row.get("url", "") or row.get("source_url", ""))

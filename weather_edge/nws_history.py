"""Collect finalized NWS station temperature extremes by local calendar day."""

import json
import time
from datetime import date, timedelta
from pathlib import Path

from .history_store import save_settlement_observation
from .settlement_rules import SettlementRule
from .settlement_source import fetch_settlement_observation


def collect_nws_history(start_date: str, end_date: str, output: str, city: str = "New York", station: str = "KNYC", timezone: str = "America/New_York", unit: str = "F", interval: float = 0.2, history_db: str = "") -> dict:
    start, end = date.fromisoformat(start_date), date.fromisoformat(end_date)
    if end < start:
        raise ValueError("end date must not be earlier than start date")
    target = Path(output)
    target.parent.mkdir(parents=True, exist_ok=True)
    collected = failed = 0
    with target.open("a", encoding="utf-8") as handle:
        current = start
        while current <= end:
            day = current.isoformat()
            rule = SettlementRule(city, day, "max_temp", "NWS", unit, timezone, station, "nearest_integer", 1.0, (), ())
            result = fetch_settlement_observation(rule)
            row = {"date": day, "city": city, "station": result.station, "api_high": result.max_temp, "api_low": result.min_temp, "unit": result.unit, "observed_at": result.observed_at, "status": result.status, "source": "NWS station observations", "source_reason": result.reason}
            handle.write(json.dumps(row, sort_keys=True) + "\n")
            handle.flush()
            if history_db:
                save_settlement_observation(history_db, city, day, result.to_dict(), result.observed_at)
            if result.status == "available":
                collected += 1
            else:
                failed += 1
            current += timedelta(days=1)
            if current <= end:
                time.sleep(max(0.0, interval))
    return {"start_date": start_date, "end_date": end_date, "city": city, "station": station, "timezone": timezone, "unit": unit, "output": output, "days": collected + failed, "collected": collected, "failed": failed}

"""Collect finalized Hong Kong Observatory daily extremes."""

import json
import time
from datetime import date, timedelta
from pathlib import Path

from .history_store import save_settlement_observation
from .settlement_source import fetch_settlement_observation
from .settlement_rules import SettlementRule


def collect_hko_history(start_date: str, end_date: str, output: str, interval: float = 0.2, history_db: str = "") -> dict:
    start = date.fromisoformat(start_date)
    end = date.fromisoformat(end_date)
    if end < start:
        raise ValueError("end date must not be earlier than start date")
    target = Path(output)
    target.parent.mkdir(parents=True, exist_ok=True)
    collected = failed = 0
    with target.open("a", encoding="utf-8") as handle:
        current = start
        while current <= end:
            day = current.isoformat()
            rule = SettlementRule("Hong Kong", day, "temperature", "Hong Kong Observatory", "C", "Asia/Hong_Kong", "HKO", "nearest_tenth", 1.0, (), ())
            result = fetch_settlement_observation(rule)
            row = {
                "date": day,
                "station": result.station,
                "api_high": result.max_temp,
                "api_low": result.min_temp,
                "unit": result.unit,
                "observed_at": result.observed_at,
                "status": result.status,
                "source": "HKO Daily Extract",
                "source_reason": result.reason,
            }
            handle.write(json.dumps(row, sort_keys=True) + "\n")
            handle.flush()
            if history_db:
                save_settlement_observation(history_db, "Hong Kong", day, result.to_dict(), result.observed_at)
            if result.status == "available":
                collected += 1
            else:
                failed += 1
            current += timedelta(days=1)
            if current <= end:
                time.sleep(max(0.0, interval))
    return {"start_date": start_date, "end_date": end_date, "output": output, "days": collected + failed, "collected": collected, "failed": failed}


def import_hko_history(input_path: str, history_db: str) -> dict:
    source = Path(input_path)
    rows = [json.loads(line) for line in source.read_text(encoding="utf-8").splitlines() if line.strip()] if source.exists() else []
    for row in rows:
        observation = {
            "source": row.get("source", "Hong Kong Observatory"),
            "station": row.get("station", "HKO"),
            "max_temp": row.get("api_high"),
            "min_temp": row.get("api_low"),
            "unit": row.get("unit", "C"),
            "status": row.get("status", ""),
            "reason": row.get("source_reason", ""),
        }
        save_settlement_observation(history_db, "Hong Kong", row.get("date", ""), observation, row.get("observed_at", ""))
    return {"input": input_path, "history_db": history_db, "imported": len(rows)}

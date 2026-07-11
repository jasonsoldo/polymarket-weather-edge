"""Join finalized HKO observations to closed Polymarket Hong Kong markets."""

import json
import re
from datetime import date
from pathlib import Path
from typing import Optional

from .http_client import get_json
from .market_scanner import GAMMA_API


def backfill_hko_polymarket(input_path: str, output_path: str, pages: int = 3) -> dict:
    rows = _read_jsonl(input_path)
    output = []
    matched_days = matched_markets = resolved_markets = 0
    for row in rows:
        if row.get("status") != "available" or not row.get("date"):
            output.append({**row, "polymarket_status": "official_observation_unavailable"})
            continue
        markets = _closed_hko_markets(str(row["date"]), pages)
        summary = _summarize_day(row, markets)
        output.append({**row, **summary})
        matched_days += bool(markets)
        matched_markets += summary["polymarket_market_count"]
        resolved_markets += summary["polymarket_resolved_count"]
    _write_jsonl(output_path, output)
    return {
        "input": input_path,
        "output": output_path,
        "days": len(rows),
        "days_with_closed_markets": matched_days,
        "markets_found": matched_markets,
        "markets_resolved": resolved_markets,
    }


def _closed_hko_markets(target_date: str, pages: int) -> list[dict]:
    target = date.fromisoformat(target_date)
    query = f"Hong Kong temperature {target.strftime('%B')} {target.day} {target.year}"
    result = []
    seen = set()
    for page in range(1, max(1, pages) + 1):
        response = get_json(
            f"{GAMMA_API}/public-search",
            {"q": query, "events_status": "closed", "limit_per_type": 100, "page": page},
        )
        events = response.get("events") if isinstance(response, dict) else []
        if not events:
            break
        for event in events:
            for market in event.get("markets") or []:
                key = str(market.get("conditionId") or market.get("id") or "")
                if key and key not in seen and _is_target_hko_market(event, market, target_date):
                    seen.add(key)
                    result.append({"event": event, "market": market})
        if len(events) < 100:
            break
    return result


def _is_target_hko_market(event: dict, market: dict, target_date: str) -> bool:
    text = " ".join(str(item or "") for item in (
        event.get("title"), event.get("description"), event.get("resolutionSource"),
        market.get("question"), market.get("description"), market.get("resolutionSource"),
    )).lower()
    market_date = str(market.get("endDate") or event.get("endDate") or "")[:10]
    return (
        bool(market.get("closed", event.get("closed", False)))
        and market_date == target_date
        and "hong kong" in text
        and "observatory" in text
        and "temperature" in text
    )


def _summarize_day(observation: dict, records: list[dict]) -> dict:
    outcomes = []
    for record in records:
        market = record["market"]
        question = str(market.get("question") or "")
        metric = "low" if "lowest" in question.lower() or "low temperature" in question.lower() else "high"
        temperature = observation.get("api_low") if metric == "low" else observation.get("api_high")
        expected = _expected_outcome(question, temperature)
        resolved = _resolved_outcome(market)
        if expected and resolved:
            outcomes.append(expected == resolved)
    market_count = len(records)
    resolved_count = sum(_resolved_outcome(item["market"]) is not None for item in records)
    matched_count = sum(outcomes)
    return {
        "polymarket_status": "matched" if market_count else "no_matching_closed_market",
        "polymarket_market_count": market_count,
        "polymarket_resolved_count": resolved_count,
        "polymarket_matching_count": matched_count,
        "settlement_match": bool(market_count) and resolved_count == market_count and matched_count == market_count,
        "settlement_comparable": bool(market_count) and resolved_count == market_count,
    }


def _expected_outcome(question: str, temperature) -> Optional[str]:
    if temperature is None:
        return None
    match = re.search(r"\bbe\s+(-?\d+(?:\.\d+)?)\s*(?:[^\w\s]\s*)?[CF]\b", question, re.IGNORECASE)
    if not match:
        return None
    threshold = float(match.group(1))
    text = question.lower()
    value = float(temperature)
    if "or below" in text or "or less" in text:
        wins = value <= threshold
    elif "or higher" in text or "or above" in text or "or more" in text:
        wins = value >= threshold
    else:
        wins = threshold <= value < threshold + 1.0 if threshold.is_integer() else abs(value - threshold) <= 0.051
    return "Yes" if wins else "No"


def _resolved_outcome(market: dict) -> Optional[str]:
    outcomes = _json_list(market.get("outcomes"))
    prices = _json_list(market.get("outcomePrices"))
    for outcome, price in zip(outcomes, prices):
        try:
            if float(price) >= 0.999:
                return str(outcome)
        except (TypeError, ValueError):
            pass
    return None


def _json_list(value) -> list:
    if isinstance(value, list):
        return value
    if isinstance(value, str):
        try:
            parsed = json.loads(value)
            return parsed if isinstance(parsed, list) else []
        except json.JSONDecodeError:
            return []
    return []


def _read_jsonl(path: str) -> list[dict]:
    source = Path(path)
    return [json.loads(line) for line in source.read_text(encoding="utf-8").splitlines() if line.strip()] if source.exists() else []


def _write_jsonl(path: str, rows: list[dict]) -> None:
    target = Path(path)
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text("".join(json.dumps(row, sort_keys=True) + "\n" for row in rows), encoding="utf-8")

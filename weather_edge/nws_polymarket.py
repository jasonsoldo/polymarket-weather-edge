"""Match finalized NWS observations to closed New York temperature markets."""

from datetime import date

from .hko_polymarket_backfill import _expected_outcome, _resolved_outcome
from .http_client import get_json
from .market_scanner import GAMMA_API


def closed_new_york_markets(target_date: str, pages: int = 5) -> list[dict]:
    return scan_closed_new_york_markets(target_date, pages)["accepted"]


def scan_closed_new_york_markets(target_date: str, pages: int = 5) -> dict:
    target = date.fromisoformat(target_date)
    query = f"New York temperature {target.strftime('%B')} {target.day} {target.year}"
    records, rejected, seen = [], [], set()
    for page in range(1, max(1, pages) + 1):
        response = get_json(f"{GAMMA_API}/public-search", {"q": query, "events_status": "closed", "limit_per_type": 100, "page": page})
        events = response.get("events") if isinstance(response, dict) else []
        if not events:
            break
        for event in events:
            for market in event.get("markets") or []:
                key = str(market.get("conditionId") or market.get("id") or "")
                if not key or key in seen:
                    continue
                reason = _target_market_rejection(event, market, target_date)
                if reason == "":
                    seen.add(key)
                    records.append({"event": event, "market": market})
                elif reason == "settlement_source_is_not_nws" and _is_new_york_temperature_market(event, market, target_date):
                    seen.add(key)
                    rejected.append({"event": event, "market": market, "reason": reason})
        if len(events) < 100:
            break
    return {"accepted": records, "rejected": rejected}


def _is_target_market(event: dict, market: dict, target_date: str) -> bool:
    return _target_market_rejection(event, market, target_date) == ""


def _is_new_york_temperature_market(event: dict, market: dict, target_date: str) -> bool:
    text = " ".join(str(value or "") for value in (event.get("title"), event.get("description"), event.get("resolutionSource"), market.get("question"), market.get("description"), market.get("resolutionSource"))).lower()
    market_date = str(market.get("endDate") or event.get("endDate") or "")[:10]
    return bool(market.get("closed", event.get("closed", False))) and market_date == target_date and "temperature" in text and any(alias in text for alias in ("new york", "nyc", "central park", "knyc", "klga", "laguardia"))


def _target_market_rejection(event: dict, market: dict, target_date: str) -> str:
    if not _is_new_york_temperature_market(event, market, target_date):
        return "not_target_market"
    text = " ".join(str(value or "") for value in (event.get("description"), event.get("resolutionSource"), market.get("description"), market.get("resolutionSource"))).lower()
    return "" if any(source in text for source in ("national weather service", "nws", "noaa")) else "settlement_source_is_not_nws"


def compare_day(final_high: float, records: list[dict]) -> list[dict]:
    compared = []
    for record in records:
        market = record["market"]
        question = str(market.get("question") or "")
        if "highest temperature" not in question.lower() and "high temperature" not in question.lower():
            continue
        expected, resolved = _expected_outcome(question, final_high), _resolved_outcome(market)
        if not resolved:
            continue
        compared.append({"market": market, "market_id": str(market.get("id") or market.get("market_id") or ""), "question": question, "expected_outcome": expected, "resolved_outcome": resolved, "settlement_match": bool(expected and expected == resolved)})
    return compared

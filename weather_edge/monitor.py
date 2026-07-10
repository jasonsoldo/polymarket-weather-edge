import json
import re
import time
from datetime import date, datetime, timezone
from pathlib import Path
from typing import Optional

from .event_bucket_analysis import build_event_trade_plan, group_event_markets
from .http_client import get_json
from .history_store import save_monitor_snapshot
from .market_scanner import fetch_weather_markets
from .orderbook import fetch_book_summary
from .risk_manager import RiskConfig, weather_data_block
from .settlement_source import fetch_settlement_observation
from .strategy_config import StrategyConfig
from .weather_sources import fetch_weather_snapshot

DEFAULT_CITY_COORDS = {
    "New York": (40.7128, -74.0060),
    "Chicago": (41.8781, -87.6298),
    "Austin": (30.2672, -97.7431),
    "Miami": (25.7617, -80.1918),
    "Los Angeles": (34.0522, -118.2437),
    "Hong Kong": (22.3193, 114.1694),
}
OPEN_METEO_GEOCODING_API = "https://geocoding-api.open-meteo.com/v1/search"
MONTHS = {
    "january": 1, "february": 2, "march": 3, "april": 4, "may": 5, "june": 6,
    "july": 7, "august": 8, "september": 9, "october": 10, "november": 11, "december": 12,
}


def build_live_snapshot(
    city: str,
    latitude: float,
    longitude: float,
    target_date: str,
    market_limit: int = 100,
    include_books: bool = False,
    tag_id: str = "",
    slug: str = "",
    query: str = "",
    pages: int = 3,
    include_broad_weather: bool = False,
    discovered_markets=None,
) -> dict:
    target_date = _resolve_target_date(target_date)
    markets = discovered_markets if discovered_markets is not None else fetch_weather_markets(
        market_limit, city=city, tag_id=tag_id, slug=slug, query=query, pages=pages,
        include_broad_weather=include_broad_weather,
    )
    markets = _markets_for_target_date(markets, target_date)
    weather = fetch_weather_snapshot(city, latitude, longitude, target_date)
    risk_block = weather_data_block(weather.disagreement or 0.0, weather.confidence, RiskConfig())
    books = {}
    for market in markets:
        for token_id in market.token_ids:
            try:
                books[token_id] = fetch_book_summary(token_id)
            except RuntimeError:
                continue
    market_rows = []
    for event_markets in group_event_markets(markets):
        row = {
            "event_id": event_markets[0].event_id,
            "event_slug": event_markets[0].event_slug,
            "markets": [market.to_dict() for market in event_markets],
        }
        try:
            plan = build_event_trade_plan(
                event_markets, weather, StrategyConfig(), RiskConfig(), books
            )
            row["event_bucket_plan"] = plan.to_dict()
            row["settlement_observation"] = fetch_settlement_observation(plan.settlement_rule).to_dict()
        except ValueError as exc:
            row["event_bucket_plan_error"] = str(exc)
        row["books"] = []
        if include_books:
            for market in event_markets:
                for token_id in market.token_ids:
                    book = books.get(token_id)
                    row["books"].append(book.to_dict() if book else {"token_id": token_id, "error": "book_unavailable"})
        market_rows.append(row)

    snapshot = {
        "observed_at": datetime.now(timezone.utc).isoformat(),
        "city": city,
        "target_date": target_date,
        "weather": weather.to_dict(),
        "risk_capital_limit": RiskConfig().max_total_exposure,
        "markets_found": len(market_rows),
        "reason": "no strict city temperature markets found" if not market_rows and city and not include_broad_weather else "",
        "markets": market_rows,
        "notes": [
            "read_only_snapshot",
            "no_orders_are_created",
            "event-level settlement rules, probabilities, PnL curves, and death gaps are evaluated",
            "if markets_found is zero, check tag_id or slug from Polymarket UI/API",
        ],
    }
    if risk_block:
        snapshot.update(risk_block)
        snapshot["notes"].insert(0, "NO_TRADE")
    elif not market_rows:
        snapshot["recommended_action"] = "NO_MARKET"
        snapshot["risk_reasons"] = ["no strict city temperature markets found"]
    else:
        snapshot["recommended_action"] = "WATCH"
        snapshot["risk_reasons"] = []
    return snapshot


def build_all_cities_snapshot(
    target_date: str,
    cities: Optional[dict[str, tuple[float, float]]] = None,
    market_limit: int = 100,
    include_books: bool = False,
    pages: int = 3,
    include_broad_weather: bool = False,
) -> dict:
    target_date = _resolve_target_date(target_date)
    strict_markets = _markets_for_target_date(
        fetch_weather_markets(market_limit, city="", pages=pages, include_broad_weather=include_broad_weather),
        target_date,
    )
    city_coords, unresolved_cities = _city_coords_for_markets(strict_markets, cities)
    city_snapshots = []
    for city, coords in city_coords.items():
        latitude, longitude = coords
        city_markets = [market for market in strict_markets if market.city_guess.lower() == city.lower()]
        city_snapshots.append(
            build_live_snapshot(
                city,
                latitude,
                longitude,
                target_date,
                market_limit=market_limit,
                include_books=include_books,
                pages=pages,
                include_broad_weather=include_broad_weather,
                discovered_markets=city_markets,
            )
        )
    actions = [item.get("recommended_action", "") for item in city_snapshots]
    if any(action == "NO_TRADE" for action in actions):
        recommended_action = "NO_TRADE"
    elif any(item.get("markets_found", 0) for item in city_snapshots):
        recommended_action = "WATCH"
    else:
        recommended_action = "NO_MARKET"

    return {
        "observed_at": datetime.now(timezone.utc).isoformat(),
        "mode": "all_cities",
        "target_date": target_date,
        "recommended_action": recommended_action,
        "cities_monitored": len(city_snapshots),
        "markets_found": sum(item.get("markets_found", 0) for item in city_snapshots),
        "strict_markets_found": len(strict_markets),
        "strict_markets": [market.to_dict() for market in strict_markets],
        "risk_capital_limit": RiskConfig().max_total_exposure,
        "unresolved_cities": unresolved_cities,
        "cities": city_snapshots,
        "notes": [
            "read_only_snapshot",
            "no_orders_are_created",
            "cities are derived from strict temperature markets for the target date",
        ],
    }


def run_live_monitor_loop(
    city: str,
    latitude: float,
    longitude: float,
    target_date: str,
    output_path: str,
    interval_seconds: int = 300,
    market_limit: int = 100,
    include_books: bool = False,
    tag_id: str = "",
    slug: str = "",
    query: str = "",
    pages: int = 3,
    include_broad_weather: bool = False,
    max_runs: Optional[int] = None,
    history_db: str = "",
) -> int:
    if interval_seconds < 1:
        raise ValueError("interval_seconds must be at least 1")

    output = Path(output_path)
    output.parent.mkdir(parents=True, exist_ok=True)
    runs = 0
    while max_runs is None or runs < max_runs:
        snapshot = build_live_snapshot(
            city,
            latitude,
            longitude,
            target_date,
            market_limit=market_limit,
            include_books=include_books,
            tag_id=tag_id,
            slug=slug,
            query=query,
            pages=pages,
            include_broad_weather=include_broad_weather,
        )
        with output.open("a", encoding="utf-8") as handle:
            handle.write(json.dumps(snapshot, sort_keys=True) + "\n")
        if history_db:
            save_monitor_snapshot(history_db, snapshot)

        runs += 1
        if max_runs is not None and runs >= max_runs:
            break
        time.sleep(interval_seconds)
    return runs


def run_all_cities_monitor_loop(
    target_date: str,
    output_path: str,
    interval_seconds: int = 300,
    market_limit: int = 100,
    include_books: bool = False,
    pages: int = 3,
    include_broad_weather: bool = False,
    max_runs: Optional[int] = None,
    history_db: str = "",
) -> int:
    if interval_seconds < 1:
        raise ValueError("interval_seconds must be at least 1")

    output = Path(output_path)
    output.parent.mkdir(parents=True, exist_ok=True)
    runs = 0
    while max_runs is None or runs < max_runs:
        snapshot = build_all_cities_snapshot(
            target_date,
            market_limit=market_limit,
            include_books=include_books,
            pages=pages,
            include_broad_weather=include_broad_weather,
        )
        with output.open("a", encoding="utf-8") as handle:
            handle.write(json.dumps(snapshot, sort_keys=True) + "\n")
        if history_db:
            save_monitor_snapshot(history_db, snapshot)

        runs += 1
        if max_runs is not None and runs >= max_runs:
            break
        time.sleep(interval_seconds)
    return runs


def _resolve_target_date(target_date: str) -> str:
    return date.today().isoformat() if target_date.strip().lower() == "today" else target_date


def _markets_for_target_date(markets, target_date: str):
    return [market for market in markets if _market_matches_target_date(market, target_date)]


def _market_matches_target_date(market, target_date: str) -> bool:
    match = re.search(r"\b(" + "|".join(MONTHS) + r")\s+(\d{1,2})\b", market.question.lower())
    if match:
        market_date = f"{target_date[:4]}-{MONTHS[match.group(1)]:02d}-{int(match.group(2)):02d}"
        return market_date == target_date
    return market.end_date.startswith(target_date)


def _city_coords_for_markets(markets, configured_cities):
    if configured_cities is not None:
        return configured_cities, []
    coords = {}
    unresolved = []
    for city in sorted({market.city_guess.strip() for market in markets if market.city_guess.strip()}):
        if city in DEFAULT_CITY_COORDS:
            coords[city] = DEFAULT_CITY_COORDS[city]
            continue
        try:
            coords[city] = _geocode_city(city)
        except RuntimeError:
            unresolved.append(city)
    return coords, unresolved


def _geocode_city(city: str) -> tuple[float, float]:
    payload = get_json(OPEN_METEO_GEOCODING_API, {"name": city, "count": 1, "language": "en", "format": "json"})
    results = payload.get("results") or []
    if not results:
        raise RuntimeError(f"city geocoding returned no result: {city}")
    result = results[0]
    return float(result["latitude"]), float(result["longitude"])

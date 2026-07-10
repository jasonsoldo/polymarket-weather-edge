import json
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional

from .bucket_probability import build_bucket_probabilities
from .market_scanner import fetch_weather_markets
from .orderbook import fetch_book_summary
from .risk_manager import RiskConfig, weather_data_block
from .settlement_rules import parse_settlement_rule
from .weather_sources import fetch_weather_snapshot

DEFAULT_CITY_COORDS = {
    "New York": (40.7128, -74.0060),
    "Chicago": (41.8781, -87.6298),
    "Austin": (30.2672, -97.7431),
    "Miami": (25.7617, -80.1918),
    "Los Angeles": (34.0522, -118.2437),
    "Hong Kong": (22.3193, 114.1694),
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
) -> dict:
    markets = fetch_weather_markets(
        market_limit,
        city=city,
        tag_id=tag_id,
        slug=slug,
        query=query,
        pages=pages,
        include_broad_weather=include_broad_weather,
    )
    weather = fetch_weather_snapshot(city, latitude, longitude, target_date)
    risk_block = weather_data_block(weather.disagreement or 0.0, weather.confidence, RiskConfig())
    market_rows = []
    for market in markets:
        row = market.to_dict()
        try:
            rule = parse_settlement_rule(market)
            row["settlement_rule"] = rule.to_dict()
            row["bucket_probabilities"] = build_bucket_probabilities(rule, weather, market).to_dict()
        except ValueError as exc:
            row["settlement_rule_error"] = str(exc)
            row["bucket_probabilities"] = None
        row["books"] = []
        if include_books:
            for token_id in market.token_ids:
                try:
                    row["books"].append(fetch_book_summary(token_id).to_dict())
                except RuntimeError as exc:
                    row["books"].append({"token_id": token_id, "error": str(exc)})
        market_rows.append(row)

    snapshot = {
        "observed_at": datetime.now(timezone.utc).isoformat(),
        "city": city,
        "target_date": target_date,
        "weather": weather.to_dict(),
        "markets_found": len(market_rows),
        "reason": "no strict city temperature markets found" if not market_rows and city and not include_broad_weather else "",
        "markets": market_rows,
        "notes": [
            "read_only_snapshot",
            "no_orders_are_created",
            "model probabilities are not generated yet",
            "settlement rules still require market-rule parsing before trading",
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
    city_coords = cities or DEFAULT_CITY_COORDS
    city_snapshots = []
    for city, coords in city_coords.items():
        latitude, longitude = coords
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
            )
        )

    strict_markets = fetch_weather_markets(
        market_limit,
        city="",
        pages=pages,
        include_broad_weather=include_broad_weather,
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
        "cities": city_snapshots,
        "notes": [
            "read_only_snapshot",
            "no_orders_are_created",
            "default cities can be expanded when Polymarket lists additional city temperature markets",
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

        runs += 1
        if max_runs is not None and runs >= max_runs:
            break
        time.sleep(interval_seconds)
    return runs

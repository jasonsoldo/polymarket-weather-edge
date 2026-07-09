from .bucket_probability import build_bucket_probabilities
from .market_scanner import fetch_weather_markets
from .orderbook import fetch_book_summary
from .settlement_rules import parse_settlement_rule
from .weather_sources import fetch_weather_snapshot


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
) -> dict:
    markets = fetch_weather_markets(
        market_limit,
        city=city,
        tag_id=tag_id,
        slug=slug,
        query=query,
        pages=pages,
    )
    weather = fetch_weather_snapshot(city, latitude, longitude, target_date)
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

    return {
        "city": city,
        "target_date": target_date,
        "weather": weather.to_dict(),
        "markets_found": len(market_rows),
        "markets": market_rows,
        "notes": [
            "read_only_snapshot",
            "no_orders_are_created",
            "model probabilities are not generated yet",
            "settlement rules still require market-rule parsing before trading",
            "if markets_found is zero, check tag_id or slug from Polymarket UI/API",
        ],
    }

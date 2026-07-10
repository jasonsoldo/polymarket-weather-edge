from .event_bucket_analysis import build_event_trade_plan, group_event_markets
from .market_scanner import fetch_weather_markets
from .orderbook import fetch_book_summary
from .position_manager import load_positions, total_exposure
from .risk_manager import RiskConfig, weather_data_block
from .strategy_config import StrategyConfig
from .trade_executor import execute_trade_plan
from .weather_sources import fetch_weather_snapshot


def run_live_dry_run(
    city: str,
    latitude: float,
    longitude: float,
    target_date: str,
    strategy: StrategyConfig,
    risk: RiskConfig,
    orders_db: str,
    positions_db: str,
    market_limit: int = 20,
    tag_id: str = "",
    slug: str = "",
    query: str = "",
    pages: int = 2,
    include_broad_weather: bool = False,
) -> dict:
    weather = fetch_weather_snapshot(city, latitude, longitude, target_date)
    weather_block = weather_data_block(weather.disagreement or 0.0, weather.confidence, risk)
    if weather_block:
        return {
            "mode": strategy.execution_mode,
            "live_trading_enabled": strategy.live_trading_enabled,
            "city": city,
            "target_date": target_date,
            "weather": weather.to_dict(),
            "markets_found": 0,
            "results": [],
            **weather_block,
            "safety": [
                "NO_TRADE",
                "private key alone does not enable live trading",
                "execution_mode must be live and LIVE_TRADING_ENABLED env must equal true for live path",
                "live path uses official py-clob-client only when installed and explicitly enabled",
            ],
        }

    markets = fetch_weather_markets(
        market_limit,
        city=city,
        tag_id=tag_id,
        slug=slug,
        query=query,
        pages=pages,
        include_broad_weather=include_broad_weather,
    )

    rows = []
    positions = load_positions(positions_db)
    current_exposure = total_exposure(positions_db)
    for event_markets in group_event_markets(markets):
        row = {
            "event_id": event_markets[0].event_id,
            "event_slug": event_markets[0].event_slug,
            "markets": [market.to_dict() for market in event_markets],
        }
        try:
            books = _fetch_books(event_markets)
            plan = build_event_trade_plan(
                event_markets, weather, strategy, risk, books, positions, current_exposure
            )
            executions = execute_trade_plan(plan, strategy, orders_db, positions_db)
            row.update(
                {
                    "books": {token_id: book.to_dict() for token_id, book in books.items()},
                    "event_bucket_plan": plan.to_dict(),
                    "executions": [execution.to_dict() for execution in executions],
                }
            )
        except Exception as exc:
            row["error"] = str(exc)
        rows.append(row)

    return {
        "mode": strategy.execution_mode,
        "live_trading_enabled": strategy.live_trading_enabled,
        "city": city,
        "target_date": target_date,
        "weather": weather.to_dict(),
        "markets_found": len(markets),
        "results": rows,
        "safety": [
            "private key alone does not enable live trading",
            "execution_mode must be live and LIVE_TRADING_ENABLED env must equal true for live path",
            "live path uses official py-clob-client only when installed and explicitly enabled",
        ],
    }


def _fetch_books(markets) -> dict:
    books = {}
    for market in markets:
        for token_id in market.token_ids:
            books[token_id] = fetch_book_summary(token_id)
    return books

from .bucket_probability import build_bucket_probabilities
from .market_scanner import fetch_weather_markets
from .orderbook import fetch_book_summary
from .position_manager import positions_for_market, total_exposure
from .risk_manager import RiskConfig, weather_data_block
from .settlement_rules import parse_settlement_rule
from .strategy_config import StrategyConfig
from .strategy_planner import build_trade_plan
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
    for market in markets:
        row = {"market": market.to_dict()}
        try:
            books = _fetch_books(market)
            rule = parse_settlement_rule(market)
            probabilities = build_bucket_probabilities(rule, weather, market)
            positions = positions_for_market(positions_db, market.market_id)
            plan = build_trade_plan(
                market,
                rule,
                probabilities,
                books,
                positions,
                strategy,
                risk,
                current_total_exposure=total_exposure(positions_db),
            )
            executions = execute_trade_plan(plan, strategy, orders_db, positions_db)
            row.update(
                {
                    "books": {token_id: book.to_dict() for token_id, book in books.items()},
                    "settlement_rule": rule.to_dict(),
                    "bucket_probabilities": probabilities.to_dict(),
                    "trade_plan": plan.to_dict(),
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


def _fetch_books(market) -> dict:
    books = {}
    for token_id in market.token_ids:
        books[token_id] = fetch_book_summary(token_id)
    return books

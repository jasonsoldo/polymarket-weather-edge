"""Minimal weather market strategy core."""

from .pnl_curve import BucketInput, BucketPnL, DeathGap, PnLCurve, build_pnl_curve
from .market_scanner import GammaTag, WeatherMarket, discover_weather_tags, fetch_weather_markets
from .orderbook import BookSummary, fetch_book_summary
from .risk_manager import MarketState, RiskConfig, RiskDecision, evaluate_trade_plan
from .simulator import SimulationResult, simulate_settlement
from .weather_sources import DailyForecast, WeatherSnapshot, fetch_weather_snapshot

__all__ = [
    "BucketInput",
    "BucketPnL",
    "BookSummary",
    "DeathGap",
    "GammaTag",
    "MarketState",
    "PnLCurve",
    "RiskConfig",
    "RiskDecision",
    "SimulationResult",
    "DailyForecast",
    "WeatherSnapshot",
    "WeatherMarket",
    "build_pnl_curve",
    "discover_weather_tags",
    "evaluate_trade_plan",
    "fetch_book_summary",
    "fetch_weather_snapshot",
    "fetch_weather_markets",
    "simulate_settlement",
]

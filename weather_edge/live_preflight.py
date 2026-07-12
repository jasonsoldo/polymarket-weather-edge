"""Fail-closed preflight for Hong Kong automatic live trading."""

import importlib.util
import os

from .hko_finalizer import hko_closure_status
from .risk_manager import RiskConfig
from .strategy_config import StrategyConfig


def hong_kong_live_preflight(strategy: StrategyConfig, risk: RiskConfig, history_db: str, orders_db: str) -> dict:
    closure = hko_closure_status(history_db, orders_db)
    checks = {
        "hong_kong_settlement_verified": closure.get("settlement_verified") is True,
        "execution_mode_live": strategy.execution_mode == "live",
        "strategy_live_enabled": strategy.live_trading_enabled is True,
        "environment_live_enabled": os.getenv("LIVE_TRADING_ENABLED") == "true",
        "kill_switch_off": os.getenv("WEATHER_EDGE_KILL_SWITCH", "true").lower() == "false",
        "private_key_present": bool(os.getenv(strategy.private_key_env)),
        "official_clob_sdk_installed": importlib.util.find_spec("py_clob_client_v2") is not None,
        "max_order_size_at_most_1": risk.max_order_size <= 1.0,
        "max_market_exposure_at_most_3": risk.max_position_per_market <= 3.0,
        "max_daily_loss_at_most_3": risk.max_daily_loss <= 3.0,
        "max_total_exposure_at_most_5": risk.max_total_exposure <= 5.0,
        "confidence_at_least_085": risk.min_confidence >= 0.85,
        "minimum_edge_at_least_010": risk.min_edge >= 0.10,
        "maximum_spread_at_most_003": risk.max_spread <= 0.03,
    }
    failed = [name for name, passed in checks.items() if not passed]
    return {"ready": not failed, "recommended_action": "LIVE_READY" if not failed else "NO_TRADE", "checks": checks, "failed_checks": failed, "closure": closure}

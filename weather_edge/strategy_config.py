import json
from dataclasses import asdict, dataclass
from pathlib import Path


@dataclass(frozen=True)
class StrategyConfig:
    execution_mode: str = "dry_run"
    live_trading_enabled: bool = False
    private_key_env: str = "POLYMARKET_PRIVATE_KEY"
    min_order_edge: float = 0.03
    main_bucket_shares: float = 2.0
    neighbor_bucket_shares: float = 1.0
    tail_bucket_shares: float = 0.5
    max_buckets_to_buy: int = 4
    min_tail_probability: float = 0.03
    duplicate_order_window_seconds: int = 3600
    dry_run_fill_ratio: float = 1.0

    def to_dict(self) -> dict:
        return asdict(self)


def load_strategy_config(path: str = "") -> StrategyConfig:
    if not path:
        return StrategyConfig()
    data = json.loads(Path(path).read_text(encoding="utf-8"))
    allowed = set(asdict(StrategyConfig()).keys())
    unknown = set(data) - allowed
    if unknown:
        raise ValueError(f"unknown strategy config keys: {sorted(unknown)}")
    return StrategyConfig(**data)

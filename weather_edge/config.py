import json
from dataclasses import asdict
from pathlib import Path

from .risk_manager import RiskConfig


def load_risk_config(path: str) -> RiskConfig:
    data = json.loads(Path(path).read_text(encoding="utf-8"))
    allowed = set(asdict(RiskConfig()).keys())
    unknown = set(data) - allowed
    if unknown:
        raise ValueError(f"unknown risk config keys: {sorted(unknown)}")
    return RiskConfig(**data)

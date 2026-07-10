import hashlib
import json
import os
from dataclasses import asdict, dataclass
from datetime import datetime, timezone
from typing import Any, Optional

from ..http_client import get_json

SUPPORTED_STATIONS = {"ZBAA", "ZUCK", "ZGGG", "EGLC", "RKSI", "ZSPD", "ZGSZ", "RCSS", "RJTT"}
ADAPTER_VERSION = "wunderground-1"


@dataclass(frozen=True)
class WundergroundSnapshot:
    status: str
    station: str
    date: str
    daily_high: Optional[float]
    daily_low: Optional[float]
    unit: str
    updated_at: str = ""
    source_url: str = ""
    raw_payload_hash: str = ""
    adapter_version: str = ADAPTER_VERSION
    reason: str = ""

    def to_dict(self):
        return asdict(self)


def _number(value):
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def parse_wunderground_payload(payload: Any, station: str, target_date: str, unit: str) -> WundergroundSnapshot:
    values = {}
    def visit(value):
        if isinstance(value, dict):
            for key, item in value.items():
                key = str(key).lower().replace("-", "_")
                if any(token in key for token in ("high", "maximum", "temperaturemax", "maxt")) and "date" not in key:
                    values.setdefault("high", _number(item))
                if any(token in key for token in ("low", "minimum", "temperaturemin", "mint")) and "date" not in key:
                    values.setdefault("low", _number(item))
                if key in ("updated_at", "timestamp", "observation_time"):
                    values["updated"] = str(item)
            for item in value.values(): visit(item)
        elif isinstance(value, list):
            for item in value: visit(item)
    visit(payload)
    raw_hash = hashlib.sha256(json.dumps(payload, sort_keys=True, default=str).encode()).hexdigest()
    high, low = values.get("high"), values.get("low")
    return WundergroundSnapshot("wu_api_supported" if high is not None or low is not None else "wu_unavailable", station.upper(), target_date, high, low, unit.upper(), values.get("updated", datetime.now(timezone.utc).isoformat()), "", raw_hash, reason="API response missing daily extremes" if high is None and low is None else "")


def fetch_wunderground_api(station: str, target_date: str, unit: str, source_url: str = "") -> WundergroundSnapshot:
    station = station.upper()
    if station not in SUPPORTED_STATIONS:
        return WundergroundSnapshot("wu_unavailable", station, target_date, None, None, unit, reason="unsupported station")
    endpoint = os.getenv("WU_API_URL", "")
    key = os.getenv("WU_API_KEY", "")
    if not endpoint or not key:
        return WundergroundSnapshot("pending_wu_adapter", station, target_date, None, None, unit, source_url=source_url, reason="WU_API_URL and WU_API_KEY are required")
    endpoint = endpoint.replace("{station}", station).replace("{date}", target_date)
    try:
        payload = get_json(endpoint, {"station": station, "date": target_date, "apiKey": key, "units": unit.lower()})
        result = parse_wunderground_payload(payload, station, target_date, unit)
        return WundergroundSnapshot(result.status, result.station, result.date, result.daily_high, result.daily_low, result.unit, result.updated_at, source_url or endpoint, result.raw_payload_hash, result.adapter_version, result.reason)
    except RuntimeError as exc:
        return WundergroundSnapshot("wu_unavailable", station, target_date, None, None, unit, source_url=source_url or endpoint, reason=str(exc))

import csv
import hashlib
import io
from dataclasses import asdict, dataclass
from datetime import datetime
from typing import Optional
from zoneinfo import ZoneInfo

from ..http_client import get_text


CURRENT_URL = "https://data.weather.gov.hk/weatherAPI/hko_data/regional-weather/latest_1min_temperature.csv"
SINCE_MIDNIGHT_URL = "https://data.weather.gov.hk/weatherAPI/hko_data/regional-weather/latest_since_midnight_maxmin.csv"
HKO_TIMEZONE = "Asia/Hong_Kong"
ADAPTER_VERSION = "hko-realtime-1"
STATION_ALIASES = {"hk observatory", "hong kong observatory"}


@dataclass(frozen=True)
class HkoObservation:
    source: str
    city: str
    station: str
    station_id: str
    observation_time: str
    current_temp: Optional[float]
    max_temp_since_midnight: Optional[float]
    min_temp_since_midnight: Optional[float]
    forecast_high: Optional[float]
    forecast_low: Optional[float]
    final_daily_max: Optional[float]
    final_daily_min: Optional[float]
    unit: str
    timezone: str
    data_type: str
    is_final: bool
    source_url: str
    raw_payload_hash: str
    adapter_version: str
    fetched_at: str
    health: dict
    healthy: bool
    block_reason: str

    def to_dict(self) -> dict:
        return asdict(self)


def fetch_hko_realtime(target_date: str, now: Optional[datetime] = None) -> HkoObservation:
    now = now or datetime.now(ZoneInfo(HKO_TIMEZONE))
    current_csv = get_text(CURRENT_URL)
    extremes_csv = get_text(SINCE_MIDNIGHT_URL)
    current = _station_row(current_csv)
    extremes = _station_row(extremes_csv)
    timestamp = str((extremes or current or {}).get("timestamp") or "")
    observed = _parse_timestamp(timestamp)
    current_temp = _number((current or {}).get("values", [None])[0])
    extreme_values = (extremes or {}).get("values", [])
    maximum = _number(extreme_values[0] if len(extreme_values) > 0 else None)
    minimum = _number(extreme_values[1] if len(extreme_values) > 1 else None)
    health = {
        "response_success": bool(current_csv and extremes_csv),
        "required_fields_present": current_temp is not None and maximum is not None and minimum is not None and observed is not None,
        "timestamp_fresh": bool(observed and abs((now - observed).total_seconds()) <= 30 * 60),
        "unit_match": True,
        "target_date_match": bool(observed and observed.date().isoformat() == target_date),
        "station_match": current is not None and extremes is not None,
        "timezone_match": bool(observed and observed.utcoffset() == now.utcoffset()),
        "data_type_match": True,
    }
    healthy = all(health.values())
    payload_hash = hashlib.sha256((current_csv + "\n" + extremes_csv).encode("utf-8")).hexdigest()
    return HkoObservation(
        source="Hong Kong Observatory", city="Hong Kong", station="Hong Kong Observatory", station_id="HKO",
        observation_time=observed.isoformat() if observed else "", current_temp=current_temp,
        max_temp_since_midnight=maximum, min_temp_since_midnight=minimum,
        forecast_high=None, forecast_low=None, final_daily_max=None, final_daily_min=None,
        unit="C", timezone=HKO_TIMEZONE, data_type="real_time_observation", is_final=False,
        source_url=SINCE_MIDNIGHT_URL, raw_payload_hash=payload_hash, adapter_version=ADAPTER_VERSION,
        fetched_at=now.isoformat(), health=health, healthy=healthy,
        block_reason="" if healthy else "hko_adapter_unhealthy",
    )


def _station_row(payload: str) -> Optional[dict]:
    rows = csv.reader(io.StringIO(payload))
    next(rows, None)
    for row in rows:
        if len(row) >= 3 and row[1].strip().lower() in STATION_ALIASES:
            return {"timestamp": row[0].strip(), "values": [value.strip() for value in row[2:]]}
    return None


def _parse_timestamp(value: str) -> Optional[datetime]:
    try:
        return datetime.strptime(value, "%Y%m%d%H%M").replace(tzinfo=ZoneInfo(HKO_TIMEZONE))
    except ValueError:
        return None


def _number(value) -> Optional[float]:
    try:
        cleaned = str(value).strip().rstrip("*")
        return None if not cleaned or cleaned.upper() == "N/A" else float(cleaned)
    except (TypeError, ValueError):
        return None

from dataclasses import dataclass, asdict
from typing import Optional

from .http_client import get_json


OPEN_METEO_API = "https://api.open-meteo.com/v1/forecast"
NWS_API = "https://api.weather.gov"


@dataclass(frozen=True)
class DailyForecast:
    source: str
    date: str
    max_temp: Optional[float]
    min_temp: Optional[float]
    unit: str
    updated_at: str
    raw_location: str
    timezone: str
    model: str
    station_or_grid: str

    def to_dict(self) -> dict:
        return asdict(self)


@dataclass(frozen=True)
class WeatherSnapshot:
    city: str
    latitude: float
    longitude: float
    target_date: str
    forecasts: tuple[DailyForecast, ...]
    disagreement: Optional[float]
    confidence: float

    def to_dict(self) -> dict:
        return {
            "city": self.city,
            "latitude": self.latitude,
            "longitude": self.longitude,
            "target_date": self.target_date,
            "forecasts": [forecast.to_dict() for forecast in self.forecasts],
            "disagreement": self.disagreement,
            "confidence": self.confidence,
        }


def fetch_weather_snapshot(
    city: str,
    latitude: float,
    longitude: float,
    target_date: str,
    unit: str = "fahrenheit",
) -> WeatherSnapshot:
    forecasts = [fetch_open_meteo(latitude, longitude, target_date, unit)]
    nws = fetch_nws(latitude, longitude, target_date)
    if nws:
        forecasts.append(nws)

    max_values = [forecast.max_temp for forecast in forecasts if forecast.max_temp is not None]
    min_values = [forecast.min_temp for forecast in forecasts if forecast.min_temp is not None]
    spreads = []
    if len(max_values) >= 2:
        spreads.append(max(max_values) - min(max_values))
    if len(min_values) >= 2:
        spreads.append(max(min_values) - min(min_values))
    disagreement = max(spreads) if spreads else None
    confidence = _confidence(len(forecasts), disagreement)
    return WeatherSnapshot(
        city=city,
        latitude=latitude,
        longitude=longitude,
        target_date=target_date,
        forecasts=tuple(forecasts),
        disagreement=disagreement,
        confidence=confidence,
    )


def fetch_open_meteo(
    latitude: float,
    longitude: float,
    target_date: str,
    unit: str = "fahrenheit",
) -> DailyForecast:
    data = get_json(
        OPEN_METEO_API,
        {
            "latitude": latitude,
            "longitude": longitude,
            "daily": "temperature_2m_max,temperature_2m_min",
            "temperature_unit": unit,
            "timezone": "auto",
            "start_date": target_date,
            "end_date": target_date,
        },
    )
    daily = data.get("daily") or {}
    dates = daily.get("time") or []
    if target_date not in dates:
        raise RuntimeError(f"Open-Meteo did not return target date {target_date}")
    index = dates.index(target_date)
    unit_name = (data.get("daily_units") or {}).get("temperature_2m_max", unit)
    return DailyForecast(
        source="open_meteo",
        date=target_date,
        max_temp=_value_at(daily.get("temperature_2m_max"), index),
        min_temp=_value_at(daily.get("temperature_2m_min"), index),
        unit=unit_name,
        updated_at=str(data.get("generationtime_ms") or ""),
        raw_location=f"{data.get('latitude')},{data.get('longitude')}",
        timezone=str(data.get("timezone") or ""),
        model=str(data.get("model") or data.get("models") or "best_match"),
        station_or_grid="open_meteo_grid",
    )


def fetch_nws(latitude: float, longitude: float, target_date: str) -> Optional[DailyForecast]:
    try:
        points = get_json(f"{NWS_API}/points/{latitude},{longitude}")
        point_props = points.get("properties") or {}
        forecast_hourly_url = point_props.get("forecastHourly")
        if not forecast_hourly_url:
            return None
        hourly = get_json(forecast_hourly_url)
    except RuntimeError:
        return None

    temps = []
    updated_at = ""
    for period in (hourly.get("properties") or {}).get("periods") or []:
        start = str(period.get("startTime") or "")
        if not start.startswith(target_date):
            continue
        temp = period.get("temperature")
        if temp is not None:
            temps.append(float(temp))
        updated_at = str(period.get("startTime") or updated_at)
    if not temps:
        return None
    return DailyForecast(
        source="nws",
        date=target_date,
        max_temp=max(temps),
        min_temp=min(temps),
        unit="F",
        updated_at=updated_at,
        raw_location=f"{latitude},{longitude}",
        timezone=str((hourly.get("properties") or {}).get("timeZone") or ""),
        model="nws_grid_forecast_hourly",
        station_or_grid="/".join(
            str(part)
            for part in (
                point_props.get("gridId"),
                point_props.get("gridX"),
                point_props.get("gridY"),
            )
            if part is not None
        ),
    )


def _value_at(values, index: int) -> Optional[float]:
    if not values or index >= len(values):
        return None
    value = values[index]
    return None if value is None else float(value)


def _confidence(source_count: int, disagreement: Optional[float]) -> float:
    base = 0.55 if source_count == 1 else 0.85
    if disagreement is None:
        return base
    if disagreement <= 1.0:
        return min(0.95, base + 0.10)
    if disagreement <= 2.0:
        return base
    if disagreement <= 4.0:
        return max(0.40, base - 0.20)
    return 0.25

import os
from dataclasses import dataclass, asdict
from datetime import date
from typing import Optional

from .http_client import get_json
from .official_sources import extract_observation
from .settlement_sources.hko import fetch_hko_realtime


OPEN_METEO_API = "https://api.open-meteo.com/v1/forecast"
NWS_API = "https://api.weather.gov"
METOFFICE_DAILY_API = "https://data.hub.api.metoffice.gov.uk/sitespecific/v0/point/daily"
HKO_FORECAST_API = "https://data.weather.gov.hk/weatherAPI/opendata/weather.php"


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
    hko_observation: Optional[dict] = None

    def to_dict(self) -> dict:
        return {
            "city": self.city,
            "latitude": self.latitude,
            "longitude": self.longitude,
            "target_date": self.target_date,
            "forecasts": [forecast.to_dict() for forecast in self.forecasts],
            "disagreement": self.disagreement,
            "confidence": self.confidence,
            "hko_observation": self.hko_observation,
        }


def fetch_weather_snapshot(
    city: str,
    latitude: float,
    longitude: float,
    target_date: str,
    unit: str = "fahrenheit",
) -> WeatherSnapshot:
    if target_date.strip().lower() == "today":
        target_date = date.today().isoformat()
    forecasts = []
    try:
        forecasts.append(fetch_open_meteo(latitude, longitude, target_date, unit))
    except RuntimeError:
        pass
    hko = fetch_hko_forecast(city, target_date)
    if hko:
        forecasts.append(hko)
    hko_observation = None
    if city.strip().lower() in {"hong kong", "hko"}:
        try:
            hko_observation = fetch_hko_realtime(target_date).to_dict()
        except RuntimeError:
            hko_observation = {
                "healthy": False,
                "block_reason": "hko_adapter_unhealthy",
                "data_type": "real_time_observation",
                "is_final": False,
            }
    nws = fetch_nws(latitude, longitude, target_date)
    if nws:
        forecasts.append(nws)
    weatherapi = fetch_weatherapi(latitude, longitude, target_date, unit)
    if weatherapi:
        forecasts.append(weatherapi)
    accuweather = fetch_accuweather(latitude, longitude, target_date, unit)
    if accuweather:
        forecasts.append(accuweather)
    metoffice = fetch_metoffice(latitude, longitude, target_date, unit)
    if metoffice:
        forecasts.append(metoffice)
    for provider in _configured_provider_for_city(city):
        forecast = fetch_configured_forecast(provider, latitude, longitude, target_date, unit)
        if forecast:
            forecasts.append(forecast)

    max_values = [forecast.max_temp for forecast in forecasts if forecast.max_temp is not None]
    min_values = [forecast.min_temp for forecast in forecasts if forecast.min_temp is not None]
    spreads = []
    if len(max_values) >= 2:
        spreads.append(max(max_values) - min(max_values))
    if len(min_values) >= 2:
        spreads.append(max(min_values) - min(min_values))
    disagreement = max(spreads) if spreads else None
    healthy_hko_observation = bool(hko_observation and hko_observation.get("healthy"))
    confidence = _confidence(len(forecasts) + int(healthy_hko_observation), disagreement)
    return WeatherSnapshot(
        city=city,
        latitude=latitude,
        longitude=longitude,
        target_date=target_date,
        forecasts=tuple(forecasts),
        disagreement=disagreement,
        confidence=confidence,
        hko_observation=hko_observation,
    )


def fetch_configured_forecast(provider: str, latitude: float, longitude: float, target_date: str, unit: str) -> Optional[DailyForecast]:
    prefix = provider.upper().replace(" ", "")
    endpoint = os.getenv(f"{prefix}_FORECAST_URL", "").strip()
    key = os.getenv(f"{prefix}_API_KEY", "").strip()
    if not endpoint:
        return None
    endpoint = endpoint.replace("{date}", target_date).replace("{lat}", str(latitude)).replace("{lon}", str(longitude))
    params = {"latitude": latitude, "longitude": longitude, "date": target_date, "target_date": target_date, "unit": unit}
    headers = {"User-Agent": "WeatherEdge/1.0"}
    if key:
        params["Authorization" if prefix == "CWA" else "apiKey"] = key
    try:
        payload = get_json(endpoint, params, headers=headers)
        if prefix == "CWA":
            maximum, minimum, observed_at = _extract_cwa_forecast(payload, target_date)
            response_unit = "C"
        else:
            maximum, minimum, observed_at, response_date, response_station, response_unit = extract_observation(payload)
            if response_date and not str(response_date).startswith(target_date):
                return None
        if maximum is None and minimum is None:
            return None
        return DailyForecast(
            f"{provider.lower()}_forecast", target_date, maximum, minimum,
            response_unit or ("F" if unit.lower().startswith("f") else "C"),
            observed_at or target_date, f"{latitude},{longitude}", "", f"{provider.lower()}_official_forecast", "official",
        )
    except (RuntimeError, TypeError, ValueError, KeyError):
        return None


def _extract_cwa_forecast(payload: dict, target_date: str) -> tuple[Optional[float], Optional[float], str]:
    maximum = minimum = None
    observed_at = ""
    records = payload.get("records") or {} if isinstance(payload, dict) else {}
    locations_value = records.get("locations") or records.get("Locations") or []
    locations = locations_value if isinstance(locations_value, list) else [locations_value]
    for container in locations:
        location_items = []
        if isinstance(container, dict):
            location_items = container.get("location") or container.get("Location") or []
        if isinstance(location_items, dict):
            location_items = [location_items]
        for location in location_items or []:
            elements = location.get("weatherElement") or location.get("WeatherElement") or []
            for element in elements:
                name = str(element.get("elementName") or element.get("ElementName") or "").lower()
                if "最高" not in name and "最低" not in name and "maxt" not in name and "mint" not in name:
                    continue
                for item in element.get("time") or element.get("Time") or []:
                    start = str(item.get("startTime") or item.get("StartTime") or item.get("dataTime") or item.get("DataTime") or "")
                    if not start.startswith(target_date):
                        continue
                    raw_value = item.get("elementValue") or item.get("ElementValue")
                    value = (raw_value or [{}])[0] if isinstance(raw_value, list) else raw_value
                    if isinstance(value, dict):
                        if "最高" in name or "maxt" in name:
                            value = value.get("MaxTemperature") or value.get("value") or value.get("Value")
                        else:
                            value = value.get("MinTemperature") or value.get("value") or value.get("Value")
                    try:
                        number = float(value)
                    except (TypeError, ValueError):
                        continue
                    observed_at = start
                    if "最高" in name or "maxt" in name:
                        maximum = number if maximum is None else max(maximum, number)
                    else:
                        minimum = number if minimum is None else min(minimum, number)
    return maximum, minimum, observed_at


def _configured_provider_for_city(city: str) -> tuple[str, ...]:
    normalized = city.strip().lower()
    if normalized in {"tokyo", "haneda", "rjtt"}:
        return ("JMA",)
    if normalized in {"seoul", "incheon", "rksi"}:
        return ("KMA",)
    if normalized in {"taipei", "songshan", "rcss"}:
        return ("CWA",)
    return ()


def fetch_hko_forecast(city: str, target_date: str) -> Optional[DailyForecast]:
    if city.strip().lower() not in {"hong kong", "hko"}:
        return None
    try:
        data = get_json(HKO_FORECAST_API, {"dataType": "fnd", "lang": "en"})
        item = next((row for row in data.get("weatherForecast", []) if str(row.get("forecastDate", "")) == target_date.replace("-", "")), None)
        if not item:
            return None
        maximum = ((item.get("forecastMaxtemp") or {}).get("value"))
        minimum = ((item.get("forecastMintemp") or {}).get("value"))
        if maximum is None or minimum is None:
            return None
        return DailyForecast("hko_forecast", target_date, float(maximum), float(minimum), "C", str(data.get("updateTime") or ""), "Hong Kong Observatory", "Asia/Hong_Kong", "hko_9day_forecast", "HKO")
    except (KeyError, TypeError, ValueError, RuntimeError):
        return None


def fetch_weatherapi(latitude: float, longitude: float, target_date: str, unit: str = "fahrenheit") -> Optional[DailyForecast]:
    key = os.getenv("WEATHERAPI_KEY", "").strip()
    if not key:
        return None
    try:
        data = get_json("https://api.weatherapi.com/v1/forecast.json", {
            "key": key, "q": f"{latitude},{longitude}", "days": 14,
            "dt": target_date, "aqi": "no", "alerts": "no",
        })
        day = ((data.get("forecast") or {}).get("forecastday") or [])[0].get("day") or {}
        current = ((data.get("current") or {}).get("last_updated") or "")
        use_f = unit.lower().startswith("f")
        return DailyForecast("weatherapi", target_date, float(day["maxtemp_f" if use_f else "maxtemp_c"]), float(day["mintemp_f" if use_f else "mintemp_c"]), "F" if use_f else "C", current, f"{latitude},{longitude}", str((data.get("location") or {}).get("tz_id") or ""), "weatherapi", "weatherapi_grid")
    except (KeyError, IndexError, TypeError, ValueError, RuntimeError):
        return None


def fetch_accuweather(latitude: float, longitude: float, target_date: str, unit: str = "fahrenheit") -> Optional[DailyForecast]:
    key = os.getenv("ACCUWEATHER_API_KEY", "").strip()
    if not key:
        return None


def fetch_metoffice(latitude: float, longitude: float, target_date: str, unit: str = "fahrenheit") -> Optional[DailyForecast]:
    key = os.getenv("METOFFICE_API_KEY", "").strip()
    if not key:
        return None
    try:
        data = get_json(METOFFICE_DAILY_API, {"latitude": latitude, "longitude": longitude}, headers={"apikey": key})
        features = data.get("features") or []
        properties = (features[0].get("properties") if features else data.get("properties")) or {}
        times = properties.get("time") or properties.get("times") or properties.get("dates") or []
        target = next((item for item in times if str(item.get("time") or item.get("date") or "").startswith(target_date)), None) if isinstance(times, list) else None
        if not target:
            return None
        values = target.get("daySignificantWeatherCode", {}) if isinstance(target, dict) else {}
        maximum = _nested_temperature(target, ("dayMaxScreenTemperature", "maxTemperature", "max_temp", "maximum"))
        minimum = _nested_temperature(target, ("nightMinScreenTemperature", "minTemperature", "min_temp", "minimum"))
        if maximum is None and minimum is None:
            return None
        return DailyForecast("metoffice", target_date, maximum, minimum, "C", str(target.get("time") or ""), f"{latitude},{longitude}", "", "metoffice_global_spot_daily", "metoffice_grid")
    except (KeyError, IndexError, TypeError, ValueError, RuntimeError):
        return None


def _nested_temperature(value, names):
    if not isinstance(value, dict):
        return None
    for name in names:
        item = value.get(name)
        if isinstance(item, dict):
            item = item.get("value")
        try:
            if item is not None:
                return float(item)
        except (TypeError, ValueError):
            continue
    return None
    try:
        location = get_json("https://dataservice.accuweather.com/locations/v1/cities/geoposition/search", {"apikey": key, "q": f"{latitude},{longitude}"})
        location_key = str(location.get("Key") or "")
        if not location_key:
            return None
        daily = get_json(f"https://dataservice.accuweather.com/forecasts/v1/daily/15day/{location_key}", {"apikey": key, "metric": "false" if unit.lower().startswith("f") else "true"})
        target = next((item for item in daily.get("DailyForecasts") or [] if str(item.get("Date", "")).startswith(target_date)), None)
        if not target:
            return None
        minimum = target.get("Temperature", {}).get("Minimum", {}).get("Value")
        maximum = target.get("Temperature", {}).get("Maximum", {}).get("Value")
        return DailyForecast("accuweather", target_date, float(maximum), float(minimum), "F" if unit.lower().startswith("f") else "C", str(target.get("Date") or ""), str(location.get("LocalizedName") or f"{latitude},{longitude}"), "", "accuweather_15day", location_key)
    except (KeyError, IndexError, TypeError, ValueError, RuntimeError):
        return None


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
    if source_count <= 0:
        return 0.0
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

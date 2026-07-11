import unittest
import os
from unittest.mock import patch

from weather_edge.market_scanner import discover_weather_tags, fetch_weather_markets
from weather_edge.city_registry import match_city
from weather_edge.orderbook import fetch_book_summary
from weather_edge.weather_sources import fetch_configured_forecast, fetch_hko_forecast, fetch_weather_snapshot


class LiveDataSourceParsingTests(unittest.TestCase):
    def test_configured_official_forecast_is_separate_from_settlement(self):
        with patch.dict(os.environ, {"JMA_FORECAST_URL": "https://jma.test/forecast", "JMA_API_KEY": "key"}), patch("weather_edge.weather_sources.get_json", return_value={"date": "2026-07-12", "daily_high": 31, "daily_low": 24, "unit": "C"}):
            forecast = fetch_configured_forecast("JMA", 35.6, 139.7, "2026-07-12", "C")
        self.assertEqual(forecast.source, "jma_forecast")
        self.assertEqual(forecast.max_temp, 31.0)
        self.assertEqual(forecast.station_or_grid, "official")

    def test_cwa_forecast_uses_authorization_and_parses_daily_extremes(self):
        payload = {"records": {"locations": [{"location": [{"weatherElement": [
            {"elementName": "最高溫度", "time": [{"startTime": "2026-07-12T06:00:00+08:00", "elementValue": [{"value": "34"}]}]},
            {"elementName": "最低溫度", "time": [{"startTime": "2026-07-12T06:00:00+08:00", "elementValue": [{"value": "27"}]}]},
        ]}]}]}}
        with patch.dict(os.environ, {"CWA_FORECAST_URL": "https://opendata.cwa.gov.tw/api/v1/rest/datastore/F-D0047-063", "CWA_API_KEY": "cwa-key"}), patch("weather_edge.weather_sources.get_json", return_value=payload) as request:
            forecast = fetch_configured_forecast("CWA", 25.03, 121.56, "2026-07-12", "C")
        self.assertEqual(forecast.max_temp, 34.0)
        self.assertEqual(forecast.min_temp, 27.0)
        self.assertIn("Authorization", request.call_args.args[1])

    def test_cwa_forecast_parses_official_capitalized_locations_key(self):
        payload = {"records": {"Locations": [{"location": [{"weatherElement": [
            {"elementName": "最高温度", "time": [{"startTime": "2026-07-12T06:00:00+08:00", "elementValue": [{"value": "34"}]}]},
            {"elementName": "最低温度", "time": [{"startTime": "2026-07-12T06:00:00+08:00", "elementValue": [{"value": "27"}]}]},
        ]}]}]}}
        with patch.dict(os.environ, {"CWA_FORECAST_URL": "https://cwa.test/forecast", "CWA_API_KEY": "cwa-key"}), patch("weather_edge.weather_sources.get_json", return_value=payload):
            forecast = fetch_configured_forecast("CWA", 25.03, 121.56, "2026-07-12", "C")
        self.assertEqual(forecast.max_temp, 34.0)
        self.assertEqual(forecast.min_temp, 27.0)

    def test_cwa_forecast_parses_official_capitalized_location_key(self):
        payload = {"records": {"Locations": [{"Location": [{"WeatherElement": [
            {"elementName": "最高温度", "time": [{"startTime": "2026-07-12T06:00:00+08:00", "elementValue": [{"value": "34"}]}]},
            {"elementName": "最低温度", "time": [{"startTime": "2026-07-12T06:00:00+08:00", "elementValue": [{"value": "27"}]}]},
        ]}]}]}}
        with patch.dict(os.environ, {"CWA_FORECAST_URL": "https://cwa.test/forecast", "CWA_API_KEY": "cwa-key"}), patch("weather_edge.weather_sources.get_json", return_value=payload):
            forecast = fetch_configured_forecast("CWA", 25.03, 121.56, "2026-07-12", "C")
        self.assertEqual(forecast.max_temp, 34.0)
        self.assertEqual(forecast.min_temp, 27.0)

    def test_hko_forecast_reads_official_daily_high_low(self):
        with patch("weather_edge.weather_sources.get_json", return_value={"updateTime": "2026-07-10T11:30:00+08:00", "weatherForecast": [{"forecastDate": "20260710", "forecastMaxtemp": {"value": 32, "unit": "C"}, "forecastMintemp": {"value": 27, "unit": "C"}}]}):
            forecast = fetch_hko_forecast("Hong Kong", "2026-07-10")
        self.assertEqual(forecast.source, "hko_forecast")
        self.assertEqual(forecast.max_temp, 32.0)
        self.assertEqual(forecast.min_temp, 27.0)
    def test_city_alias_matching_does_not_turn_unrelated_text_into_los_angeles(self):
        item, alias = match_city("Will the highest temperature in Hong Kong be 26C or below")
        self.assertEqual(item["name"], "Hong Kong")
        self.assertEqual(alias, "Hong Kong")

    def test_fetch_weather_markets_filters_gamma_events(self):
        def fake_get_json(url, params=None, timeout=20):
            if url.endswith("/tags"):
                return [{"id": "10", "label": "Weather", "slug": "weather"}]
            return {
                "events": [
                    {
                        "id": "event-1",
                        "slug": "nyc-high-temperature",
                        "title": "NYC high temperature on July 10",
                        "active": True,
                        "closed": False,
                        "tags": [{"label": "Weather", "slug": "weather"}],
                        "markets": [
                            {
                                "id": "market-1",
                                "conditionId": "condition-1",
                                "slug": "nyc-high-temperature-88",
                                "question": "What will the high temperature be in New York on July 10?",
                                "description": "Weather market",
                                "endDate": "2026-07-10T23:59:00Z",
                                "resolutionSource": "NWS",
                                "outcomes": '["86F or below","87F","88F","89F or higher"]',
                                "outcomePrices": '["0.05","0.24","0.30","0.18"]',
                                "clobTokenIds": '["token-1","token-2","token-3","token-4"]',
                                "active": True,
                                "closed": False,
                            }
                        ],
                    },
                    {"id": "event-2", "title": "Fed decision", "markets": []},
                ],
                "next_cursor": "",
            }

        with patch("weather_edge.market_scanner.get_json", side_effect=fake_get_json):
            markets = fetch_weather_markets(limit=10, city="New York")

        self.assertEqual(len(markets), 1)
        self.assertEqual(markets[0].market_id, "market-1")
        self.assertEqual(markets[0].condition_id, "condition-1")
        self.assertEqual(markets[0].outcomes[2], "88F")
        self.assertEqual(markets[0].outcome_prices[2], 0.30)
        self.assertEqual(markets[0].token_ids[2], "token-3")
        self.assertEqual(markets[0].resolution_source, "NWS")
        self.assertTrue(markets[0].is_temperature_market)
        self.assertEqual(markets[0].excluded_reason, "")
        self.assertIn("high temperature", markets[0].matched_keywords)
        self.assertGreater(markets[0].city_match_score, 0)
        self.assertEqual(markets[0].market_type_guess, "high_temp")

    def test_public_search_discovers_city_temperature_bucket_markets(self):
        def fake_get_json(url, params=None, timeout=20):
            if url.endswith("/public-search"):
                self.assertIn("q", params)
                return {
                    "events": [
                        {
                            "id": "event-hk",
                            "slug": "highest-temperature-in-hong-kong-on-july-9-2026",
                            "title": "Highest temperature in Hong Kong on July 9?",
                            "active": True,
                            "closed": False,
                            "tags": [
                                {"label": "Weather", "slug": "weather"},
                                {"label": "temperature", "slug": "temperature"},
                            ],
                            "markets": [
                                {
                                    "id": "market-hk-26",
                                    "conditionId": "condition-hk-26",
                                    "slug": "highest-temperature-in-hong-kong-on-july-9-2026-26c",
                                    "question": "Will the highest temperature in Hong Kong be 26°C on July 9?",
                                    "description": "Resolves to the highest temperature recorded by the Hong Kong Observatory in degrees Celsius.",
                                    "endDate": "2026-07-09T12:00:00Z",
                                    "outcomes": '["Yes","No"]',
                                    "outcomePrices": '["0.10","0.90"]',
                                    "clobTokenIds": '["token-yes","token-no"]',
                                    "active": True,
                                    "closed": False,
                                    "feeType": "weather_fees",
                                }
                            ],
                        }
                    ]
                }
            if url.endswith("/tags"):
                return []
            if url.endswith("/events") or url.endswith("/events/keyset"):
                return {"events": [], "next_cursor": ""}
            return []

        with patch("weather_edge.market_scanner.get_json", side_effect=fake_get_json):
            markets = fetch_weather_markets(limit=10, pages=1)

        self.assertEqual(len(markets), 1)
        self.assertEqual(markets[0].market_id, "market-hk-26")
        self.assertEqual(markets[0].city_guess, "Hong Kong")
        self.assertTrue(markets[0].is_temperature_market)
        self.assertEqual(markets[0].market_type_guess, "high_temp")
        self.assertIn("temperature", markets[0].matched_keywords)

    def test_strict_filter_excludes_broad_weather_and_non_weather_markets(self):
        def fake_get_json(url, params=None, timeout=20):
            if url.endswith("/tags"):
                return [{"id": "10", "label": "Weather", "slug": "weather"}]
            return {
                "events": [
                    {
                        "id": "event-1",
                        "slug": "weather-and-climate",
                        "title": "Climate markets",
                        "active": True,
                        "closed": False,
                        "tags": [{"label": "Weather", "slug": "weather"}],
                        "markets": [
                            {
                                "id": "market-1",
                                "slug": "arctic-sea-ice-extent-2026",
                                "question": "Arctic sea ice extent in 2026?",
                                "description": "Climate change long-term market",
                                "outcomes": '["Yes","No"]',
                                "outcomePrices": '["0.5","0.5"]',
                                "clobTokenIds": '["token-1","token-2"]',
                                "active": True,
                                "closed": False,
                            },
                            {
                                "id": "market-2",
                                "slug": "measles-cases-in-us-in-2026",
                                "question": "Measles cases in US in 2026?",
                                "description": "Disease market",
                                "outcomes": '["Yes","No"]',
                                "outcomePrices": '["0.5","0.5"]',
                                "clobTokenIds": '["token-3","token-4"]',
                                "active": True,
                                "closed": False,
                            },
                        ],
                    }
                ],
                "next_cursor": "",
            }

        with patch("weather_edge.market_scanner.get_json", side_effect=fake_get_json):
            strict = fetch_weather_markets(limit=10, city="New York")
            broad = fetch_weather_markets(limit=10, include_broad_weather=True)

        self.assertEqual(strict, [])
        self.assertEqual(len(broad), 1)
        self.assertEqual(broad[0].excluded_reason, "arctic sea ice")

    def test_strict_filter_excludes_heat_wave_threshold_markets(self):
        def fake_get_json(url, params=None, timeout=20):
            if url.endswith("/public-search"):
                return {
                    "events": [
                        {
                            "id": "event-paris",
                            "slug": "paris-heat-wave-by-july-31",
                            "title": "Paris heat wave by July 31?",
                            "active": True,
                            "closed": False,
                            "tags": [{"label": "Weather", "slug": "weather"}, {"label": "temperature", "slug": "temperature"}],
                            "markets": [
                                {
                                    "id": "market-paris",
                                    "conditionId": "condition-paris",
                                    "slug": "paris-heat-wave-by-july-31",
                                    "question": "Paris heat wave by July 31?",
                                    "description": "Resolves Yes if the highest temperature is at least 35 degrees Celsius for 3 consecutive days.",
                                    "outcomes": '["Yes","No"]',
                                    "outcomePrices": '["0.50","0.50"]',
                                    "clobTokenIds": '["yes","no"]',
                                    "active": True,
                                    "closed": False,
                                }
                            ],
                        }
                    ]
                }
            if url.endswith("/tags"):
                return []
            return {"events": [], "next_cursor": ""}

        with patch("weather_edge.market_scanner.get_json", side_effect=fake_get_json):
            markets = fetch_weather_markets(limit=10, pages=1)

        self.assertEqual(markets, [])

    def test_discover_weather_tags_finds_weather_label(self):
        with patch(
            "weather_edge.market_scanner.get_json",
            return_value=[{"id": "10", "label": "Weather", "slug": "weather"}],
        ):
            tags = discover_weather_tags()

        self.assertEqual(tags[0].id, "10")

    def test_fetch_book_summary_calculates_bbo_and_spread(self):
        book = {
            "bids": [{"price": "0.20", "size": "4"}, {"price": "0.24", "size": "5"}],
            "asks": [{"price": "0.31", "size": "3"}, {"price": "0.35", "size": "2"}],
            "market": "condition-1",
            "min_order_size": "5",
            "tick_size": "0.01",
            "neg_risk": True,
            "hash": "0xabc",
            "timestamp": "123",
        }

        with patch("weather_edge.orderbook.get_json", return_value=book):
            summary = fetch_book_summary("token-1")

        self.assertEqual(summary.best_bid, 0.24)
        self.assertEqual(summary.best_ask, 0.31)
        self.assertAlmostEqual(summary.spread, 0.07)
        self.assertEqual(summary.bid_size, 9)
        self.assertEqual(summary.ask_size, 5)
        self.assertEqual(summary.tick_size, 0.01)
        self.assertEqual(summary.min_order_size, 5)
        self.assertTrue(summary.neg_risk)
        self.assertEqual(summary.book_hash, "0xabc")

    def test_weather_snapshot_combines_open_meteo_and_nws(self):
        def fake_get_json(url, params=None, timeout=20):
            if "open-meteo" in url:
                return {
                    "latitude": 40.7,
                    "longitude": -74.0,
                    "generationtime_ms": 1.2,
                    "timezone": "America/New_York",
                    "daily_units": {"temperature_2m_max": "F"},
                    "daily": {
                        "time": ["2026-07-10"],
                        "temperature_2m_max": [88.0],
                        "temperature_2m_min": [72.0],
                    },
                }
            if "/points/" in url:
                return {"properties": {"forecastHourly": "https://api.weather.gov/gridpoints/test/hourly"}}
            return {
                "properties": {
                    "timeZone": "America/New_York",
                    "periods": [
                        {"startTime": "2026-07-10T00:00:00-04:00", "temperature": 73},
                        {"startTime": "2026-07-10T15:00:00-04:00", "temperature": 89},
                    ]
                }
            }

        with patch("weather_edge.weather_sources.get_json", side_effect=fake_get_json):
            snapshot = fetch_weather_snapshot("New York", 40.7, -74.0, "2026-07-10")

        self.assertEqual(len(snapshot.forecasts), 2)
        self.assertEqual(snapshot.disagreement, 1.0)
        self.assertGreaterEqual(snapshot.confidence, 0.85)
        self.assertEqual(snapshot.forecasts[0].timezone, "America/New_York")
        self.assertEqual(snapshot.forecasts[1].model, "nws_grid_forecast_hourly")

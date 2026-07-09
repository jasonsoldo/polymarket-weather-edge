import unittest
from unittest.mock import patch

from weather_edge.market_scanner import discover_weather_tags, fetch_weather_markets
from weather_edge.orderbook import fetch_book_summary
from weather_edge.weather_sources import fetch_weather_snapshot


class LiveDataSourceParsingTests(unittest.TestCase):
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

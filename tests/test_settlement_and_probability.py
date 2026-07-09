import unittest

from weather_edge.bucket_probability import build_bucket_probabilities
from weather_edge.market_scanner import WeatherMarket
from weather_edge.settlement_rules import parse_bucket, parse_settlement_rule
from weather_edge.weather_sources import DailyForecast, WeatherSnapshot


class SettlementAndProbabilityTests(unittest.TestCase):
    def test_parse_bucket_bounds(self):
        self.assertEqual(parse_bucket("86F or below").upper, 86)
        self.assertIsNone(parse_bucket("86F or below").lower)
        self.assertEqual(parse_bucket("89F or higher").lower, 89)
        self.assertIsNone(parse_bucket("89F or higher").upper)
        self.assertEqual(parse_bucket("87F").lower, 87)
        self.assertEqual(parse_bucket("87F").upper, 87)
        self.assertEqual(parse_bucket("87-89F").lower, 87)
        self.assertEqual(parse_bucket("87-89F").upper, 89)

    def test_parse_settlement_rule_extracts_required_weather_fields(self):
        market = _market()

        rule = parse_settlement_rule(market)

        self.assertEqual(rule.city, "New York")
        self.assertEqual(rule.date, "2026-07-10")
        self.assertEqual(rule.market_type, "max_temp")
        self.assertEqual(rule.settlement_source, "NWS")
        self.assertEqual(rule.measurement_unit, "F")
        self.assertEqual(rule.timezone, "America/New_York")
        self.assertEqual(rule.target_station_or_data_source, "KNYC")
        self.assertEqual(rule.rounding_rule, "nearest_integer")
        self.assertEqual(len(rule.buckets), 4)
        self.assertGreater(rule.confidence, 0.75)

    def test_probability_curve_uses_weather_forecasts_and_market_prices(self):
        market = _market()
        rule = parse_settlement_rule(market)
        weather = WeatherSnapshot(
            city="New York",
            latitude=40.7128,
            longitude=-74.0060,
            target_date="2026-07-10",
            forecasts=(
                DailyForecast("open_meteo", "2026-07-10", 88.0, 72.0, "F", "1", "40,-74", "America/New_York", "best_match", "grid"),
                DailyForecast("nws", "2026-07-10", 86.0, 73.0, "F", "2", "40,-74", "America/New_York", "nws_grid", "OKX/33/42"),
            ),
            disagreement=2.0,
            confidence=0.80,
        )

        curve = build_bucket_probabilities(rule, weather, market)

        self.assertAlmostEqual(curve.probability_sum, 1.0)
        self.assertEqual(curve.model.target_temperature_type, "max_temp")
        self.assertEqual(curve.buckets[2].bucket, "88F")
        self.assertGreater(curve.buckets[2].model_probability, 0.1)
        self.assertAlmostEqual(curve.buckets[2].edge, curve.buckets[2].model_probability - 0.30)


def _market():
    return WeatherMarket(
        event_id="event-1",
        event_slug="nyc-high-temperature",
        event_title="NYC high temperature on July 10",
        market_id="market-1",
        condition_id="condition-1",
        market_slug="nyc-high-temperature-88",
        question="What will the high temperature be in New York on July 10?",
        description=(
            "This market resolves based on the National Weather Service station KNYC. "
            "Temperature will be measured in Fahrenheit and rounded to the nearest whole degree. "
            "Resolution time is ET."
        ),
        end_date="2026-07-10T23:59:00Z",
        active=True,
        closed=False,
        outcomes=("86F or below", "87F", "88F", "89F or higher"),
        outcome_prices=(0.05, 0.24, 0.30, 0.18),
        token_ids=("token-1", "token-2", "token-3", "token-4"),
        resolution_source="NWS",
        tags=("Weather",),
        city_guess="New York",
        discovery_source="test",
        is_temperature_market=True,
        excluded_reason="",
        matched_keywords=("high temperature",),
        city_match_score=2,
        market_type_guess="high_temp",
    )

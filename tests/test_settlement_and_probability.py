import unittest
from dataclasses import replace

from weather_edge.bucket_probability import build_bucket_probabilities, build_probability_model
from weather_edge.event_bucket_analysis import build_event_trade_plan
from weather_edge.risk_manager import RiskConfig
from weather_edge.strategy_config import StrategyConfig
from weather_edge.market_scanner import WeatherMarket
from weather_edge.settlement_rules import parse_bucket, parse_settlement_rule
from weather_edge.weather_sources import DailyForecast, WeatherSnapshot


class SettlementAndProbabilityTests(unittest.TestCase):
    def test_wunderground_rule_is_parsed_with_icao_station_and_city_timezone(self):
        market = replace(
            _market(),
            question="Will the highest temperature in London be 25C on July 10?",
            outcomes=("Yes", "No"),
            outcome_prices=(0.2, 0.8),
            city_guess="London",
            normalized_city="London",
            resolution_source="",
            description="Resolves using https://www.wunderground.com/history/daily/gb/london/EGLC",
        )
        rule = parse_settlement_rule(market)
        self.assertEqual(rule.settlement_source, "Weather Underground")
        self.assertEqual(rule.target_station_or_data_source, "EGLC")
        self.assertEqual(rule.timezone, "Europe/London")
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

    def test_yes_no_temperature_market_parses_question_bucket_and_converts_units(self):
        market = _hong_kong_market("26°C")
        rule = parse_settlement_rule(market)
        weather = WeatherSnapshot(
            "Hong Kong", 22.3, 114.2, "2026-07-10",
            (DailyForecast("open_meteo", "2026-07-10", 78.8, 73.0, "F", "1", "", "Asia/Hong_Kong", "best", "grid"),),
            None, 0.80,
        )

        self.assertEqual(rule.measurement_unit, "C")
        self.assertEqual(rule.buckets[0].label, "26°C")
        self.assertAlmostEqual(build_probability_model(rule, weather).mean, 26.0, places=1)

    def test_event_plan_has_complete_pnl_rows_and_death_gap(self):
        markets = [_hong_kong_market("25°C or below"), _hong_kong_market("26°C"), _hong_kong_market("27°C or higher")]
        weather = WeatherSnapshot(
            "Hong Kong", 22.3, 114.2, "2026-07-10",
            (DailyForecast("open_meteo", "2026-07-10", 78.8, 73.0, "F", "1", "", "Asia/Hong_Kong", "best", "grid"),),
            None, 0.80,
        )

        plan = build_event_trade_plan(markets, weather, StrategyConfig(max_buckets_to_buy=1), RiskConfig())

        self.assertEqual(len(plan.curve.rows), 3)
        self.assertTrue(plan.bucket_set_complete)
        self.assertGreater(plan.curve.max_uncovered_probability, 0.08)
        self.assertTrue(plan.curve.death_gaps)


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


def _hong_kong_market(bucket: str):
    return WeatherMarket(
        event_id="hko-event", event_slug="highest-temperature-in-hong-kong", event_title="Highest temperature in Hong Kong on July 10?",
        market_id=f"hko-{bucket}", condition_id="", market_slug=f"hko-{bucket}",
        question=f"Will the highest temperature in Hong Kong be {bucket} on July 10?",
        description="Resolves using Hong Kong Observatory Absolute Daily Max (deg. C).",
        end_date="2026-07-10T23:59:00Z", active=True, closed=False, outcomes=("Yes", "No"),
        outcome_prices=(0.20, 0.80), token_ids=(f"yes-{bucket}", f"no-{bucket}"),
        resolution_source="Hong Kong Observatory", tags=("Weather",), city_guess="Hong Kong", discovery_source="test",
        is_temperature_market=True, excluded_reason="", matched_keywords=("highest temperature",), city_match_score=2,
        market_type_guess="high_temp",
    )

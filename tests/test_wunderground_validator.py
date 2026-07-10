import unittest

from weather_edge.settlement_sources.wunderground_validator import validate_history


class WundergroundValidatorTests(unittest.TestCase):
    def test_station_is_not_verified_until_threshold_is_met(self):
        rows = [{"api_high": 30, "page_high": 30, "station_observed_high": 30, "resolved_high": 30}]
        result = validate_history(rows, min_days=30)
        self.assertFalse(result.verified)
        self.assertEqual(result.validation_days, 1)

    def test_matching_history_can_verify_station(self):
        rows = [{"api_high": 30, "page_high": 30, "station_observed_high": 30, "resolved_high": 30} for _ in range(30)]
        result = validate_history(rows, min_days=30)
        self.assertTrue(result.verified)
        self.assertEqual(result.exact_match_rate, 1.0)

    def test_wrong_station_or_date_counts_as_missing(self):
        rows = [{"api_high": 30, "page_high": 30, "station_match": False, "date_match": True} for _ in range(30)]
        self.assertFalse(validate_history(rows, min_days=30).verified)


if __name__ == "__main__":
    unittest.main()

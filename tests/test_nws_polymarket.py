import unittest

from weather_edge.nws_polymarket import _is_target_market, compare_day


class NwsPolymarketTests(unittest.TestCase):
    def test_requires_date_city_source_and_closed_market(self):
        event = {"title": "New York temperature", "description": "National Weather Service KNYC", "endDate": "2026-07-10T23:00:00Z"}
        market = {"closed": True, "question": "Will the highest temperature in New York be 85°F on July 10?"}
        self.assertTrue(_is_target_market(event, market, "2026-07-10"))
        self.assertFalse(_is_target_market(event, {**market, "closed": False}, "2026-07-10"))

    def test_compares_final_temperature_to_resolved_bucket(self):
        market = {"id": "m1", "question": "Will the highest temperature in New York be 85°F on July 10?", "outcomes": ["Yes", "No"], "outcomePrices": [1, 0]}
        result = compare_day(85.0, [{"event": {}, "market": market}])
        self.assertEqual(result[0]["expected_outcome"], "Yes")
        self.assertTrue(result[0]["settlement_match"])


if __name__ == "__main__":
    unittest.main()

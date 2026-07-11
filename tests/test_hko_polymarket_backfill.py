import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from weather_edge.hko_polymarket_backfill import _expected_outcome, backfill_hko_polymarket


class HkoPolymarketBackfillTests(unittest.TestCase):
    def test_integer_bucket_covers_the_full_degree_interval(self):
        question = "Will the highest temperature in Hong Kong be 30°C on May 31?"
        self.assertEqual(_expected_outcome(question, 30.9), "Yes")
        self.assertEqual(_expected_outcome(question, 31.0), "No")

    def test_backfill_requires_all_closed_buckets_to_match_hko(self):
        event = {
            "title": "Highest temperature in Hong Kong on June 1?",
            "description": "Hong Kong Observatory daily temperature",
            "endDate": "2025-06-01T12:00:00Z",
            "markets": [
                {"id": "a", "closed": True, "question": "Will the highest temperature in Hong Kong be 31°C on June 1?", "outcomes": '["Yes", "No"]', "outcomePrices": '["1", "0"]'},
                {"id": "b", "closed": True, "question": "Will the highest temperature in Hong Kong be 32°C on June 1?", "outcomes": '["Yes", "No"]', "outcomePrices": '["0", "1"]'},
            ],
        }
        with tempfile.TemporaryDirectory() as tmp:
            source = Path(tmp) / "hko.jsonl"
            output = Path(tmp) / "joined.jsonl"
            source.write_text(json.dumps({"date": "2025-06-01", "status": "available", "api_high": 31.0, "api_low": 25.0}) + "\n", encoding="utf-8")
            with patch("weather_edge.hko_polymarket_backfill.get_json", return_value={"events": [event]}):
                summary = backfill_hko_polymarket(str(source), str(output))
            row = json.loads(output.read_text(encoding="utf-8"))
        self.assertEqual(summary["markets_resolved"], 2)
        self.assertTrue(row["settlement_comparable"])
        self.assertTrue(row["settlement_match"])

    def test_backfill_marks_missing_event_without_claiming_match(self):
        with tempfile.TemporaryDirectory() as tmp:
            source = Path(tmp) / "hko.jsonl"
            output = Path(tmp) / "joined.jsonl"
            source.write_text(json.dumps({"date": "2025-06-01", "status": "available", "api_high": 31.0, "api_low": 25.0}) + "\n", encoding="utf-8")
            with patch("weather_edge.hko_polymarket_backfill.get_json", return_value={"events": []}):
                backfill_hko_polymarket(str(source), str(output))
            row = json.loads(output.read_text(encoding="utf-8"))
        self.assertEqual(row["polymarket_status"], "no_matching_closed_market")
        self.assertFalse(row["settlement_match"])


if __name__ == "__main__":
    unittest.main()

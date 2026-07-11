import unittest

from weather_edge.cli import _dry_run_summary


class DryRunSummaryTests(unittest.TestCase):
    def test_event_risk_is_promoted_to_top_level_no_trade(self):
        summary = _dry_run_summary({
            "mode": "dry_run",
            "city": "Hong Kong",
            "target_date": "2026-07-12",
            "weather": {"forecasts": [], "confidence": 0.85, "disagreement": 1.8},
            "markets_found": 22,
            "results": [{
                "event_slug": "highest-temperature-in-hong-kong-on-july-12-2026",
                "event_bucket_plan": {
                    "settlement_source_status": "supported_official",
                    "decision": {"recommended_action": "block_new_position", "reasons": ["death gap probability is too high: 32C"]},
                    "curve": {"total_cost": 0.2, "worst_case_pnl": -0.2, "best_case_pnl": 1.8, "death_gaps": [{"bucket": "32C"}]},
                },
            }],
        })

        self.assertEqual(summary["recommended_action"], "NO_TRADE")
        self.assertEqual(summary["blocked_by"], "event_risk")
        self.assertIn("death gap probability is too high: 32C", summary["risk_reasons"])


if __name__ == "__main__":
    unittest.main()

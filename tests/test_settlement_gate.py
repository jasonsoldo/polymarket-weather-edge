import unittest

from weather_edge.settlement_source import settlement_status_allows_scoring


class SettlementGateTests(unittest.TestCase):
    def test_only_verified_wunderground_can_score(self):
        self.assertTrue(settlement_status_allows_scoring("wu_verified"))
        for status in ("pending_wu_adapter", "wu_browser_supported", "wu_api_supported", "wu_source_mismatch", "wu_stale", "wu_unavailable"):
            self.assertFalse(settlement_status_allows_scoring(status))


if __name__ == "__main__":
    unittest.main()

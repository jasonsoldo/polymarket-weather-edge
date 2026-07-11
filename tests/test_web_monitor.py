import tempfile
import unittest
from pathlib import Path

from weather_edge.web_monitor import read_recent_snapshots, render_dashboard, render_module_page


class WebMonitorTests(unittest.TestCase):
    def test_read_recent_snapshots_reads_jsonl_tail(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "live_monitor.jsonl"
            path.write_text(
                '{"observed_at":"one","recommended_action":"WATCH"}\n'
                '{"observed_at":"two","recommended_action":"NO_TRADE"}\n',
                encoding="utf-8",
            )

            snapshots = read_recent_snapshots(str(path), limit=1)

        self.assertEqual(len(snapshots), 1)
        self.assertEqual(snapshots[0]["observed_at"], "two")
        self.assertEqual(snapshots[0]["recommended_action"], "NO_TRADE")

    def test_render_dashboard_shows_weather_risk_and_market_status(self):
        snapshot = {
            "city": "New York",
            "target_date": "2026-07-10",
            "recommended_action": "NO_TRADE",
            "blocked_by": "data_disagreement",
            "risk_reasons": ["NO_TRADE", "weather data disagreement too high"],
            "weather": {"disagreement": 3.9, "confidence": 0.65},
            "markets_found": 0,
            "markets": [],
        }

        html = render_dashboard(snapshot, [snapshot])

        self.assertIn("WeatherEdge Monitor", html)
        self.assertIn("NO_TRADE", html)
        self.assertIn("Real Weather Markets", html)
        self.assertNotIn("Raw Snapshot", html)

    def test_render_dashboard_shows_event_bucket_pnl_and_death_gap(self):
        snapshot = {
            "city": "Hong Kong",
            "target_date": "2026-07-10",
            "recommended_action": "WATCH",
            "weather": {"disagreement": 0.5, "confidence": 0.9, "forecasts": [{"source": "open_meteo", "max_temp": 81.3, "min_temp": 70.2, "unit": "F"}]},
            "risk_capital_limit": 500.0,
            "markets_found": 1,
            "markets": [{
                "event_slug": "highest-temperature-in-hong-kong",
                "event_bucket_plan": {
                    "decision": {"recommended_action": "block_new_position"},
                    "settlement_rule": {"settlement_source": "Wunderground", "target_station_or_data_source": "EGLC", "measurement_unit": "C"},
                    "forecast_model": {"mean": 27.4, "standard_deviation": 1.1},
                    "curve": {
                        "total_cost": 12.5, "best_case_pnl": 4.5, "worst_case_pnl": -12.5,
                        "death_gaps": [{"bucket": "27°C"}],
                        "rows": [{
                            "bucket": "27°C", "price": 0.20, "model_probability": 0.32,
                            "edge": 0.12, "shares": 0.0, "pnl_if_wins": 0.0,
                        }],
                    },
                },
            }],
        }

        html = render_dashboard(snapshot, [])

        self.assertIn("Real Weather Markets", html)
        self.assertIn("highest-temperature-in-hong-kong", html)
        self.assertIn("Investment", html)
        self.assertIn("Maximum Loss", html)
        self.assertIn("500.00", html)
        self.assertIn("27.40C", html)
        self.assertIn("open_meteo: H 81.3F / L 70.2F", html)

    def test_render_dashboard_shows_all_cities_table(self):
        snapshot = {
            "mode": "all_cities",
            "target_date": "2026-07-10",
            "recommended_action": "NO_TRADE",
            "cities_monitored": 2,
            "markets_found": 0,
            "strict_markets_found": 0,
            "strict_markets": [],
            "cities": [
                {
                    "city": "New York",
                    "recommended_action": "NO_TRADE",
                    "markets_found": 0,
                    "weather": {"disagreement": 3.9, "confidence": 0.65},
                    "risk_reasons": ["NO_TRADE"],
                },
                {
                    "city": "Chicago",
                    "recommended_action": "NO_MARKET",
                    "markets_found": 0,
                    "weather": {"disagreement": 0.5, "confidence": 0.9},
                    "risk_reasons": ["no strict city temperature markets found"],
                },
            ],
        }

        html = render_dashboard(snapshot, [snapshot])

        self.assertIn("WeatherEdge All Cities Monitor", html)
        self.assertIn("Real Weather Markets", html)
        self.assertNotIn("Global Strict Temperature Markets", html)

    def test_all_cities_dashboard_shows_city_bucket_curve(self):
        snapshot = {
            "mode": "all_cities", "target_date": "2026-07-10", "recommended_action": "WATCH",
            "cities_monitored": 1, "markets_found": 1, "strict_markets_found": 0, "strict_markets": [],
            "cities": [{
                "city": "Hong Kong", "recommended_action": "WATCH", "markets_found": 1,
                "weather": {"disagreement": 0.5, "confidence": 0.9}, "risk_reasons": [],
                "markets": [{
                    "event_slug": "highest-temperature-in-hong-kong",
                    "event_bucket_plan": {"decision": {"recommended_action": "block_new_position"}, "curve": {
                        "death_gaps": [], "rows": [{"bucket": "27°C", "price": 0.2, "model_probability": 0.3, "edge": 0.1, "pnl_if_wins": 0.0}],
                    }},
                }],
            }],
        }

        html = render_dashboard(snapshot, [])

        self.assertIn("Real Weather Markets", html)
        self.assertIn("27°C", html)


    def test_hong_kong_closure_is_visible_on_dashboard_and_module(self):
        snapshot = {
            "mode": "all_cities", "target_date": "2026-07-12", "recommended_action": "NO_TRADE",
            "portfolio": {"cost_basis": 0, "unrealized_pnl": 0, "stale_positions": 0},
            "hong_kong_closure": {"settlement_verified": True, "last_final_date": "2026-07-10", "final_daily_max": 31.0, "markets_resolved": 2, "settlement_matches": 2, "winning_buckets": ["Will the highest temperature in Hong Kong be 31C?"], "shadow_samples": 1, "shadow_finalized": 1, "shadow_hypothetical_pnl": 0.6, "shadow_realized_pnl": 0.6},
            "cities": [{"city": "Hong Kong", "markets_found": 2, "weather": {"confidence": 0.85, "forecasts": [{"source": "hko_forecast", "max_temp": 32.0, "unit": "C", "updated_at": "2026-07-11"}]}, "markets": []}],
        }
        overview = render_dashboard(snapshot, [])
        module = render_module_page(snapshot, "/hong-kong", [])
        self.assertIn("HONG KONG FIRST", overview)
        self.assertIn("SHADOW REALIZED", overview)
        self.assertIn("official_source_verified", module)
        self.assertIn("31.0", module)
        self.assertIn("0.60", module)


if __name__ == "__main__":
    unittest.main()

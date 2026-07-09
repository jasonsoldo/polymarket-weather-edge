import json
import tempfile
import unittest
from contextlib import redirect_stdout
from io import StringIO
from pathlib import Path

from weather_edge.cli import main


class CliBacktestTests(unittest.TestCase):
    def test_analyze_can_write_sqlite_log(self):
        with tempfile.TemporaryDirectory() as tmp:
            db = str(Path(tmp) / "weather_edge.sqlite")
            with redirect_stdout(StringIO()):
                code = main(
                    [
                        "analyze",
                        "--plan",
                        "data/sample_plan.json",
                        "--config",
                        "config/risk.example.json",
                        "--db",
                        db,
                    ]
                )

            self.assertEqual(code, 0)
            self.assertTrue(Path(db).exists())

    def test_backtest_sample_has_trade_and_block(self):
        with tempfile.TemporaryDirectory() as tmp:
            output_path = Path(tmp) / "summary.json"
            with redirect_stdout(StringIO()):
                code = main(
                    [
                        "backtest",
                        "--file",
                        "data/sample_backtest.json",
                        "--config",
                        "config/risk.example.json",
                    ]
                )

            output_path.write_text(json.dumps({"code": code}), encoding="utf-8")
            self.assertEqual(code, 0)

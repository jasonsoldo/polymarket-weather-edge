import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from weather_edge.order_store import StoredOrder, load_orders, save_order
from weather_edge.reconciliation import reconcile_live_orders


class ReconciliationTests(unittest.TestCase):
    def test_updates_submitted_order_with_exchange_fill(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = str(Path(tmp) / "orders.sqlite")
            save_order(path, StoredOrder("c1", "m", "t", "27C", "BUY", 0.2, 5, "live_submitted", {"response": {"orderID": "exchange-1"}}))
            with patch("weather_edge.reconciliation.get_order", return_value={"status": "MATCHED", "size_matched": "5"}):
                rows = reconcile_live_orders(path)

            self.assertEqual(rows[0]["status"], "live_filled")
            self.assertEqual(load_orders(path)[0].status, "live_filled")

from .clob_v2 import get_order
from .order_store import StoredOrder, load_orders, save_order


TERMINAL = {"MATCHED", "CANCELED", "CANCELLED", "UNMATCHED", "REJECTED"}


def reconcile_live_orders(orders_db: str) -> list[dict]:
    rows = []
    for order in load_orders(orders_db, ("live_submitted",)):
        order_id = _order_id(order.payload.get("response") or {})
        if not order_id:
            rows.append({"client_order_id": order.client_order_id, "status": "unreconciled", "reason": "exchange order id missing"})
            continue
        exchange = get_order(order_id)
        status = str(exchange.get("status") or "live_submitted").upper()
        filled = float(exchange.get("size_matched") or exchange.get("matched_size") or 0.0)
        local_status = "live_filled" if status == "MATCHED" else "live_partial" if filled > 0 else "live_submitted"
        payload = {**order.payload, "reconciliation": exchange, "filled_size": filled}
        save_order(orders_db, StoredOrder(order.client_order_id, order.market_id, order.token_id, order.bucket, order.side, order.price, order.size, local_status, payload))
        rows.append({"client_order_id": order.client_order_id, "exchange_order_id": order_id, "status": local_status, "filled_size": filled})
    return rows


def _order_id(response: dict) -> str:
    return str(response.get("orderID") or response.get("order_id") or response.get("id") or "")

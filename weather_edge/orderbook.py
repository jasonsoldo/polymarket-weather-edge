from dataclasses import asdict, dataclass
from typing import Optional

from .http_client import get_json


CLOB_API = "https://clob.polymarket.com"


@dataclass(frozen=True)
class BookSummary:
    token_id: str
    market: str
    best_bid: Optional[float]
    best_ask: Optional[float]
    spread: Optional[float]
    bid_size: float
    ask_size: float
    min_order_size: Optional[float]
    tick_size: Optional[float]
    neg_risk: bool
    book_hash: str
    raw_timestamp: str

    def to_dict(self) -> dict:
        return asdict(self)


def fetch_book_summary(token_id: str) -> BookSummary:
    book = get_json(f"{CLOB_API}/book", {"token_id": token_id})
    bids = _levels(book.get("bids") or book.get("buys") or [])
    asks = _levels(book.get("asks") or book.get("sells") or [])
    best_bid = max((price for price, _size in bids), default=None)
    best_ask = min((price for price, _size in asks), default=None)
    spread = best_ask - best_bid if best_bid is not None and best_ask is not None else None
    return BookSummary(
        token_id=token_id,
        market=str(book.get("market") or ""),
        best_bid=best_bid,
        best_ask=best_ask,
        spread=spread,
        bid_size=sum(size for _price, size in bids),
        ask_size=sum(size for _price, size in asks),
        min_order_size=_optional_float(book.get("min_order_size")),
        tick_size=_optional_float(book.get("tick_size")),
        neg_risk=bool(book.get("neg_risk", False)),
        book_hash=str(book.get("hash") or ""),
        raw_timestamp=str(book.get("timestamp") or book.get("updated_at") or ""),
    )


def _levels(levels: list[dict]) -> list[tuple[float, float]]:
    parsed = []
    for level in levels:
        price = _optional_float(level.get("price"))
        size = _optional_float(level.get("size"))
        if price and size and price > 0 and size > 0:
            parsed.append((price, size))
    return parsed


def _optional_float(value) -> Optional[float]:
    if value is None or value == "":
        return None
    try:
        return float(value)
    except (TypeError, ValueError):
        return None

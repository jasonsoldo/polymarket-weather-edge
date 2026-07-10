import os


HOST = "https://clob.polymarket.com"


def submit_limit_order(token_id: str, price: float, size: float, side: str) -> dict:
    client, types = _client()
    OrderArgs, OrderType, PartialCreateOrderOptions, Side = types
    sdk_side = Side.BUY if side == "BUY" else Side.SELL
    response = client.create_and_post_order(
        order_args=OrderArgs(token_id=token_id, price=price, size=size, side=sdk_side),
        options=PartialCreateOrderOptions(tick_size="0.01"),
        order_type=OrderType.GTC,
    )
    return _as_dict(response)


def get_order(order_id: str) -> dict:
    client, _types = _client()
    return _as_dict(client.get_order(order_id))


def _client():
    try:
        from py_clob_client_v2 import ApiCreds, ClobClient, OrderArgs, OrderType, PartialCreateOrderOptions, Side
    except ImportError as exc:
        raise RuntimeError("py-clob-client-v2 is not installed") from exc
    key = os.environ["POLYMARKET_PRIVATE_KEY"]
    api_key = os.environ.get("CLOB_API_KEY")
    api_secret = os.environ.get("CLOB_SECRET")
    api_passphrase = os.environ.get("CLOB_PASS_PHRASE")
    if api_key and api_secret and api_passphrase:
        creds = ApiCreds(api_key=api_key, api_secret=api_secret, api_passphrase=api_passphrase)
    else:
        l1 = ClobClient(host=HOST, chain_id=137, key=key)
        creds = l1.create_or_derive_api_key()
    return ClobClient(host=HOST, chain_id=137, key=key, creds=creds), (OrderArgs, OrderType, PartialCreateOrderOptions, Side)


def _as_dict(value) -> dict:
    if isinstance(value, dict):
        return value
    if hasattr(value, "model_dump"):
        return value.model_dump()
    if hasattr(value, "__dict__"):
        return dict(value.__dict__)
    return {"response": str(value)}

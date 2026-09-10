import pytest

from kalshi_bot.data.coinbase_public import (
    CoinbaseDataError,
    CoinbasePublicClient,
    coinbase_product,
    missing_buckets,
    parse_candles,
)


def test_coinbase_mapping_and_causal_parse():
    assert coinbase_product("xrp") == "XRP-USD"
    rows = parse_candles(
        [[100, 9, 11, 10, 10.5, 2], [300, 10, 12, 11, 11.5, 3]],
        asset_id="BTC",
        period_seconds=60,
        retrieved_at=500,
    )
    assert rows[0].available_at == 500
    assert missing_buckets(rows, start_ts=100, end_ts=400) == (160, 220, 280, 340)


def test_coinbase_rejects_unknown_asset_and_malformed_rows():
    with pytest.raises(CoinbaseDataError, match="outside"):
        coinbase_product("DOGE")
    with pytest.raises(CoinbaseDataError, match="malformed"):
        parse_candles([[1, 2]], asset_id="ETH", period_seconds=60, retrieved_at=2)


def test_coinbase_request_is_bounded():
    client = CoinbasePublicClient(client=object())
    with pytest.raises(CoinbaseDataError, match="300-bucket"):
        client.fetch_candles(
            product_id="BTC-USD", start_ts=0, end_ts=301 * 60, granularity_seconds=60
        )

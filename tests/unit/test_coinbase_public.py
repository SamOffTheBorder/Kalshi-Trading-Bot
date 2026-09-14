import httpx
import pytest

from kalshi_bot.data.coinbase_public import (
    CoinbaseDataError,
    CoinbasePublicClient,
    coinbase_product,
    missing_buckets,
    parse_candles,
    parse_trades,
)
from kalshi_bot.data.quality import coverage_report


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


def test_parse_trades_is_causal_and_sorted():
    rows = parse_trades(
        [
            {"trade_id": 2, "price": "101", "size": "1", "time": "2026-01-01T00:00:01Z"},
            {"trade_id": 1, "price": "100", "size": "2", "time": "2026-01-01T00:00:00Z"},
        ],
        asset_id="BTC",
        retrieved_at=1_767_225_601,
    )
    assert [r.trade_id for r in rows] == ["1", "2"]
    assert rows[0].available_at == rows[0].retrieved_at * 1_000


def test_parse_trades_rejects_malformed_or_non_positive_rows():
    with pytest.raises(CoinbaseDataError, match="missing a field"):
        parse_trades([{"trade_id": 1, "price": "1"}], asset_id="BTC", retrieved_at=0)
    with pytest.raises(CoinbaseDataError, match="non-positive"):
        parse_trades(
            [{"trade_id": 1, "price": "0", "size": "1", "time": "2026-01-01T00:00:00Z"}],
            asset_id="BTC",
            retrieved_at=0,
        )


def test_trade_gaps_are_reported_not_forward_filled():
    # Reuse the existing generic coverage_report rather than a bespoke
    # Coinbase-trade gap function -- a missing second is a gap, not a value.
    rows = parse_trades(
        [
            {"trade_id": 1, "price": "100", "size": "1", "time": "2026-01-01T00:00:00Z"},
            {"trade_id": 2, "price": "100", "size": "1", "time": "2026-01-01T00:00:05Z"},
        ],
        asset_id="BTC",
        retrieved_at=10,
    )
    report = coverage_report(
        [r.observed_at // 1_000 for r in rows],
        source="coinbase",
        native_symbol="BTC-USD",
        observation_type="trade",
        expected_step=1,
    )
    base = rows[0].observed_at // 1_000
    assert report.gaps == ((base + 1, base + 5),)


def test_fetch_trade_pages_paginates_and_respects_rate_limit_and_max_pages():
    calls: list[dict] = []

    def handler(request: httpx.Request) -> httpx.Response:
        calls.append(dict(request.url.params))
        after = request.url.params.get("after")
        if after is None:
            return httpx.Response(
                200, json=[{"trade_id": 2}], headers={"cb-after": "1"}
            )
        return httpx.Response(200, json=[{"trade_id": 1}])

    client = CoinbasePublicClient(client=httpx.Client(transport=httpx.MockTransport(handler)))
    sleeps: list[float] = []
    pages = list(
        client.fetch_trade_pages(
            product_id="BTC-USD", max_pages=5, sleep_fn=sleeps.append
        )
    )
    assert pages == [[{"trade_id": 2}], [{"trade_id": 1}]]
    assert len(calls) == 2
    # Only one inter-page sleep for two pages, and no sleep issued for the
    # last page fetched (no `after` cursor left to continue with).
    assert sleeps == [0.2]


def test_fetch_trade_pages_never_exceeds_max_pages():
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json=[{"trade_id": 1}], headers={"cb-after": "next"})

    client = CoinbasePublicClient(client=httpx.Client(transport=httpx.MockTransport(handler)))
    pages = list(
        client.fetch_trade_pages(product_id="BTC-USD", max_pages=3, sleep_fn=lambda _s: None)
    )
    assert len(pages) == 3


def test_fetch_trades_page_raises_on_rate_limit():
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(429)

    client = CoinbasePublicClient(client=httpx.Client(transport=httpx.MockTransport(handler)))
    with pytest.raises(CoinbaseDataError, match="rate limit"):
        client.fetch_trades_page(product_id="BTC-USD")


def test_fetch_trades_page_is_idempotent_for_repeated_page():
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json=[{"trade_id": 1}])

    client = CoinbasePublicClient(client=httpx.Client(transport=httpx.MockTransport(handler)))
    first, _ = client.fetch_trades_page(product_id="BTC-USD")
    second, _ = client.fetch_trades_page(product_id="BTC-USD")
    assert first == second

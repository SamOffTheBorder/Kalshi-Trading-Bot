import httpx
import pytest

from kalshi_bot.data.gemini_public import (
    GeminiDataError,
    GeminiPublicClient,
    gemini_symbol,
    missing_seconds,
    parse_trades,
)


def test_gemini_mapping_and_causal_parse():
    assert gemini_symbol("xrp") == "xrpusd"
    rows = parse_trades(
        [{"tid": 2, "price": "101", "amount": "1", "timestampms": 101_000}],
        asset_id="BTC",
        retrieved_at=200,
    )
    assert rows[0].available_at == 200_000
    assert rows[0].observed_at == 101_000


def test_gemini_rejects_unknown_asset_and_malformed_rows():
    with pytest.raises(GeminiDataError, match="outside"):
        gemini_symbol("DOGE")
    with pytest.raises(GeminiDataError, match="missing a field"):
        parse_trades([{"tid": 1, "price": "1"}], asset_id="BTC", retrieved_at=0)


def test_gemini_rejects_non_positive_price_or_amount():
    with pytest.raises(GeminiDataError, match="non-positive"):
        parse_trades(
            [{"tid": 1, "price": "0", "amount": "1", "timestampms": 1}],
            asset_id="BTC",
            retrieved_at=0,
        )


def test_gemini_trades_are_sorted_and_causal():
    rows = parse_trades(
        [
            {"tid": 2, "price": "101", "amount": "1", "timestampms": 50_000},
            {"tid": 1, "price": "100", "amount": "2", "timestampms": 10_000},
        ],
        asset_id="BTC",
        retrieved_at=100,
    )
    assert [r.trade_id for r in rows] == ["1", "2"]


def test_missing_seconds_never_fills():
    rows = parse_trades(
        [
            {"tid": 1, "price": "100", "amount": "1", "timestampms": 0},
            {"tid": 2, "price": "100", "amount": "1", "timestampms": 5_000},
        ],
        asset_id="BTC",
        retrieved_at=10,
    )
    assert missing_seconds(rows, start_ts=0, end_ts=6) == (1, 2, 3, 4)


def test_fetch_trades_page_passes_since_tid():
    calls: list[dict] = []

    def handler(request: httpx.Request) -> httpx.Response:
        calls.append(dict(request.url.params))
        return httpx.Response(200, json=[])

    client = GeminiPublicClient(client=httpx.Client(transport=httpx.MockTransport(handler)))
    client.fetch_trades_page(symbol="btcusd", since_tid=42)
    assert calls == [{"limit_trades": "500", "since_tid": "42"}]


def test_fetch_trades_page_raises_on_rate_limit():
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(429)

    client = GeminiPublicClient(client=httpx.Client(transport=httpx.MockTransport(handler)))
    with pytest.raises(GeminiDataError, match="rate limit"):
        client.fetch_trades_page(symbol="btcusd")


def test_fetch_trades_page_requires_symbol():
    client = GeminiPublicClient(client=object())
    with pytest.raises(GeminiDataError, match="required"):
        client.fetch_trades_page(symbol="")


def test_fetch_trade_pages_paginates_forward_and_stops_on_short_page():
    import kalshi_bot.data.gemini_public as gp

    pages_returned = [
        [{"tid": i, "price": "1", "amount": "1", "timestampms": i} for i in range(500)],
        [{"tid": 500, "price": "1", "amount": "1", "timestampms": 500}],
    ]
    calls: list[int | None] = []

    def handler(request: httpx.Request) -> httpx.Response:
        since = request.url.params.get("since_tid")
        calls.append(int(since) if since is not None else None)
        return httpx.Response(200, json=pages_returned[len(calls) - 1])

    client = GeminiPublicClient(client=httpx.Client(transport=httpx.MockTransport(handler)))
    sleeps: list[float] = []
    pages = list(
        client.fetch_trade_pages(
            symbol="btcusd", start_tid=0, max_pages=5, sleep_fn=sleeps.append
        )
    )
    assert len(pages) == 2
    assert calls == [0, 499]
    assert sleeps == [0.5]


def test_fetch_trade_pages_never_exceeds_max_pages():
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(
            200,
            json=[
                {"tid": i, "price": "1", "amount": "1", "timestampms": i}
                for i in range(500)
            ],
        )

    client = GeminiPublicClient(client=httpx.Client(transport=httpx.MockTransport(handler)))
    pages = list(
        client.fetch_trade_pages(
            symbol="btcusd", start_tid=0, max_pages=3, sleep_fn=lambda _s: None
        )
    )
    assert len(pages) == 3

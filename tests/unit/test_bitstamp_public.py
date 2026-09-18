import httpx
import pytest

from kalshi_bot.data.bitstamp_public import (
    BitstampDataError,
    BitstampPublicClient,
    bitstamp_currency_pair,
    missing_seconds,
    parse_trades,
)


def test_bitstamp_mapping_and_causal_parse():
    assert bitstamp_currency_pair("xrp") == "xrpusd"
    rows = parse_trades(
        [{"tid": "2", "price": "101", "amount": "1", "date": "101"}],
        asset_id="BTC",
        retrieved_at=200,
    )
    assert rows[0].available_at == 200_000
    assert rows[0].observed_at == 101_000


def test_bitstamp_rejects_unknown_asset_and_malformed_rows():
    with pytest.raises(BitstampDataError, match="outside"):
        bitstamp_currency_pair("DOGE")
    with pytest.raises(BitstampDataError, match="missing a field"):
        parse_trades([{"tid": 1, "price": "1"}], asset_id="BTC", retrieved_at=0)


def test_bitstamp_rejects_non_positive_price_or_amount():
    with pytest.raises(BitstampDataError, match="non-positive"):
        parse_trades(
            [{"tid": 1, "price": "0", "amount": "1", "date": "1"}],
            asset_id="BTC",
            retrieved_at=0,
        )


def test_bitstamp_trades_are_sorted_and_causal():
    rows = parse_trades(
        [
            {"tid": "2", "price": "101", "amount": "1", "date": "50"},
            {"tid": "1", "price": "100", "amount": "2", "date": "10"},
        ],
        asset_id="BTC",
        retrieved_at=100,
    )
    assert [r.trade_id for r in rows] == ["1", "2"]


def test_missing_seconds_never_fills():
    rows = parse_trades(
        [
            {"tid": "1", "price": "100", "amount": "1", "date": "0"},
            {"tid": "2", "price": "100", "amount": "1", "date": "5"},
        ],
        asset_id="BTC",
        retrieved_at=10,
    )
    assert missing_seconds(rows, start_ts=0, end_ts=6) == (1, 2, 3, 4)


def test_fetch_transactions_uses_window_param():
    calls: list[dict] = []

    def handler(request: httpx.Request) -> httpx.Response:
        calls.append(dict(request.url.params))
        return httpx.Response(200, json=[])

    client = BitstampPublicClient(client=httpx.Client(transport=httpx.MockTransport(handler)))
    client.fetch_transactions(currency_pair="btcusd", window="hour")
    assert calls == [{"time": "hour"}]


def test_fetch_transactions_raises_on_rate_limit():
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(429)

    client = BitstampPublicClient(client=httpx.Client(transport=httpx.MockTransport(handler)))
    with pytest.raises(BitstampDataError, match="rate limit"):
        client.fetch_transactions(currency_pair="btcusd")


def test_fetch_transactions_requires_currency_pair():
    client = BitstampPublicClient(client=object())
    with pytest.raises(BitstampDataError, match="required"):
        client.fetch_transactions(currency_pair="")

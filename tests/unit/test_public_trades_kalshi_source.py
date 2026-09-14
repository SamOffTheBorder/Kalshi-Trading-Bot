"""KalshiTradeSource: rediscovers open KXBTC15M-style markets on a timer and
pages each one's trade history forward from its last-seen observed_at. No
live network -- a fake client implements the same two read-only methods the
real `KalshiPublicClient` exposes.
"""

from __future__ import annotations

import pytest

from kalshi_bot.data.public_trades.kalshi_source import KalshiTradeSource, parse_trade


def _row(trade_id: str, created_time: str, ticker: str = "KXBTC15M-A") -> dict:
    return {
        "ticker": ticker,
        "trade_id": trade_id,
        "created_time": created_time,
        "yes_price_dollars": "0.3100",
        "count_fp": "100.00",
        "taker_side": "yes",
        "taker_book_side": "bid",
        "taker_outcome_side": "yes",
        "is_block_trade": False,
    }


def test_parse_trade_extracts_fields_and_converts_time():
    reading = parse_trade(_row("t1", "2026-01-01T00:00:00Z"))
    assert reading is not None
    assert reading.trade_id == "t1"
    assert reading.observed_at == 1_767_225_600
    assert reading.price_dollars == "0.3100"
    assert reading.quantity_fp == "100.00"
    assert reading.taker_side == "yes"


def test_parse_trade_rejects_unusable_rows():
    assert parse_trade(None) is None
    assert parse_trade({}) is None
    assert parse_trade({"ticker": "A", "trade_id": "t1"}) is None  # no created_time/price


class _FakeClient:
    def __init__(self, markets: list[dict], pages_by_ticker: dict[str, list[list[dict]]]) -> None:
        self._markets = markets
        self._pages_by_ticker = {k: list(v) for k, v in pages_by_ticker.items()}
        self._call_index: dict[str, int] = {}
        self.market_calls = 0
        self.trade_calls: list[tuple[str, int | None, str | None]] = []

    def get_markets(self, *, series_ticker=None, status=None):
        self.market_calls += 1
        return list(self._markets), None

    def get_trades(self, *, ticker=None, min_ts=None, max_ts=None, limit=1000, cursor=None):
        self.trade_calls.append((ticker, min_ts, cursor))
        pages = self._pages_by_ticker.get(ticker, [])
        idx = self._call_index.get(ticker, 0)
        if idx >= len(pages):
            return [], None
        rows = pages[idx]
        self._call_index[ticker] = idx + 1
        next_cursor = f"cursor-{idx + 1}" if idx + 1 < len(pages) else None
        return rows, next_cursor


def test_fetch_polls_every_discovered_open_market():
    client = _FakeClient(
        markets=[{"ticker": "KXBTC15M-A"}, {"ticker": "KXBTC15M-B"}],
        pages_by_ticker={
            "KXBTC15M-A": [[_row("a1", "2026-01-01T00:00:00Z", "KXBTC15M-A")]],
            "KXBTC15M-B": [[_row("b1", "2026-01-01T00:00:00Z", "KXBTC15M-B")]],
        },
    )
    source = KalshiTradeSource(client, series_ticker="KXBTC15M")
    readings = source.fetch({})
    assert {r.trade_id for r in readings} == {"a1", "b1"}
    assert client.market_calls == 1


def test_pagination_follows_cursor_until_short_page():
    full_page = [_row(f"t{i}", "2026-01-01T00:00:00Z") for i in range(3)]
    client = _FakeClient(
        markets=[{"ticker": "KXBTC15M-A"}],
        pages_by_ticker={"KXBTC15M-A": [full_page, [_row("t-last", "2026-01-01T00:00:05Z")]]},
    )
    source = KalshiTradeSource(client, series_ticker="KXBTC15M", page_limit=3)
    readings = source.fetch({})
    assert len(readings) == 4
    assert client.trade_calls[0] == ("KXBTC15M-A", None, None)
    assert client.trade_calls[1] == ("KXBTC15M-A", None, "cursor-1")


def test_since_by_ticker_is_passed_as_min_ts():
    client = _FakeClient(
        markets=[{"ticker": "KXBTC15M-A"}],
        pages_by_ticker={"KXBTC15M-A": [[_row("t1", "2026-01-01T00:00:10Z")]]},
    )
    source = KalshiTradeSource(client, series_ticker="KXBTC15M")
    source.fetch({"KXBTC15M-A": 1_767_225_600})
    assert client.trade_calls[0] == ("KXBTC15M-A", 1_767_225_600, None)


def test_max_pages_per_ticker_bounds_pagination():
    # Every page reports a cursor and is exactly page_limit long -> would
    # paginate forever without the bound.
    pages = [[_row(f"t{i}", "2026-01-01T00:00:00Z")] for i in range(10)]
    client = _FakeClient(markets=[{"ticker": "KXBTC15M-A"}], pages_by_ticker={"KXBTC15M-A": pages})
    source = KalshiTradeSource(
        client, series_ticker="KXBTC15M", page_limit=1, max_pages_per_ticker=3
    )
    readings = source.fetch({})
    assert len(readings) == 3
    assert len(client.trade_calls) == 3


def test_one_tickers_failure_does_not_stop_the_others():
    class _PartialFailure(_FakeClient):
        def get_trades(self, *, ticker=None, min_ts=None, max_ts=None, limit=1000, cursor=None):
            if ticker == "KXBTC15M-A":
                raise RuntimeError("timeout")
            return super().get_trades(
                ticker=ticker, min_ts=min_ts, max_ts=max_ts, limit=limit, cursor=cursor
            )

    client = _PartialFailure(
        markets=[{"ticker": "KXBTC15M-A"}, {"ticker": "KXBTC15M-B"}],
        pages_by_ticker={"KXBTC15M-B": [[_row("b1", "2026-01-01T00:00:00Z", "KXBTC15M-B")]]},
    )
    source = KalshiTradeSource(client, series_ticker="KXBTC15M")
    readings = source.fetch({})
    assert [r.trade_id for r in readings] == ["b1"]


def test_discovery_failure_keeps_the_previous_ticker_list():
    class _FlakyDiscovery(_FakeClient):
        def __init__(self, *a, **kw):
            super().__init__(*a, **kw)
            self._fail_next = False

        def get_markets(self, *, series_ticker=None, status=None):
            if self._fail_next:
                raise RuntimeError("timeout")
            return super().get_markets(series_ticker=series_ticker, status=status)

    client = _FlakyDiscovery(
        markets=[{"ticker": "KXBTC15M-A"}],
        pages_by_ticker={
            "KXBTC15M-A": [
                [_row("a1", "2026-01-01T00:00:00Z")],
                [_row("a2", "2026-01-01T00:00:05Z")],
            ]
        },
    )
    clock = {"t": 0.0}
    source = KalshiTradeSource(
        client, series_ticker="KXBTC15M", rediscover_every_s=100, now_fn=lambda: clock["t"]
    )
    source.fetch({})
    client._fail_next = True
    clock["t"] = 101.0
    readings = source.fetch({})
    assert [r.trade_id for r in readings] == ["a2"]


def test_requires_series_ticker():
    with pytest.raises(ValueError):
        KalshiTradeSource(_FakeClient([], {}), series_ticker="")


def test_rejects_nonpositive_max_pages():
    with pytest.raises(ValueError):
        KalshiTradeSource(_FakeClient([], {}), series_ticker="KXBTC15M", max_pages_per_ticker=0)

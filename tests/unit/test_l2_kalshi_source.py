"""KalshiL2Source: rediscovers open KXBTC15M-style markets on a timer and
polls each one's order book. No live network -- a fake client implements the
same two read-only methods the real `KalshiPublicClient` exposes.
"""

from __future__ import annotations

from kalshi_bot.data.l2.kalshi_source import KalshiL2Source, parse_orderbook


class _FakeClient:
    def __init__(self, markets: list[dict], orderbooks: dict[str, dict]) -> None:
        self._markets = markets
        self._orderbooks = orderbooks
        self.orderbook_calls: list[str] = []
        self.market_calls = 0

    def get_markets(self, *, series_ticker=None, status=None):
        self.market_calls += 1
        return list(self._markets), None

    def get_orderbook(self, market_ticker: str, *, depth=None):
        self.orderbook_calls.append(market_ticker)
        if market_ticker not in self._orderbooks:
            raise RuntimeError(f"no orderbook for {market_ticker}")
        return self._orderbooks[market_ticker]


def _ob(bid: str = "0.30", ask: str = "0.31") -> dict:
    return {"orderbook_fp": {"no_dollars": [[bid, "100"]], "yes_dollars": [[ask, "150"]]}}


def test_parse_orderbook_extracts_bids_and_asks():
    parsed = parse_orderbook(_ob())
    assert parsed == ([["0.30", "100"]], [["0.31", "150"]])


def test_parse_orderbook_rejects_unusable_shapes():
    assert parse_orderbook(None) is None
    assert parse_orderbook({}) is None
    assert parse_orderbook({"orderbook_fp": {}}) is None


def test_fetch_polls_every_discovered_open_market():
    client = _FakeClient(
        markets=[{"ticker": "KXBTC15M-A"}, {"ticker": "KXBTC15M-B"}],
        orderbooks={"KXBTC15M-A": _ob("0.30", "0.31"), "KXBTC15M-B": _ob("0.50", "0.51")},
    )
    clock = {"t": 0.0}
    source = KalshiL2Source(
        client, series_ticker="KXBTC15M", now_fn=lambda: clock["t"]
    )
    readings = source.fetch()
    assert {r.market_ticker for r in readings} == {"KXBTC15M-A", "KXBTC15M-B"}
    assert client.market_calls == 1


def test_rediscovery_only_happens_on_the_configured_cadence():
    client = _FakeClient(
        markets=[{"ticker": "KXBTC15M-A"}], orderbooks={"KXBTC15M-A": _ob()}
    )
    clock = {"t": 0.0}
    source = KalshiL2Source(
        client, series_ticker="KXBTC15M", rediscover_every_s=300, now_fn=lambda: clock["t"]
    )
    source.fetch()
    clock["t"] = 100.0  # inside the rediscovery window
    source.fetch()
    assert client.market_calls == 1
    clock["t"] = 301.0  # past the window -> rediscovers
    source.fetch()
    assert client.market_calls == 2


def test_one_markets_orderbook_failure_does_not_stop_the_others():
    client = _FakeClient(
        markets=[{"ticker": "KXBTC15M-A"}, {"ticker": "KXBTC15M-B"}],
        orderbooks={"KXBTC15M-B": _ob()},  # A has none -> raises inside get_orderbook
    )
    source = KalshiL2Source(client, series_ticker="KXBTC15M")
    readings = source.fetch()
    assert [r.market_ticker for r in readings] == ["KXBTC15M-B"]


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
        markets=[{"ticker": "KXBTC15M-A"}], orderbooks={"KXBTC15M-A": _ob()}
    )
    clock = {"t": 0.0}
    source = KalshiL2Source(
        client, series_ticker="KXBTC15M", rediscover_every_s=100, now_fn=lambda: clock["t"]
    )
    source.fetch()  # discovers KXBTC15M-A
    client._fail_next = True
    clock["t"] = 101.0
    readings = source.fetch()  # rediscovery fails -> keeps polling KXBTC15M-A
    assert [r.market_ticker for r in readings] == ["KXBTC15M-A"]


def test_requires_series_ticker():
    import pytest

    with pytest.raises(ValueError):
        KalshiL2Source(_FakeClient([], {}), series_ticker="")

from __future__ import annotations

import pytest

from kalshi_bot.backtest.perp_ledger import (
    FundingEvent,
    PerpBacktestError,
    PerpBacktestQuote,
    simulate_perp_trade,
)


def _quote(ts: int, *, bid: float, ask: float, mark: float, available_at: int | None = None):
    return PerpBacktestQuote(ts, ts if available_at is None else available_at, bid, ask, mark)


def test_long_round_trip_uses_ask_entry_bid_exit_and_realized_funding():
    trade = simulate_perp_trade(
        symbol="BTC-PERP",
        entry_quote=_quote(100, bid=99.0, ask=100.0, mark=99.5),
        exit_quote=_quote(200, bid=110.0, ask=111.0, mark=110.5),
        signed_size=1.0,
        collateral_usd=75.0,
        fee_rate=0.001,
        funding_events=(FundingEvent(150, 0.001, 100.0, -0.25),),
    )

    assert trade.entry_mark == 100.0
    assert trade.exit_mark == 110.0
    assert trade.gross_pnl_usd == pytest.approx(10.0)
    assert trade.funding_pnl_usd == pytest.approx(-0.25)
    assert trade.fees_usd == pytest.approx(0.21)
    assert trade.max_leverage_used > 1.0
    assert trade.min_distance_to_liquidation is not None


def test_short_round_trip_uses_bid_entry_ask_exit():
    trade = simulate_perp_trade(
        symbol="ETH-PERP",
        entry_quote=_quote(100, bid=100.0, ask=101.0, mark=100.5),
        exit_quote=_quote(200, bid=90.0, ask=91.0, mark=90.5),
        signed_size=-1.0,
        collateral_usd=100.0,
        fee_rate=0.0,
    )

    assert trade.entry_mark == 100.0
    assert trade.exit_mark == 91.0
    assert trade.gross_pnl_usd == pytest.approx(9.0)


@pytest.mark.parametrize(
    "change,reason",
    [
        (
            {"entry_quote": _quote(100, bid=99.0, ask=100.0, mark=99.5, available_at=101)},
            "unavailable",
        ),
        ({"entry_quote": _quote(100, bid=None, ask=100.0, mark=99.5)}, "one_sided"),
        ({"collateral_usd": 10.0}, "leverage"),
    ],
)
def test_simulator_rejects_non_executable_or_unsafe_inputs(change, reason):
    params = dict(
        symbol="BTC-PERP",
        entry_quote=_quote(100, bid=99.0, ask=100.0, mark=99.5),
        exit_quote=_quote(200, bid=110.0, ask=111.0, mark=110.5),
        signed_size=1.0,
        collateral_usd=100.0,
        fee_rate=0.001,
    )
    params.update(change)

    with pytest.raises(PerpBacktestError, match=reason):
        simulate_perp_trade(**params)

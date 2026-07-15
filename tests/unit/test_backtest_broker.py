"""BacktestBroker: pessimistic fills per side, fee at settlement, rejections."""

import pytest

from kalshi_bot.execution.backtest_broker import BacktestBroker, MarketBar
from kalshi_bot.execution.broker_protocol import BrokerAdapter, OrderRequest

TS = 1_784_000_000


def make_bar(**overrides) -> MarketBar:
    defaults = dict(
        market_ticker="KXBTCD-T-1",
        ts=TS,
        yes_bid_low=42,
        yes_bid_close=44,
        yes_ask_high=47,
        yes_ask_close=46,
    )
    defaults.update(overrides)
    return MarketBar(**defaults)


def make_broker(cash=100.0, fill_mode="pessimistic") -> BacktestBroker:
    broker = BacktestBroker(starting_cash_usd=cash, fill_mode=fill_mode)
    broker.set_current_bar(make_bar())
    return broker


def test_conforms_to_protocol():
    assert isinstance(make_broker(), BrokerAdapter)


# --- fill pricing ------------------------------------------------------------


async def test_yes_fills_at_bar_worst_ask():
    result = await make_broker().place_order(
        OrderRequest(market_ticker="KXBTCD-T-1", side="yes", quantity=10)
    )
    assert result.status == "filled"
    assert result.fill_price_cents == 47  # ask_high, not ask_close (46)


async def test_no_fills_at_complement_of_worst_bid():
    result = await make_broker().place_order(
        OrderRequest(market_ticker="KXBTCD-T-1", side="no", quantity=10)
    )
    assert result.status == "filled"
    assert result.fill_price_cents == 100 - 42  # lowest bid -> priciest NO


async def test_midpoint_mode_fills_between_quotes():
    result = await make_broker(fill_mode="midpoint").place_order(
        OrderRequest(market_ticker="KXBTCD-T-1", side="yes", quantity=10)
    )
    assert result.fill_price_cents == 45  # (44 + 46) / 2


async def test_cash_reduced_by_cost():
    broker = make_broker(cash=100.0)
    await broker.place_order(OrderRequest(market_ticker="KXBTCD-T-1", side="yes", quantity=10))
    assert await broker.get_account_balance() == pytest.approx(100.0 - 4.70)


# --- rejections ---------------------------------------------------------------


async def test_insufficient_funds_rejected():
    broker = make_broker(cash=1.0)
    result = await broker.place_order(
        OrderRequest(market_ticker="KXBTCD-T-1", side="yes", quantity=10)
    )
    assert result.status == "rejected"
    assert result.reject_reason == "insufficient_funds"


async def test_unknown_market_rejected():
    result = await make_broker().place_order(
        OrderRequest(market_ticker="NOPE", side="yes", quantity=1)
    )
    assert result.reject_reason == "no_market_data"


async def test_limit_price_respected():
    result = await make_broker().place_order(
        OrderRequest(market_ticker="KXBTCD-T-1", side="yes", quantity=1, limit_price_cents=46)
    )
    assert result.reject_reason == "limit_exceeded"  # pessimistic fill is 47


async def test_duplicate_position_rejected():
    broker = make_broker()
    await broker.place_order(OrderRequest(market_ticker="KXBTCD-T-1", side="yes", quantity=1))
    second = await broker.place_order(
        OrderRequest(market_ticker="KXBTCD-T-1", side="no", quantity=1)
    )
    assert second.reject_reason == "position_already_open"


async def test_unquoted_side_rejected():
    broker = BacktestBroker(starting_cash_usd=100.0)
    broker.set_current_bar(make_bar(yes_ask_high=None, yes_ask_close=None))
    result = await broker.place_order(
        OrderRequest(market_ticker="KXBTCD-T-1", side="yes", quantity=1)
    )
    assert result.reject_reason == "no_fillable_quote"


# --- settlement & fees -----------------------------------------------------------


async def test_winning_settlement_applies_fee():
    """Spec scenario: YES settles in the money -> PnL = gross - 7% fee.

    10 contracts at 47c: cost $4.70. Win -> gross = $5.30, fee = $0.371.
    """
    broker = make_broker(cash=100.0)
    await broker.place_order(OrderRequest(market_ticker="KXBTCD-T-1", side="yes", quantity=10))
    broker.settle_market("KXBTCD-T-1", "yes", TS + 3600)

    s = broker.settlements[0]
    assert s.won is True
    assert s.gross_pnl_usd == pytest.approx(5.30)
    assert s.fee_usd == pytest.approx(0.371)
    assert s.net_pnl_usd == pytest.approx(4.929)
    # cash: 100 - 4.70 + (10 - 0.371) = 104.929
    assert await broker.get_account_balance() == pytest.approx(104.929)


async def test_losing_settlement_no_fee():
    broker = make_broker(cash=100.0)
    await broker.place_order(OrderRequest(market_ticker="KXBTCD-T-1", side="yes", quantity=10))
    broker.settle_market("KXBTCD-T-1", "no", TS + 3600)

    s = broker.settlements[0]
    assert s.won is False
    assert s.fee_usd == 0.0
    assert s.net_pnl_usd == pytest.approx(-4.70)
    assert await broker.get_account_balance() == pytest.approx(95.30)


async def test_no_side_settlement():
    broker = make_broker(cash=100.0)
    await broker.place_order(OrderRequest(market_ticker="KXBTCD-T-1", side="no", quantity=5))
    # NO cost = 58c x 5 = $2.90; market resolves NO -> win
    broker.settle_market("KXBTCD-T-1", "no", TS + 3600)
    s = broker.settlements[0]
    assert s.won is True
    assert s.gross_pnl_usd == pytest.approx((1.0 - 0.58) * 5)


async def test_position_removed_after_settlement():
    broker = make_broker()
    await broker.place_order(OrderRequest(market_ticker="KXBTCD-T-1", side="yes", quantity=1))
    assert len(await broker.get_open_positions()) == 1
    broker.settle_market("KXBTCD-T-1", "yes", TS + 3600)
    assert await broker.get_open_positions() == []


def test_settle_without_position_is_noop():
    broker = make_broker()
    broker.settle_market("KXBTCD-T-1", "yes", TS)
    assert broker.settlements == []

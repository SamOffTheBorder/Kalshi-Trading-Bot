"""BacktestBroker: pessimistic fills per side, fee at entry, rejections."""

import pytest

from kalshi_bot.execution.backtest_broker import BacktestBroker, MarketBar
from kalshi_bot.execution.broker_protocol import BrokerAdapter, OrderRequest
from kalshi_bot.signals.fees import entry_fee_dollars

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
    """10 contracts @ 47c: stake $4.70, entry fee = ceil(0.07*0.47*0.53*10*100)/100
    = ceil(17.437)/100 = $0.18, charged at entry regardless of outcome."""
    broker = make_broker(cash=100.0)
    await broker.place_order(OrderRequest(market_ticker="KXBTCD-T-1", side="yes", quantity=10))
    assert await broker.get_account_balance() == pytest.approx(100.0 - 4.70 - 0.18)


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


async def test_winning_settlement_charges_entry_fee_not_settlement_fee():
    """Spec scenario: fee is charged AT ENTRY, win or lose — never at settlement.

    10 contracts at 47c: stake $4.70, entry fee $0.18 (see test_cash_reduced_by_cost).
    Win -> gross = (1-0.47)*10 = $5.30; net = gross - entry_fee = $5.12.
    """
    broker = make_broker(cash=100.0)
    await broker.place_order(OrderRequest(market_ticker="KXBTCD-T-1", side="yes", quantity=10))
    broker.settle_market("KXBTCD-T-1", "yes", TS + 3600)

    s = broker.settlements[0]
    assert s.won is True
    assert s.gross_pnl_usd == pytest.approx(5.30)
    assert s.fee_usd == pytest.approx(0.18)  # the entry fee, not a settlement cut
    assert s.net_pnl_usd == pytest.approx(5.12)
    # cash: 100 - 4.70 (stake) - 0.18 (entry fee) + 10 (payout on win) = 105.12
    assert await broker.get_account_balance() == pytest.approx(105.12)


async def test_losing_settlement_still_charged_the_entry_fee():
    """The fee already left the account at entry — settlement charges nothing
    further, but the fee already paid still shows up in net PnL on a loss."""
    broker = make_broker(cash=100.0)
    await broker.place_order(OrderRequest(market_ticker="KXBTCD-T-1", side="yes", quantity=10))
    broker.settle_market("KXBTCD-T-1", "no", TS + 3600)

    s = broker.settlements[0]
    assert s.won is False
    assert s.fee_usd == pytest.approx(0.18)  # same fee as the winning case — paid regardless
    assert s.net_pnl_usd == pytest.approx(-4.70 - 0.18)
    # cash: 100 - 4.70 (stake) - 0.18 (entry fee), nothing returned on a loss
    assert await broker.get_account_balance() == pytest.approx(95.12)


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


# --- early close (fixed-R stop/target exits, tasks.md 6.1/6.2/8.1) -----------


async def test_close_position_early_yes_side_target_hit():
    broker = make_broker(cash=100.0)
    result = await broker.place_order(
        OrderRequest(market_ticker="KXBTCD-T-1", side="yes", quantity=10)
    )
    assert result.fill_price_cents == 47
    cash_after_entry = await broker.get_account_balance()

    settlement = broker.close_position_early("KXBTCD-T-1", 60, TS + 300)
    assert settlement is not None
    assert settlement.won is True
    assert settlement.gross_pnl_usd == pytest.approx((0.60 - 0.47) * 10)
    # Early exit is a second taker order — proceeds are net of its fee
    # (kxbtc15m-validation-rebuild §2.4).
    exit_fee = entry_fee_dollars(60, 10)
    assert settlement.exit_fee_usd == pytest.approx(exit_fee)
    assert await broker.get_account_balance() == pytest.approx(
        cash_after_entry + 0.60 * 10 - exit_fee
    )


async def test_close_position_early_yes_side_stop_hit():
    broker = make_broker(cash=100.0)
    await broker.place_order(OrderRequest(market_ticker="KXBTCD-T-1", side="yes", quantity=10))
    settlement = broker.close_position_early("KXBTCD-T-1", 30, TS + 300)
    assert settlement is not None
    assert settlement.won is False
    assert settlement.gross_pnl_usd == pytest.approx((0.30 - 0.47) * 10)


async def test_close_position_early_no_side_gain_uses_no_exit_value():
    """kxbtc15m-validation-rebuild §2.4 scenario: a NO position closed at a
    HIGHER NO price than its NO entry price realizes the increase in NO
    value, net of both the entry and exit transaction fees.

    `close_position_early` takes the exit price in the HELD side's own
    convention. NO fill here = 100 - yes_bid_low(42) = 58c. Passing an exit
    of 68 (a NO price) is a 10c/contract NO gain."""
    broker = make_broker(cash=100.0)
    result = await broker.place_order(
        OrderRequest(market_ticker="KXBTCD-T-1", side="no", quantity=10)
    )
    entry_no = result.fill_price_cents
    assert entry_no == 58
    settlement = broker.close_position_early("KXBTCD-T-1", 68, TS + 300)
    assert settlement is not None
    assert settlement.won is True
    assert settlement.gross_pnl_usd == pytest.approx((0.68 - 0.58) * 10)
    assert settlement.entry_fee_usd == pytest.approx(entry_fee_dollars(58, 10))
    assert settlement.exit_fee_usd == pytest.approx(entry_fee_dollars(68, 10))
    assert settlement.net_pnl_usd == pytest.approx(
        settlement.gross_pnl_usd - settlement.entry_fee_usd - settlement.exit_fee_usd
    )


async def test_close_position_early_no_side_loss_when_no_price_falls():
    """The mirror of the gain case: a NO position closed BELOW its NO entry
    price is a loss (previously this direction was scored as a win — a
    side-convention bug §2.4 corrects)."""
    broker = make_broker(cash=100.0)
    result = await broker.place_order(
        OrderRequest(market_ticker="KXBTCD-T-1", side="no", quantity=10)
    )
    assert result.fill_price_cents == 58
    settlement = broker.close_position_early("KXBTCD-T-1", 48, TS + 300)
    assert settlement is not None
    assert settlement.won is False
    assert settlement.gross_pnl_usd == pytest.approx((0.48 - 0.58) * 10)


async def test_close_position_early_removes_the_position():
    broker = make_broker()
    await broker.place_order(OrderRequest(market_ticker="KXBTCD-T-1", side="yes", quantity=1))
    broker.close_position_early("KXBTCD-T-1", 60, TS + 300)
    assert await broker.get_open_positions() == []


async def test_close_position_early_charges_exit_leg_fee():
    broker = make_broker(cash=100.0)
    await broker.place_order(OrderRequest(market_ticker="KXBTCD-T-1", side="yes", quantity=10))
    settlement = broker.close_position_early("KXBTCD-T-1", 60, TS + 300)
    assert settlement is not None
    # An early exit is a second taker order and incurs its own fee on the
    # exit price (kxbtc15m-validation-rebuild §2.4). Both legs are recorded
    # separately; fee_usd is their sum; net = gross - entry_fee - exit_fee.
    assert settlement.entry_fee_usd == pytest.approx(entry_fee_dollars(47, 10))
    assert settlement.exit_fee_usd == pytest.approx(entry_fee_dollars(60, 10))
    assert settlement.exit_fee_usd > 0
    assert settlement.fee_usd == pytest.approx(settlement.entry_fee_usd + settlement.exit_fee_usd)
    assert settlement.net_pnl_usd == pytest.approx(
        settlement.gross_pnl_usd - settlement.entry_fee_usd - settlement.exit_fee_usd
    )


async def test_settle_market_hold_to_expiry_has_no_exit_fee():
    broker = make_broker(cash=100.0)
    await broker.place_order(OrderRequest(market_ticker="KXBTCD-T-1", side="yes", quantity=10))
    broker.settle_market("KXBTCD-T-1", "yes", TS + 900)
    s = broker.settlements[-1]
    assert s.exit_fee_usd == 0.0
    assert s.net_pnl_usd == pytest.approx(s.gross_pnl_usd - s.entry_fee_usd)


def test_close_position_early_without_position_is_noop():
    broker = make_broker()
    assert broker.close_position_early("KXBTCD-T-1", 50, TS) is None
    assert broker.settlements == []


async def test_close_position_early_appends_to_settlements():
    broker = make_broker()
    await broker.place_order(OrderRequest(market_ticker="KXBTCD-T-1", side="yes", quantity=1))
    broker.close_position_early("KXBTCD-T-1", 60, TS + 300)
    assert len(broker.settlements) == 1
    assert broker.settlements[0].settled_ts == TS + 300


# --- liquidity cap ------------------------------------------------------------


async def test_fill_capped_at_fraction_of_bar_volume():
    broker = BacktestBroker(starting_cash_usd=1000.0, liquidity_cap_frac=0.25)
    broker.set_current_bar(make_bar(volume=40))
    result = await broker.place_order(
        OrderRequest(market_ticker="KXBTCD-T-1", side="yes", quantity=100)
    )
    assert result.status == "filled"
    assert result.quantity == 10  # 25% of 40, not the requested 100


async def test_order_within_cap_fills_in_full():
    broker = BacktestBroker(starting_cash_usd=1000.0, liquidity_cap_frac=0.25)
    broker.set_current_bar(make_bar(volume=40))
    result = await broker.place_order(
        OrderRequest(market_ticker="KXBTCD-T-1", side="yes", quantity=5)
    )
    assert result.status == "filled"
    assert result.quantity == 5


async def test_zero_volume_bar_rejects():
    broker = BacktestBroker(starting_cash_usd=1000.0)
    broker.set_current_bar(make_bar(volume=0))
    result = await broker.place_order(
        OrderRequest(market_ticker="KXBTCD-T-1", side="yes", quantity=10)
    )
    assert result.status == "rejected"
    assert result.reject_reason == "insufficient_liquidity"


async def test_unknown_volume_is_uncapped():
    broker = BacktestBroker(starting_cash_usd=1000.0)
    broker.set_current_bar(make_bar(volume=None))
    result = await broker.place_order(
        OrderRequest(market_ticker="KXBTCD-T-1", side="yes", quantity=100)
    )
    assert result.status == "filled"
    assert result.quantity == 100


def test_liquidity_cap_frac_validation():
    with pytest.raises(ValueError):
        BacktestBroker(starting_cash_usd=100.0, liquidity_cap_frac=0.0)
    with pytest.raises(ValueError):
        BacktestBroker(starting_cash_usd=100.0, liquidity_cap_frac=1.5)


# --- execution model: taker-only (kxbtc15m-validation-rebuild §2.5) -------------


def make_maker_bar(**overrides) -> MarketBar:
    """A bar carrying the high/low fields the OLD candle-range maker
    inference used (yes_ask_low, yes_bid_high). §2.5 removed that inference:
    these fields no longer produce a maker fill. Kept as a fixture so the
    tests below can prove a maker order is rejected EVEN when the range
    would previously have "touched" it."""
    defaults = dict(
        market_ticker="KXBTCD-T-1",
        ts=TS,
        yes_bid_low=42,
        yes_bid_close=44,
        yes_ask_high=47,
        yes_ask_close=46,
        yes_ask_low=43,
        yes_bid_high=58,
    )
    defaults.update(overrides)
    return MarketBar(**defaults)


async def test_maker_order_is_unfilled_even_when_candle_range_would_touch_it():
    """§2.5 scenario: a maker order lacking a validated queue/partial-fill
    model and with no observed fill is recorded UNFILLED — a candle range
    that crosses the limit is not fill evidence. Here yes_ask_low=43 < the
    44c limit (the old model would have "filled" it); the order is still
    rejected."""
    for side, limit in (("yes", 44), ("no", 44)):
        broker = BacktestBroker(starting_cash_usd=100.0)
        broker.set_current_bar(make_maker_bar())
        result = await broker.place_order(
            OrderRequest(
                market_ticker="KXBTCD-T-1",
                side=side,
                quantity=10,
                limit_price_cents=limit,
                execution_style="maker",
            )
        )
        assert result.status == "rejected"
        assert result.reject_reason == "maker_unfilled_no_validated_model"
    # cash untouched — nothing was staked
    assert await broker.get_account_balance() == pytest.approx(100.0)


async def test_maker_order_rejected_before_limit_price_check():
    """The taker-only rejection is unconditional — it does not depend on a
    limit price being supplied."""
    broker = BacktestBroker(starting_cash_usd=100.0)
    broker.set_current_bar(make_maker_bar())
    result = await broker.place_order(
        OrderRequest(market_ticker="KXBTCD-T-1", side="yes", quantity=10, execution_style="maker")
    )
    assert result.status == "rejected"
    assert result.reject_reason == "maker_unfilled_no_validated_model"


async def test_taker_is_the_only_fill_path():
    """The default (taker) order still fills at the bar's worst plausible
    price and pays the taker fee — 10 @ 44c: stake $4.40, fee $0.18."""
    broker = BacktestBroker(starting_cash_usd=100.0)
    broker.set_current_bar(make_bar(yes_ask_high=44))
    result = await broker.place_order(
        OrderRequest(market_ticker="KXBTCD-T-1", side="yes", quantity=10)
    )
    assert result.status == "filled"
    assert result.fill_price_cents == 44
    assert await broker.get_account_balance() == pytest.approx(100.0 - 4.40 - 0.18)

"""kxbtc15m-validation-rebuild §2.6: end-to-end scenario accounting through
the ENGINE (not just the broker unit tests) — NO-side gains, early-close
double-leg fees, and the fee/PnL fields the `SimulatedTrade` audit row must
carry for each.

The broker's own unit tests (`tests/unit/test_backtest_broker.py`) already
pin the fill/settlement arithmetic in isolation. These tests confirm the
engine wires it through: the queued-fill path, the fixed-R exit path, and
the settlement path all populate `entry_fee_usd` / `exit_fee_usd` / `fee_usd`
/ `net_pnl_usd` consistently on the persisted trade row.

Timestamp-causality scenarios live in `test_engine_causal_timeline.py`;
maker-order rejection lives in the broker unit tests (the engine never
submits `execution_style="maker"`). Precision-retention of exchange values
is covered by the data-contract layer (kxbtc15m-validation-rebuild §1.2).
"""

from __future__ import annotations

import pytest
from sqlalchemy import create_engine, select
from sqlalchemy.orm import Session, sessionmaker

from kalshi_bot.backtest.engine import BacktestEngine
from kalshi_bot.execution.backtest_broker import BacktestBroker
from kalshi_bot.risk.drawdown_guard import DrawdownGuard
from kalshi_bot.signals.fees import TAKER_FEE_COEFFICIENT, entry_fee_dollars
from kalshi_bot.storage.models import Base, Candle, KalshiMarket, SimulatedTrade, SpotCandle
from kalshi_bot.strategy.base import Action, Decision, StrategyContext

BASE = 1_784_000_000
DECIDE_TS = BASE + 60
FILL_TS = BASE + 120
EXIT_TS = BASE + 240
MARKET_CLOSE = BASE + 900
END = BASE + 1_200


class OneShotStrategy:
    """Emits a single configurable Decision on the first candle, HOLD after.
    `action`, `fair_probability`, and optional fixed-R cents are passed in so
    one class covers every scenario below."""

    name = "one_shot"

    def __init__(
        self,
        action: Action,
        *,
        fair_probability: float = 0.90,
        stop_cents: int | None = None,
        target_cents: int | None = None,
    ) -> None:
        self._action = action
        self._fp = fair_probability
        self._stop = stop_cents
        self._target = target_cents
        self._fired = False

    def evaluate(self, context: StrategyContext) -> Decision:
        if self._fired or context.yes_ask_cents is None or context.yes_bid_cents is None:
            return Decision(
                action=Action.HOLD,
                market_ticker=context.market_ticker,
                strategy_name=self.name,
                hold_reason="done",
            )
        self._fired = True
        entry = (
            context.yes_ask_cents
            if self._action == Action.BUY_YES
            else 100 - context.yes_bid_cents
        )
        return Decision(
            action=self._action,
            market_ticker=context.market_ticker,
            strategy_name=self.name,
            fair_probability=self._fp,
            bs_probability=self._fp,
            entry_price_cents=entry,
            stop_price_cents=self._stop,
            target_price_cents=self._target,
        )


@pytest.fixture
def session() -> Session:
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)
    return sessionmaker(bind=engine, expire_on_commit=False)()


def _candle(
    end_ts: int,
    *,
    ask_high: int = 42,
    ask_close: int = 40,
    bid_low: int = 38,
    bid_close: int = 39,
    price_high: int | None = None,
    price_low: int | None = None,
) -> Candle:
    return Candle(
        market_ticker="M1",
        series_ticker="KXBTC15M",
        period_minutes=1,
        end_period_ts=end_ts,
        price_open=ask_close,
        price_high=price_high if price_high is not None else ask_high,
        price_low=price_low if price_low is not None else bid_low,
        price_close=ask_close,
        yes_bid_low=bid_low,
        yes_bid_close=bid_close,
        yes_ask_high=ask_high,
        yes_ask_close=ask_close,
        volume=100_000,
        open_interest=5_000,
    )


def _spot(session: Session) -> None:
    for i in range(40):
        session.add(
            SpotCandle(
                exchange="coinbase",
                symbol="BTC-USD",
                period_minutes=1440,
                open_ts=BASE - (40 - i) * 86_400,
                open=100_000,
                high=100_000,
                low=100_000,
                close=100_000,
                volume=1,
            )
        )
    session.add(
        SpotCandle(
            exchange="coinbase",
            symbol="BTC-USD",
            period_minutes=60,
            open_ts=BASE - 3600,
            open=100_000,
            high=100_000,
            low=100_000,
            close=100_000,
            volume=1,
        )
    )


def _market(session: Session, *, result: str) -> None:
    session.add(
        KalshiMarket(
            ticker="M1",
            series_ticker="KXBTC15M",
            strike_type="greater",
            floor_strike=100_000.0,
            open_ts=BASE,
            close_ts=MARKET_CLOSE,
            status="settled",
            result=result,
        )
    )


async def _run(session: Session, strategy: OneShotStrategy):
    broker = BacktestBroker(starting_cash_usd=1000.0)
    engine = BacktestEngine(
        strategy=strategy,
        broker=broker,
        session=session,
        starting_cash_usd=1000.0,
        kelly_fraction=0.25,
        max_position_pct=0.05,
        guard=DrawdownGuard(pause_pct=0.25, halt_pct=0.40, initial_equity=1000.0),
        candle_period_minutes=1,
        eval_stride_s=1,
    )
    return await engine.run(start_ts=BASE, end_ts=END, split_ts=BASE + 500)


# --- NO-side gain, end to end -------------------------------------------------


async def test_no_side_position_settling_no_is_a_win_with_entry_only_fee(session):
    """BUY_NO on a bid_low=38 candle -> NO fill at 100-38 = 62c. Market
    settles NO -> the position wins. Held to expiry: entry fee only, no exit
    fee. The persisted trade row's fee fields must reflect exactly that."""
    _market(session, result="no")
    session.add_all([_candle(DECIDE_TS), _candle(FILL_TS)])
    _spot(session)
    session.commit()

    await _run(session, OneShotStrategy(Action.BUY_NO))

    trade = session.execute(select(SimulatedTrade)).scalars().one()
    assert trade.side == "no"
    assert trade.entry_price_cents == 62  # 100 - bid_low(38)
    assert trade.status == "settled_won"

    qty = trade.quantity
    expected_entry_fee = entry_fee_dollars(62, qty, coefficient=TAKER_FEE_COEFFICIENT)
    expected_gross = (1.0 - 0.62) * qty  # NO wins: pays out 1.00, cost 0.62
    assert trade.entry_fee_usd == pytest.approx(expected_entry_fee)
    assert trade.exit_fee_usd == pytest.approx(0.0)  # held to expiry, no exit order
    assert trade.fee_usd == pytest.approx(expected_entry_fee)
    assert trade.gross_pnl_usd == pytest.approx(expected_gross)
    assert trade.net_pnl_usd == pytest.approx(expected_gross - expected_entry_fee)


async def test_no_side_position_settling_yes_is_a_loss(session):
    """The mirror: BUY_NO, market settles YES -> the NO position loses its
    whole stake. Still entry-fee-only."""
    _market(session, result="yes")
    session.add_all([_candle(DECIDE_TS), _candle(FILL_TS)])
    _spot(session)
    session.commit()

    await _run(session, OneShotStrategy(Action.BUY_NO))

    trade = session.execute(select(SimulatedTrade)).scalars().one()
    assert trade.side == "no"
    assert trade.status == "settled_lost"
    qty = trade.quantity
    expected_entry_fee = entry_fee_dollars(62, qty, coefficient=TAKER_FEE_COEFFICIENT)
    assert trade.gross_pnl_usd == pytest.approx(-0.62 * qty)
    assert trade.exit_fee_usd == pytest.approx(0.0)
    assert trade.net_pnl_usd == pytest.approx(-0.62 * qty - expected_entry_fee)


# --- early-close double-leg fee, end to end ---------------------------------


async def test_fixed_r_early_close_records_both_leg_fees(session):
    """A fixed-R target exit is a SECOND taker order. The persisted trade
    row must carry a non-zero entry_fee_usd AND a non-zero exit_fee_usd,
    with fee_usd their sum and net_pnl_usd = gross - entry_fee - exit_fee
    (kxbtc15m-validation-rebuild §2.4)."""
    _market(session, result="no")  # opposite of the early-exit win: proves pre-emption
    # entry candles: ask 40c/42c-high -> YES fill at 42c, target = 42+8 = 50c
    session.add_all([_candle(DECIDE_TS), _candle(FILL_TS)])
    # exit candle at minute 3: trade price reaches 55 -> crosses the 50c target
    session.add(
        _candle(
            EXIT_TS,
            ask_high=55,
            ask_close=52,
            bid_low=50,
            bid_close=51,
            price_high=55,
            price_low=48,
        )
    )
    _spot(session)
    session.commit()

    await _run(
        session,
        OneShotStrategy(Action.BUY_YES, stop_cents=32, target_cents=50),
    )

    trade = session.execute(select(SimulatedTrade)).scalars().one()
    assert trade.status == "closed_early"
    assert trade.exit_price_cents == 50  # the target level itself
    qty = trade.quantity

    expected_entry_fee = entry_fee_dollars(42, qty, coefficient=TAKER_FEE_COEFFICIENT)
    expected_exit_fee = entry_fee_dollars(50, qty, coefficient=TAKER_FEE_COEFFICIENT)
    expected_gross = (0.50 - 0.42) * qty
    assert trade.entry_fee_usd == pytest.approx(expected_entry_fee)
    assert trade.exit_fee_usd == pytest.approx(expected_exit_fee)
    assert trade.exit_fee_usd > 0
    assert trade.fee_usd == pytest.approx(expected_entry_fee + expected_exit_fee)
    assert trade.gross_pnl_usd == pytest.approx(expected_gross)
    assert trade.net_pnl_usd == pytest.approx(
        expected_gross - expected_entry_fee - expected_exit_fee
    )


async def test_fixed_r_early_close_at_a_loss_still_records_both_leg_fees(session):
    """A stop-out is also a second taker order: both fees recorded even
    though the trade lost money."""
    _market(session, result="yes")
    session.add_all([_candle(DECIDE_TS), _candle(FILL_TS)])
    # exit candle: trade price falls to 29 -> crosses the 32c stop (42-10)
    session.add(
        _candle(
            EXIT_TS,
            ask_high=34,
            ask_close=31,
            bid_low=29,
            bid_close=30,
            price_high=36,
            price_low=29,
        )
    )
    _spot(session)
    session.commit()

    await _run(
        session,
        OneShotStrategy(Action.BUY_YES, stop_cents=32, target_cents=52),
    )

    trade = session.execute(select(SimulatedTrade)).scalars().one()
    assert trade.status == "closed_early"
    assert trade.exit_price_cents == 32  # the stop level
    qty = trade.quantity
    expected_entry_fee = entry_fee_dollars(42, qty, coefficient=TAKER_FEE_COEFFICIENT)
    expected_exit_fee = entry_fee_dollars(32, qty, coefficient=TAKER_FEE_COEFFICIENT)
    expected_gross = (0.32 - 0.42) * qty  # negative
    assert expected_gross < 0
    assert trade.entry_fee_usd == pytest.approx(expected_entry_fee)
    assert trade.exit_fee_usd == pytest.approx(expected_exit_fee)
    assert trade.exit_fee_usd > 0
    assert trade.fee_usd == pytest.approx(expected_entry_fee + expected_exit_fee)
    assert trade.net_pnl_usd == pytest.approx(
        expected_gross - expected_entry_fee - expected_exit_fee
    )


async def test_hold_to_expiry_settlement_has_no_exit_fee(session):
    """Contrast case: a YES position that rides to settlement (no fixed-R
    levels) pays only the entry fee — exit_fee_usd is exactly 0."""
    _market(session, result="yes")
    session.add_all([_candle(DECIDE_TS), _candle(FILL_TS)])
    _spot(session)
    session.commit()

    await _run(session, OneShotStrategy(Action.BUY_YES))

    trade = session.execute(select(SimulatedTrade)).scalars().one()
    assert trade.status == "settled_won"
    assert trade.exit_fee_usd == pytest.approx(0.0)
    assert trade.fee_usd == pytest.approx(trade.entry_fee_usd)
    assert trade.net_pnl_usd == pytest.approx(trade.gross_pnl_usd - trade.entry_fee_usd)

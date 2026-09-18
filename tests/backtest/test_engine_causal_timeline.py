"""kxbtc15m-validation-rebuild §2.1/§2.2: the backtest engine must not let a
decision consume a bar's close and then execute an order *inside that same
bar*. A decision made from the candle ending at ts is queued and executes
only against a LATER candle for that market (next bar or later); its fill
price is that later bar's price, not the decision bar's.

These are the look-ahead regression tests the section calls for. Each one is
constructed so the OLD (same-bar) behaviour and the NEW (next-bar) behaviour
give visibly different, hand-checkable results.
"""

from __future__ import annotations

import pytest
from sqlalchemy import create_engine, select
from sqlalchemy.orm import Session, sessionmaker

from kalshi_bot.backtest.engine import BacktestEngine
from kalshi_bot.execution.backtest_broker import BacktestBroker
from kalshi_bot.risk.drawdown_guard import DrawdownGuard
from kalshi_bot.storage.models import Base, Candle, KalshiMarket, SimulatedTrade, SpotCandle
from kalshi_bot.strategy.base import Action, Decision, StrategyContext

BASE = 1_784_000_000
DECIDE_TS = BASE + 60
NEXT_TS = BASE + 120
THIRD_TS = BASE + 180
MARKET_CLOSE = BASE + 900
END = BASE + 1_200


class BuyOnceStrategy:
    """BUY_YES on the first candle it sees, HOLD forever after. No entry
    band, no fixed-R exit — a bare directional entry, so the only thing
    under test is WHEN and at WHAT PRICE the fill lands."""

    name = "buy_once"

    def __init__(self) -> None:
        self._fired = False

    def evaluate(self, context: StrategyContext) -> Decision:
        if self._fired or context.yes_ask_cents is None:
            return Decision(
                action=Action.HOLD,
                market_ticker=context.market_ticker,
                strategy_name=self.name,
                hold_reason="done",
            )
        self._fired = True
        return Decision(
            action=Action.BUY_YES,
            market_ticker=context.market_ticker,
            strategy_name=self.name,
            fair_probability=0.90,
            bs_probability=0.90,
            entry_price_cents=context.yes_ask_cents,
        )


@pytest.fixture
def session() -> Session:
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)
    return sessionmaker(bind=engine, expire_on_commit=False)()


def _candle(end_ts: int, *, ask_high: int, ask_close: int, bid_low: int, bid_close: int) -> Candle:
    return Candle(
        market_ticker="M1",
        series_ticker="KXBTC15M",
        period_minutes=1,
        end_period_ts=end_ts,
        price_open=ask_close,
        price_high=ask_high,
        price_low=bid_low,
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


def _market(session: Session, *, result: str = "yes", close_ts: int = MARKET_CLOSE) -> None:
    session.add(
        KalshiMarket(
            ticker="M1",
            series_ticker="KXBTC15M",
            strike_type="greater",
            floor_strike=100_000.0,
            open_ts=BASE,
            close_ts=close_ts,
            status="settled",
            result=result,
        )
    )


async def _run(session: Session, *, end_ts: int = END, split_ts: int = BASE + 500):
    broker = BacktestBroker(starting_cash_usd=1000.0)
    engine = BacktestEngine(
        strategy=BuyOnceStrategy(),
        broker=broker,
        session=session,
        starting_cash_usd=1000.0,
        kelly_fraction=0.25,
        max_position_pct=0.05,
        guard=DrawdownGuard(pause_pct=0.25, halt_pct=0.40, initial_equity=1000.0),
        candle_period_minutes=1,
        eval_stride_s=1,
    )
    return await engine.run(start_ts=BASE, end_ts=end_ts, split_ts=split_ts)


async def test_decision_does_not_fill_against_its_own_bar(session):
    """One candle only: the decision is made, queued, and — with no later
    candle to execute against before the market closes — never fills. The
    old engine would have filled it against this very bar."""
    _market(session)
    session.add(_candle(DECIDE_TS, ask_high=42, ask_close=40, bid_low=38, bid_close=39))
    _spot(session)
    session.commit()

    result = await _run(session)

    assert session.execute(select(SimulatedTrade)).scalars().all() == []
    assert result.final_equity == pytest.approx(1000.0)  # nothing spent


async def test_fill_uses_the_next_bar_price_not_the_decision_bar_price(session):
    """Decision bar ask_high = 42c; next bar ask_high = 60c. A next-bar fill
    must pay 60c (the pessimistic price of the bar it actually executed in),
    NOT 42c. This is the exact leak §2.2 closes: the old engine paid 42c,
    a price only observable at a moment the order could not yet have been
    working."""
    _market(session)
    session.add(_candle(DECIDE_TS, ask_high=42, ask_close=40, bid_low=38, bid_close=39))
    session.add(_candle(NEXT_TS, ask_high=60, ask_close=58, bid_low=55, bid_close=57))
    _spot(session)
    session.commit()

    await _run(session)

    trades = session.execute(select(SimulatedTrade)).scalars().all()
    assert len(trades) == 1
    assert trades[0].entry_price_cents == 60  # next bar's ask_high, not 42
    assert trades[0].entry_ts == NEXT_TS


async def test_fill_lands_on_first_available_later_bar(session):
    """A gap between the decision bar and the next candle for the market is
    fine — the order simply waits and fills on the first later candle that
    exists (here THIRD_TS, with NEXT_TS absent)."""
    _market(session)
    session.add(_candle(DECIDE_TS, ask_high=42, ask_close=40, bid_low=38, bid_close=39))
    session.add(_candle(THIRD_TS, ask_high=44, ask_close=43, bid_low=41, bid_close=42))
    _spot(session)
    session.commit()

    await _run(session)

    trades = session.execute(select(SimulatedTrade)).scalars().all()
    assert len(trades) == 1
    assert trades[0].entry_ts == THIRD_TS
    assert trades[0].entry_price_cents == 44


async def test_queued_entry_expires_if_market_closes_before_next_candle(session):
    """Decision bar exists; the market then closes before any next candle.
    The queued order never gets a fill event and is dropped — no phantom
    entry at settlement, no error."""
    _market(session, close_ts=NEXT_TS)  # closes at the would-be fill bar
    session.add(_candle(DECIDE_TS, ask_high=42, ask_close=40, bid_low=38, bid_close=39))
    session.add(_candle(NEXT_TS, ask_high=42, ask_close=40, bid_low=38, bid_close=39))
    _spot(session)
    session.commit()

    result = await _run(session, end_ts=END)

    assert session.execute(select(SimulatedTrade)).scalars().all() == []
    assert result.final_equity == pytest.approx(1000.0)


async def test_liveness_is_checked_against_the_fill_bar_not_the_decision_bar(session):
    """Decision bar is a healthy live quote; the next (fill) bar has gone
    dead (zero OI / 0c-1c shell). The entry must be dropped as a dead quote
    — the liveness gate runs at FILL time, against the fill bar."""
    _market(session)
    session.add(_candle(DECIDE_TS, ask_high=42, ask_close=40, bid_low=38, bid_close=39))
    dead = Candle(
        market_ticker="M1",
        series_ticker="KXBTC15M",
        period_minutes=1,
        end_period_ts=NEXT_TS,
        price_open=1,
        price_high=1,
        price_low=0,
        price_close=1,
        yes_bid_low=0,
        yes_bid_close=0,
        yes_ask_high=1,
        yes_ask_close=1,
        volume=0,
        open_interest=0,
    )
    session.add(dead)
    session.add(_candle(THIRD_TS, ask_high=42, ask_close=40, bid_low=38, bid_close=39))
    _spot(session)
    session.commit()

    await _run(session)

    # The order was queued at DECIDE_TS, drained at NEXT_TS, and rejected
    # there for the dead quote. It is NOT re-queued afterwards (the strategy
    # only fires once), so THIRD_TS's healthy quote does not rescue it.
    assert session.execute(select(SimulatedTrade)).scalars().all() == []


async def test_guard_halt_between_decision_and_fill_blocks_the_entry(session):
    """If the drawdown guard HALTs at the fill timestep (before the drain),
    a queued entry decided while the guard was NORMAL must not execute —
    gates are fill-time, not decision-time."""
    _market(session)
    session.add(_candle(DECIDE_TS, ask_high=42, ask_close=40, bid_low=38, bid_close=39))
    session.add(_candle(NEXT_TS, ask_high=42, ask_close=40, bid_low=38, bid_close=39))
    _spot(session)
    session.commit()

    broker = BacktestBroker(starting_cash_usd=1000.0)
    guard = DrawdownGuard(pause_pct=0.25, halt_pct=0.40, initial_equity=1000.0)
    guard.update(500.0)  # 50% drawdown -> HALTED before the run even starts
    assert not guard.allows_new_entries()
    engine = BacktestEngine(
        strategy=BuyOnceStrategy(),
        broker=broker,
        session=session,
        starting_cash_usd=1000.0,
        kelly_fraction=0.25,
        max_position_pct=0.05,
        guard=guard,
        candle_period_minutes=1,
        eval_stride_s=1,
    )
    await engine.run(start_ts=BASE, end_ts=END, split_ts=BASE + 500)

    assert session.execute(select(SimulatedTrade)).scalars().all() == []

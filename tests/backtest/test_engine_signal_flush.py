"""Periodic signal flush (tasks.md 8.1 performance finding): a long run at a
fine eval_stride_s must not let pending SignalRecord INSERTs accumulate
unbounded, AND must not corrupt in-flight SimulatedTrade mutations that
happen after a mid-run flush."""

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
MARKET_CLOSE = BASE + 900
END = BASE + 1_200


class EnterOnceThenHoldStrategy:
    """Enters on the FIRST evaluation, then HOLDs on every subsequent one —
    enough HOLDs to trigger at least one mid-run flush with
    signal_flush_interval=2, while still tracking exactly one open
    SimulatedTrade that must be mutated correctly at settlement despite the
    flush(es) that happened in between."""

    name = "enter_once"

    def __init__(self) -> None:
        self._fired = False

    def evaluate(self, context: StrategyContext) -> Decision:
        if not self._fired and context.yes_ask_cents is not None:
            self._fired = True
            return Decision(
                action=Action.BUY_YES,
                market_ticker=context.market_ticker,
                strategy_name=self.name,
                fair_probability=0.9,
                bs_probability=0.9,
                entry_price_cents=context.yes_ask_cents,
            )
        return Decision(
            action=Action.HOLD,
            market_ticker=context.market_ticker,
            strategy_name=self.name,
            hold_reason="already_traded",
        )


@pytest.fixture
def session() -> Session:
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)
    return sessionmaker(bind=engine, expire_on_commit=False)()


async def test_mid_run_flush_does_not_corrupt_trade_settlement(session):
    session.add(
        KalshiMarket(
            ticker="M1",
            series_ticker="KXBTCD",
            strike_type="greater",
            floor_strike=100_000.0,
            open_ts=BASE,
            close_ts=MARKET_CLOSE,
            status="settled",
            result="yes",
        )
    )
    # Several 1-min candles so the strategy is re-evaluated (and HOLDs)
    # enough times to trigger multiple flushes at signal_flush_interval=2.
    for minute in range(1, 8):
        session.add(
            Candle(
                market_ticker="M1",
                series_ticker="KXBTCD",
                period_minutes=1,
                end_period_ts=BASE + minute * 60,
                price_open=40,
                price_high=41,
                price_low=39,
                price_close=40,
                yes_bid_low=38,
                yes_bid_close=39,
                yes_ask_high=42,
                yes_ask_close=40,
                volume=1_000,
                open_interest=10,
            )
        )
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
    session.commit()

    broker = BacktestBroker(starting_cash_usd=1000.0)
    engine = BacktestEngine(
        strategy=EnterOnceThenHoldStrategy(),
        broker=broker,
        session=session,
        starting_cash_usd=1000.0,
        kelly_fraction=0.25,
        max_position_pct=0.05,
        guard=DrawdownGuard(pause_pct=0.25, halt_pct=0.40, initial_equity=1000.0),
        candle_period_minutes=1,
        eval_stride_s=1,
        signal_flush_interval=2,  # force multiple mid-run flushes
    )
    await engine.run(start_ts=BASE, end_ts=END, split_ts=BASE + 500)

    trades = session.execute(select(SimulatedTrade)).scalars().all()
    assert len(trades) == 1
    trade = trades[0]
    # Settlement mutation (applied well after several flushes occurred)
    # must have landed correctly, not been silently lost to a stale/expired
    # object reference.
    assert trade.status == "settled_won"
    assert trade.net_pnl_usd is not None
    assert trade.net_pnl_usd > 0

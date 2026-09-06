"""StrategyContext.spot_bars is actually populated by the engine (tasks.md
8.1's engine extension) — required for trend_scalp/level_break, which read
bar history to detect swing levels. Prior to this fix the field was always
empty regardless of what spot data existed, silently making those
strategies untestable."""

from __future__ import annotations

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import Session, sessionmaker

from kalshi_bot.backtest.engine import BacktestEngine
from kalshi_bot.execution.backtest_broker import BacktestBroker
from kalshi_bot.risk.drawdown_guard import DrawdownGuard
from kalshi_bot.storage.models import Base, Candle, KalshiMarket, SpotCandle
from kalshi_bot.strategy.base import Action, Decision, StrategyContext

BASE = 1_784_000_000
T1 = BASE + 3600
M1_CLOSE = BASE + 7200
END = BASE + 8_000


class BarCapturingStrategy:
    name = "bar_capturing"

    def __init__(self) -> None:
        self.seen_bars: list[tuple] = []

    def evaluate(self, context: StrategyContext) -> Decision:
        self.seen_bars.append(context.spot_bars)
        return Decision(
            action=Action.HOLD,
            market_ticker=context.market_ticker,
            strategy_name=self.name,
            hold_reason="observing_only",
        )


@pytest.fixture
def session() -> Session:
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)
    return sessionmaker(bind=engine, expire_on_commit=False)()


async def test_spot_bars_populated_with_hourly_history(session):
    session.add(
        KalshiMarket(
            ticker="M1",
            series_ticker="KXBTCD",
            strike_type="greater",
            floor_strike=100_000.0,
            open_ts=BASE,
            close_ts=M1_CLOSE,
            status="settled",
            result="no",
        )
    )
    session.add(
        Candle(
            market_ticker="M1",
            series_ticker="KXBTCD",
            period_minutes=60,
            end_period_ts=T1,
            yes_bid_close=40,
            yes_ask_close=42,
            yes_bid_low=38,
            yes_ask_high=44,
            volume=1_000,
            open_interest=10,
        )
    )
    # 40 daily spots (required for vol estimation) + 10 hourly spot bars
    # strictly before T1.
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
    for i in range(10):
        session.add(
            SpotCandle(
                exchange="coinbase",
                symbol="BTC-USD",
                period_minutes=60,
                open_ts=T1 - (10 - i) * 3600,
                open=100_000 + i,
                high=100_000 + i + 5,
                low=100_000 + i - 5,
                close=100_000 + i,
                volume=2.0,
            )
        )
    session.commit()

    strategy = BarCapturingStrategy()
    broker = BacktestBroker(starting_cash_usd=100.0)
    engine = BacktestEngine(
        strategy=strategy,
        broker=broker,
        session=session,
        starting_cash_usd=100.0,
        kelly_fraction=0.25,
        max_position_pct=0.05,
        guard=DrawdownGuard(pause_pct=0.25, halt_pct=0.40, initial_equity=100.0),
        candle_period_minutes=60,
        spot_bar_window=5,
    )
    await engine.run(start_ts=BASE, end_ts=END, split_ts=BASE + 5000)

    assert len(strategy.seen_bars) == 1
    bars = strategy.seen_bars[0]
    assert len(bars) == 5  # windowed to spot_bar_window=5, not all 10 available
    assert all(b.ts < T1 for b in bars)  # strictly before ts — no look-ahead
    assert [b.ts for b in bars] == sorted(b.ts for b in bars)  # oldest first
    # Volume/high/low actually carried through, not just close.
    assert bars[0].volume == pytest.approx(2.0)
    assert bars[0].high > bars[0].close > bars[0].low

"""Fixed-R intrabar stop/target exits (tasks.md 6.1/6.2 + 8.1's engine
extension): a Decision carrying stop_price_cents/target_price_cents must
close the position early against the market's own 1-minute contract
candles, rather than always holding to settlement.

Scenario (all arithmetic hand-computed in comments):
  - $1000 starting cash, quarter-Kelly, 5% position cap
  - One market, 1-minute candles: entry at minute 0, target hit at minute 3
  - The market's OFFICIAL result (settled at minute 15) is the OPPOSITE of
    the early-exit outcome — proves the early exit actually pre-empts
    settlement rather than coincidentally agreeing with it.
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
ENTRY_TS = BASE + 60  # first 1-min candle
MARKET_CLOSE = BASE + 900  # 15 minutes later
END = BASE + 1_200


class FixedRTestStrategy:
    """Emits a single BUY_YES decision with a fixed-R target 10c above
    entry, stop 10c below — on the first evaluation only, to keep the
    scenario to exactly one trade."""

    name = "fixed_r_test"

    def __init__(self) -> None:
        self._fired = False

    def evaluate(self, context: StrategyContext) -> Decision:
        if not self._fired and context.yes_ask_cents is not None:
            self._fired = True
            entry = context.yes_ask_cents
            return Decision(
                action=Action.BUY_YES,
                market_ticker=context.market_ticker,
                strategy_name=self.name,
                fair_probability=0.90,
                bs_probability=0.90,
                entry_price_cents=entry,
                stop_price_cents=max(1, entry - 10),
                target_price_cents=min(99, entry + 10),
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


async def run_engine(session: Session):
    broker = BacktestBroker(starting_cash_usd=1000.0)
    engine = BacktestEngine(
        strategy=FixedRTestStrategy(),
        broker=broker,
        session=session,
        starting_cash_usd=1000.0,
        kelly_fraction=0.25,
        max_position_pct=0.05,
        guard=DrawdownGuard(pause_pct=0.25, halt_pct=0.40, initial_equity=1000.0),
        candle_period_minutes=1,
        eval_stride_s=1,  # re-evaluate every 1-min candle
    )
    return await engine.run(start_ts=BASE, end_ts=END, split_ts=BASE + 500)


async def test_target_hit_closes_position_before_settlement(session):
    session.add(
        KalshiMarket(
            ticker="M1",
            series_ticker="KXBTCD",
            strike_type="greater",
            floor_strike=100_000.0,
            open_ts=BASE,
            close_ts=MARKET_CLOSE,
            status="settled",
            result="no",  # OPPOSITE of the early-exit outcome (proves pre-emption)
        )
    )
    # Entry candle: ask 40c/42c-high. Target = 40+10 = 50c.
    session.add(
        Candle(
            market_ticker="M1",
            series_ticker="KXBTCD",
            period_minutes=1,
            end_period_ts=ENTRY_TS,
            price_open=39,
            price_high=42,
            price_low=38,
            price_close=40,
            yes_bid_low=38,
            yes_bid_close=39,
            yes_ask_high=42,
            yes_ask_close=40,
            volume=1_000,
            open_interest=10,
        )
    )
    # Candle at minute 3: trade price reaches 51 -> crosses the 50c target.
    session.add(
        Candle(
            market_ticker="M1",
            series_ticker="KXBTCD",
            period_minutes=1,
            end_period_ts=BASE + 240,
            price_open=45,
            price_high=51,
            price_low=44,
            price_close=48,
            yes_bid_low=44,
            yes_bid_close=47,
            yes_ask_high=51,
            yes_ask_close=48,
            volume=1_000,
            open_interest=10,
        )
    )
    _spot(session)
    session.commit()

    result = await run_engine(session)

    trades = session.execute(select(SimulatedTrade)).scalars().all()
    assert len(trades) == 1
    trade = trades[0]
    assert trade.status == "closed_early"
    assert trade.exit_price_cents == 50  # the target level itself, not the bar's 51 high
    assert trade.exit_ts == BASE + 240
    assert trade.net_pnl_usd is not None
    assert trade.net_pnl_usd > 0  # target hit on a YES position is a win

    # The market's official result was "no" (a loss) — if settlement had
    # been allowed to run, this trade would show a LOSS. Confirming a WIN
    # proves the early exit pre-empted settlement rather than coinciding
    # with it by chance.
    assert result.final_equity > 1000.0


async def test_stop_hit_closes_position_as_a_loss(session):
    session.add(
        KalshiMarket(
            ticker="M1",
            series_ticker="KXBTCD",
            strike_type="greater",
            floor_strike=100_000.0,
            open_ts=BASE,
            close_ts=MARKET_CLOSE,
            status="settled",
            result="yes",  # OPPOSITE of the early-exit outcome
        )
    )
    session.add(
        Candle(
            market_ticker="M1",
            series_ticker="KXBTCD",
            period_minutes=1,
            end_period_ts=ENTRY_TS,
            price_open=39,
            price_high=42,
            price_low=38,
            price_close=40,
            yes_bid_low=38,
            yes_bid_close=39,
            yes_ask_high=42,
            yes_ask_close=40,
            volume=1_000,
            open_interest=10,
        )
    )
    # Minute 3: trade price falls to 29 -> crosses the 30c stop (40-10).
    session.add(
        Candle(
            market_ticker="M1",
            series_ticker="KXBTCD",
            period_minutes=1,
            end_period_ts=BASE + 240,
            price_open=35,
            price_high=36,
            price_low=29,
            price_close=31,
            yes_bid_low=29,
            yes_bid_close=30,
            yes_ask_high=33,
            yes_ask_close=31,
            volume=1_000,
            open_interest=10,
        )
    )
    _spot(session)
    session.commit()

    await run_engine(session)

    trades = session.execute(select(SimulatedTrade)).scalars().all()
    assert len(trades) == 1
    trade = trades[0]
    assert trade.status == "closed_early"
    assert trade.exit_price_cents == 30
    assert trade.net_pnl_usd is not None
    assert trade.net_pnl_usd < 0


async def test_neither_level_hit_holds_to_settlement(session):
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
    session.add(
        Candle(
            market_ticker="M1",
            series_ticker="KXBTCD",
            period_minutes=1,
            end_period_ts=ENTRY_TS,
            price_open=39,
            price_high=42,
            price_low=38,
            price_close=40,
            yes_bid_low=38,
            yes_bid_close=39,
            yes_ask_high=42,
            yes_ask_close=40,
            volume=1_000,
            open_interest=10,
        )
    )
    # A quiet bar that stays comfortably inside [30, 50] the whole time.
    session.add(
        Candle(
            market_ticker="M1",
            series_ticker="KXBTCD",
            period_minutes=1,
            end_period_ts=BASE + 240,
            price_open=40,
            price_high=41,
            price_low=39,
            price_close=40,
            yes_bid_low=39,
            yes_bid_close=40,
            yes_ask_high=41,
            yes_ask_close=40,
            volume=1_000,
            open_interest=10,
        )
    )
    _spot(session)
    session.commit()

    await run_engine(session)

    trades = session.execute(select(SimulatedTrade)).scalars().all()
    assert len(trades) == 1
    trade = trades[0]
    assert trade.status == "settled_won"  # rode to expiry, market settled YES


async def test_both_levels_touched_in_one_bar_assumes_stop_first(session):
    """A bar that touches both stop AND target in one minute is ambiguous
    from OHLC alone — the engine must assume the WORSE outcome (stop first),
    same pessimism discipline BacktestBroker already applies to entry fills."""
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
    session.add(
        Candle(
            market_ticker="M1",
            series_ticker="KXBTCD",
            period_minutes=1,
            end_period_ts=ENTRY_TS,
            price_open=39,
            price_high=42,
            price_low=38,
            price_close=40,
            yes_bid_low=38,
            yes_bid_close=39,
            yes_ask_high=42,
            yes_ask_close=40,
            volume=1_000,
            open_interest=10,
        )
    )
    # Wild bar: low 25 (below the 30c stop) AND high 55 (above the 50c target).
    session.add(
        Candle(
            market_ticker="M1",
            series_ticker="KXBTCD",
            period_minutes=1,
            end_period_ts=BASE + 240,
            price_open=40,
            price_high=55,
            price_low=25,
            price_close=40,
            yes_bid_low=25,
            yes_bid_close=40,
            yes_ask_high=55,
            yes_ask_close=40,
            volume=1_000,
            open_interest=10,
        )
    )
    _spot(session)
    session.commit()

    await run_engine(session)

    trades = session.execute(select(SimulatedTrade)).scalars().all()
    assert len(trades) == 1
    trade = trades[0]
    assert trade.status == "closed_early"
    assert trade.exit_price_cents == 30  # the stop, not the target

"""Known-answer replay: the engine must reproduce hand-computed outcomes
exactly. This is the test that guards against the backtest engine itself
producing falsely-favorable results — v1's core failure mode one layer up.

Scenario (all arithmetic hand-computed in comments):
  - $100 starting cash, quarter-Kelly, 5% position cap
  - Market M1 (train segment): ask 40c/42c-high, settles YES -> win
  - Market M2 (test segment):  ask 45c flat,     settles NO  -> loss
  - Deterministic test strategy: BUY_YES whenever ask < 50, claimed p=0.90
"""

import pytest
from sqlalchemy import create_engine, select
from sqlalchemy.orm import Session, sessionmaker

from kalshi_bot.backtest.engine import BacktestEngine
from kalshi_bot.execution.backtest_broker import BacktestBroker
from kalshi_bot.risk.drawdown_guard import DrawdownGuard
from kalshi_bot.storage.models import (
    BacktestRun,
    Base,
    Candle,
    KalshiMarket,
    SignalRecord,
    SimulatedTrade,
    SpotCandle,
)
from kalshi_bot.strategy.base import Action, Decision, StrategyContext

BASE = 1_784_000_000
T1 = BASE + 3600  # M1's candle hour
M1_CLOSE = BASE + 7200
SPLIT = BASE + 10_000
T2 = BASE + 14_400  # M2's candle hour
M2_CLOSE = BASE + 18_000
END = BASE + 20_000


class DeterministicStrategy:
    """Engine-agnosticism check: any StrategyProtocol implementation works."""

    name = "deterministic_test"

    def evaluate(self, context: StrategyContext) -> Decision:
        if context.yes_ask_cents is not None and context.yes_ask_cents < 50:
            return Decision(
                action=Action.BUY_YES,
                market_ticker=context.market_ticker,
                strategy_name=self.name,
                bs_probability=0.90,
                entry_price_cents=context.yes_ask_cents,
            )
        return Decision(
            action=Action.HOLD,
            market_ticker=context.market_ticker,
            strategy_name=self.name,
            hold_reason="ask_too_high",
        )


@pytest.fixture
def session() -> Session:
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)
    return sessionmaker(bind=engine, expire_on_commit=False)()


def seed_synthetic_history(session: Session) -> None:
    session.add_all(
        [
            KalshiMarket(
                ticker="M1",
                series_ticker="KXBTCD",
                strike_type="greater",
                floor_strike=100_000.0,
                open_ts=BASE,
                close_ts=M1_CLOSE,
                status="settled",
                result="yes",
            ),
            KalshiMarket(
                ticker="M2",
                series_ticker="KXBTCD",
                strike_type="greater",
                floor_strike=100_000.0,
                open_ts=SPLIT,
                close_ts=M2_CLOSE,
                status="settled",
                result="no",
            ),
        ]
    )
    session.add_all(
        [
            Candle(
                market_ticker="M1",
                series_ticker="KXBTCD",
                period_minutes=60,
                end_period_ts=T1,
                yes_bid_low=35,
                yes_bid_close=38,
                yes_ask_high=42,
                yes_ask_close=40,
                volume=10,
                open_interest=10,
            ),
            Candle(
                market_ticker="M2",
                series_ticker="KXBTCD",
                period_minutes=60,
                end_period_ts=T2,
                yes_bid_low=40,
                yes_bid_close=43,
                yes_ask_high=45,
                yes_ask_close=45,
                volume=10,
                open_interest=10,
            ),
        ]
    )
    # 40 daily spot closes before BASE (constant -> vol 0, unused by the
    # deterministic strategy but required for context assembly) + hourly spots.
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
    for ts in (T1 - 3600, T2 - 3600):
        session.add(
            SpotCandle(
                exchange="coinbase",
                symbol="BTC-USD",
                period_minutes=60,
                open_ts=ts,
                open=100_000,
                high=100_000,
                low=100_000,
                close=100_000,
                volume=1,
            )
        )
    session.commit()


async def run_engine(session: Session):
    broker = BacktestBroker(starting_cash_usd=100.0)
    engine = BacktestEngine(
        strategy=DeterministicStrategy(),
        broker=broker,
        session=session,
        starting_cash_usd=100.0,
        kelly_fraction=0.25,
        max_position_pct=0.05,
        guard=DrawdownGuard(pause_pct=0.25, halt_pct=0.40, initial_equity=100.0),
        candle_period_minutes=60,  # synthetic candles are hourly, mid-market
    )
    return await engine.run(start_ts=BASE, end_ts=END, split_ts=SPLIT)


async def test_replay_matches_hand_computation(session):
    seed_synthetic_history(session)
    result = await run_engine(session)

    # --- M1 sizing: p=0.90 at sizing cost 40c, equity $100 ---------------------
    # full Kelly: b = (0.60*0.93)/0.40 = 1.395; f* = 0.9 - 0.1/1.395 = 0.828315...
    # quarter-Kelly 0.20708 -> clamped to 0.05 -> budget $5.00 -> 12 contracts
    # fill at ask_high 42c -> cost $5.04
    # WIN:  gross = (1-0.42)*12 = $6.96; fee = 0.07*6.96 = $0.4872; net = $6.4728
    # cash after: 100 - 5.04 + 12 - 0.4872 = 106.4728
    trades = (
        session.execute(select(SimulatedTrade).order_by(SimulatedTrade.entry_ts)).scalars().all()
    )
    assert len(trades) == 2
    m1 = trades[0]
    assert m1.market_ticker == "M1"
    assert m1.quantity == 12
    assert m1.entry_price_cents == 42
    assert m1.status == "settled_won"
    assert m1.gross_pnl_usd == pytest.approx(6.96)
    assert m1.fee_usd == pytest.approx(0.4872)
    assert m1.net_pnl_usd == pytest.approx(6.4728)

    # --- M2 sizing: equity $106.4728, cost 45c --------------------------------
    # budget = 106.4728*0.05 = $5.32364 -> 11 contracts @ 45c = $4.95
    # LOSS: net = -$4.95. Final equity = 106.4728 - 4.95 = 101.5228
    m2 = trades[1]
    assert m2.market_ticker == "M2"
    assert m2.quantity == 11
    assert m2.entry_price_cents == 45
    assert m2.status == "settled_lost"
    assert m2.net_pnl_usd == pytest.approx(-4.95)

    assert result.final_equity == pytest.approx(101.5228)

    # --- segmentation: the win is train, the loss is test ------------------------
    assert result.train.n_trades == 1
    assert result.train.wins == 1
    assert result.train.net_pnl_usd == pytest.approx(6.4728)
    assert result.test.n_trades == 1
    assert result.test.wins == 0
    assert result.test.net_pnl_usd == pytest.approx(-4.95)

    # --- fee-adjusted breakeven displayed next to achieved (spec) ----------------
    assert result.test.breakeven_win_rate_avg is not None
    # at 45c: p_be = 0.45 / (0.55*0.93 + 0.45) = 0.46806...
    assert result.test.breakeven_win_rate_avg == pytest.approx(0.45 / (0.55 * 0.93 + 0.45))
    assert result.test.win_rate_margin == pytest.approx(0.0 - result.test.breakeven_win_rate_avg)


async def test_every_evaluation_is_persisted(session):
    seed_synthetic_history(session)
    await run_engine(session)
    signals = session.execute(select(SignalRecord)).scalars().all()
    assert len(signals) == 2  # one evaluation per market candle
    assert all(s.mode == "backtest" and s.backtest_run_id is not None for s in signals)


async def test_run_row_persists_segmented_metrics(session):
    seed_synthetic_history(session)
    result = await run_engine(session)
    run = session.execute(select(BacktestRun)).scalar_one()
    assert run.id == result.run_id
    assert run.status == "completed"
    assert run.metrics_train["n_trades"] == 1
    assert run.metrics_test["n_trades"] == 1
    assert run.split_ts == SPLIT


async def test_split_is_engine_enforced(session):
    seed_synthetic_history(session)
    broker = BacktestBroker(starting_cash_usd=100.0)
    engine = BacktestEngine(
        strategy=DeterministicStrategy(),
        broker=broker,
        session=session,
        starting_cash_usd=100.0,
        kelly_fraction=0.25,
        max_position_pct=0.05,
        guard=DrawdownGuard(pause_pct=0.25, halt_pct=0.40, initial_equity=100.0),
    )
    with pytest.raises(ValueError):
        await engine.run(start_ts=BASE, end_ts=END, split_ts=END + 1)

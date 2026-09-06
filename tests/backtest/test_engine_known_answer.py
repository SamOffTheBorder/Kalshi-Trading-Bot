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
                volume=1_000,  # deep enough that the liquidity cap never binds here
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
                volume=1_000,  # deep enough that the liquidity cap never binds here
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
    """Fee model (v2, corrected — see execution/fees.py): charged ONCE, AT
    ENTRY, win or lose. Sizing divides budget by EFFECTIVE cost (price + fee),
    not price alone (risk/kelly.py). All numbers below are cross-checked
    against the actual engine, not hand-derived from scratch.
    """
    seed_synthetic_history(session)
    result = await run_engine(session)

    # --- M1 sizing: p=0.90 at sizing cost 40c, equity $100 ---------------------
    # effective cost = 0.40 + fee_rate(0.40) = 0.40 + 0.07*0.40*0.60 = 0.4168
    # full Kelly: b = (1-0.4168)/0.4168 = 1.39923...; f* = 0.9 - 0.1/1.39923 = 0.82853...
    # quarter-Kelly 0.20713 -> clamped to 0.05 -> budget $5.00 -> floor(5.00/0.4168) = 11 contracts
    # fill at ask_high 42c -> stake $4.62, entry fee = ceil(0.07*0.42*0.58*11*100)/100 = $0.19
    # WIN: gross = (1-0.42)*11 = $6.38; fee already paid at entry = $0.19; net = $6.19
    # cash after: 100 - 4.62 - 0.19 (entry) + 11 (payout) = 106.19
    trades = (
        session.execute(select(SimulatedTrade).order_by(SimulatedTrade.entry_ts)).scalars().all()
    )
    assert len(trades) == 2
    m1 = trades[0]
    assert m1.market_ticker == "M1"
    assert m1.quantity == 11
    assert m1.entry_price_cents == 42
    assert m1.status == "settled_won"
    assert m1.gross_pnl_usd == pytest.approx(6.38)
    assert m1.fee_usd == pytest.approx(0.19)
    assert m1.net_pnl_usd == pytest.approx(6.19)

    # --- M2 sizing: equity $106.19, cost 45c ----------------------------------
    # effective cost = 0.45 + 0.07*0.45*0.55 = 0.467325
    # full Kelly: b=(1-0.467325)/0.467325=1.13968...; f*=0.9-0.1/1.13968=0.81226...
    # quarter-Kelly 0.20307 -> clamped to 0.05 -> budget = 106.19*0.05 = $5.3095
    # floor(5.3095/0.467325) = 11 contracts @ 45c = $4.95 stake
    # entry fee = ceil(0.07*0.45*0.55*11*100)/100 = $0.20
    # LOSS: net = -4.95 - 0.20 = -5.15. Final equity = 106.19 - 4.95 - 0.20 = 101.04
    m2 = trades[1]
    assert m2.market_ticker == "M2"
    assert m2.quantity == 11
    assert m2.entry_price_cents == 45
    assert m2.status == "settled_lost"
    assert m2.fee_usd == pytest.approx(0.20)
    assert m2.net_pnl_usd == pytest.approx(-5.15)

    assert result.final_equity == pytest.approx(101.04)

    # --- segmentation: the win is train, the loss is test ------------------------
    assert result.train.n_trades == 1
    assert result.train.wins == 1
    assert result.train.net_pnl_usd == pytest.approx(6.19)
    assert result.test.n_trades == 1
    assert result.test.wins == 0
    assert result.test.net_pnl_usd == pytest.approx(-5.15)

    # --- fee-adjusted breakeven displayed next to achieved (spec) ----------------
    assert result.test.breakeven_win_rate_avg is not None
    # corrected formula: p_be = P + fee_rate(P); at 45c: 0.45 + 0.07*0.45*0.55 = 0.467325
    assert result.test.breakeven_win_rate_avg == pytest.approx(0.45 + 0.07 * 0.45 * 0.55)
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


class BandedStrategy:
    """Declares a narrow entry band around its decision price, so a
    pessimistic fill at a worse price is rejected by the engine — the fix
    for Phase 1's fill-vs-intended-price bug (18/64 trades, 28%, landed
    outside the strategy's own band; backtest-engine spec: 'entry gates are
    evaluated against the actual fill')."""

    name = "banded_test"

    def evaluate(self, context: StrategyContext) -> Decision:
        if context.yes_ask_cents is not None and context.yes_ask_cents < 50:
            return Decision(
                action=Action.BUY_YES,
                market_ticker=context.market_ticker,
                strategy_name=self.name,
                bs_probability=0.90,
                entry_price_cents=context.yes_ask_cents,
                # M1's decision price (yes_ask_close) is 40c, comfortably
                # inside [35, 41] — but the pessimistic fill uses
                # yes_ask_high = 42c, which falls OUTSIDE this band.
                min_entry_price_cents=35,
                max_entry_price_cents=41,
            )
        return Decision(
            action=Action.HOLD,
            market_ticker=context.market_ticker,
            strategy_name=self.name,
            hold_reason="ask_too_high",
        )


async def test_fill_outside_entry_band_is_rejected(session):
    """M1's decision price (40c) is inside the strategy's declared band
    [35, 41], but the pessimistic fill (yes_ask_high=42c) is not. The engine
    must reject the fill — no position, no cash spent — rather than record a
    trade at a price the strategy never agreed to."""
    seed_synthetic_history(session)
    broker = BacktestBroker(starting_cash_usd=100.0)
    engine = BacktestEngine(
        strategy=BandedStrategy(),
        broker=broker,
        session=session,
        starting_cash_usd=100.0,
        kelly_fraction=0.25,
        max_position_pct=0.05,
        guard=DrawdownGuard(pause_pct=0.25, halt_pct=0.40, initial_equity=100.0),
        candle_period_minutes=60,
    )
    result = await engine.run(start_ts=BASE, end_ts=END, split_ts=SPLIT)

    # BandedStrategy always declares [35, 41] regardless of market. M1's
    # pessimistic fill (yes_ask_high=42) and M2's (yes_ask_high=45) both
    # land above 41, so both fills are rejected and no trades occur.
    trades = session.execute(select(SimulatedTrade)).scalars().all()
    assert trades == []
    assert result.final_equity == pytest.approx(100.0)  # nothing spent
    assert broker.settlements == []  # nothing was ever open to settle


async def test_dead_quote_market_never_generates_an_entry(session):
    """Spec: 'Only live markets are tradeable' — a market with zero open
    interest is a phantom quote (92/100 sampled KXBTCD strikes, Phase 1) and
    must never fill, even though the strategy would otherwise BUY it."""
    session.add(
        KalshiMarket(
            ticker="DEAD",
            series_ticker="KXBTCD",
            strike_type="greater",
            floor_strike=100_000.0,
            open_ts=BASE,
            close_ts=M1_CLOSE,
            status="settled",
            result="yes",
        )
    )
    session.add(
        Candle(
            market_ticker="DEAD",
            series_ticker="KXBTCD",
            period_minutes=60,
            end_period_ts=T1,
            yes_bid_low=0,
            yes_bid_close=0,
            yes_ask_high=1,
            yes_ask_close=1,  # ask < 50 -> DeterministicStrategy would BUY_YES
            volume=0,
            open_interest=0,  # the phantom-market signal
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
            open_ts=T1 - 3600,
            open=100_000,
            high=100_000,
            low=100_000,
            close=100_000,
            volume=1,
        )
    )
    session.commit()

    result = await run_engine(session)

    # The strategy is still evaluated (audit trail intact) and would have
    # bought — but no trade, no cash spent, no settlement.
    signals = session.execute(select(SignalRecord)).scalars().all()
    assert len(signals) == 1
    assert signals[0].action == "BUY_YES"

    trades = session.execute(select(SimulatedTrade)).scalars().all()
    assert trades == []
    assert result.final_equity == pytest.approx(100.0)


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

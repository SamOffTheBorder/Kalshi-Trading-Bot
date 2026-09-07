"""kxbtc15m-validation-rebuild §2.3: BUY YES and BUY NO must both carry a
valid, side-consistent `fair_probability`, and the engine must have NO
default-certainty path.

Before this fix the engine computed p_win as
``decision.bs_probability if BUY_YES else 1.0 - (decision.bs_probability or 0.0)``
so a directional strategy that set no ``bs_probability`` (every trend/level
strategy) produced:
  - BUY_NO  -> p_win = 1.0 - (None or 0.0) = 1.0  (sized as a sure thing)
  - BUY_YES -> p_win = None -> silently dropped

Now the engine reads ``decision.fair_probability`` directly (no inversion,
no fallback); a BUY that omits it is dropped with a logged warning rather
than entered.
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
T1 = BASE + 60  # decision candle
T1_FILL = BASE + 120  # next candle — a queued entry executes here (§2.1/§2.2)
M1_CLOSE = BASE + 900
END = BASE + 1_200


class DirectionalStrategy:
    """Emits one BUY on the first evaluation. ``fair_probability`` is passed
    through from the constructor (or omitted when None) so a single scenario
    matrix covers 'valid NO prob', 'valid YES prob', and 'missing prob'."""

    name = "directional_test"

    def __init__(self, action: Action, fair_probability: float | None) -> None:
        self._action = action
        self._fp = fair_probability
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
        entry = (
            context.yes_ask_cents if self._action == Action.BUY_YES else 100 - context.yes_bid_cents
        )
        return Decision(
            action=self._action,
            market_ticker=context.market_ticker,
            strategy_name=self.name,
            fair_probability=self._fp,
            entry_price_cents=entry,
        )


@pytest.fixture
def session() -> Session:
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)
    return sessionmaker(bind=engine, expire_on_commit=False)()


def _seed(session: Session, *, result: str) -> None:
    session.add(
        KalshiMarket(
            ticker="M1",
            series_ticker="KXBTC15M",
            strike_type="greater",
            floor_strike=100_000.0,
            open_ts=BASE,
            close_ts=M1_CLOSE,
            status="settled",
            result=result,
        )
    )
    def candle(end_ts: int) -> Candle:
        return Candle(
            market_ticker="M1",
            series_ticker="KXBTC15M",
            period_minutes=1,
            end_period_ts=end_ts,
            price_open=49,
            price_high=51,
            price_low=48,
            price_close=50,
            yes_bid_low=48,
            yes_bid_close=49,
            yes_ask_high=52,
            yes_ask_close=50,
            volume=10_000,
            open_interest=5_000,
        )

    # decision candle + the next candle the queued order fills against
    session.add_all([candle(T1), candle(T1_FILL)])
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


async def _run(session: Session, strategy: DirectionalStrategy):
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


async def test_buy_no_without_fair_probability_is_not_entered(session):
    """The regression: a BUY_NO carrying no probability used to size at
    p_win = 1.0. It must now be dropped, not entered."""
    _seed(session, result="no")
    await _run(session, DirectionalStrategy(Action.BUY_NO, fair_probability=None))
    trades = session.execute(select(SimulatedTrade)).scalars().all()
    assert trades == []


async def test_buy_yes_without_fair_probability_is_not_entered(session):
    _seed(session, result="yes")
    await _run(session, DirectionalStrategy(Action.BUY_YES, fair_probability=None))
    trades = session.execute(select(SimulatedTrade)).scalars().all()
    assert trades == []


async def test_buy_no_with_valid_side_consistent_probability_enters(session):
    """A BUY_NO whose fair_probability is P(NO wins) enters and is sized off
    that value (not an inverted YES prob, not certainty)."""
    _seed(session, result="no")  # NO resolves -> the position wins
    await _run(session, DirectionalStrategy(Action.BUY_NO, fair_probability=0.65))
    trades = session.execute(select(SimulatedTrade)).scalars().all()
    assert len(trades) == 1
    assert trades[0].side == "no"
    assert trades[0].status == "settled_won"


async def test_fair_probability_out_of_range_is_not_entered(session):
    _seed(session, result="yes")
    await _run(session, DirectionalStrategy(Action.BUY_YES, fair_probability=1.4))
    trades = session.execute(select(SimulatedTrade)).scalars().all()
    assert trades == []

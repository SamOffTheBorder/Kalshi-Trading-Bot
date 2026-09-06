"""Concurrent same-timestep entries must size against the CURRENT remaining
bankroll, not a stale figure snapshotted once at the top of the timestep
(tasks.md 8.3 finding, 2026-09-06).

Found via a real backtest: ~24 correlated strikes (same underlying BTC move,
different threshold levels) fired in a single evaluation batch. Each Kelly
sizing call used the SAME pre-batch equity figure, so every position sized
as if it were the only one being opened that step — the aggregate exposure
across the batch could dwarf any single position's own cap, and later
positions could still get sized generously even after earlier ones in the
same batch had already spent most of the bankroll. Fixed by re-fetching cash
+ open positions immediately before each individual sizing call rather than
once per timestep."""

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
MARKET_CLOSE = BASE + 900
END = BASE + 1_200

N_MARKETS = 6
STARTING_CASH = 60.0


class AlwaysBuyMaxConfidence:
    """Enters every market it sees, at maximum Kelly confidence (p_win=0.99
    against a cheap 10c contract) so sizing is aggressive enough that a
    shared stale bankroll figure across the batch would visibly produce
    near-identical large quantities, while a correctly re-marked bankroll
    must shrink the later entries in the same batch."""

    name = "always_buy"

    def evaluate(self, context: StrategyContext) -> Decision:
        if context.yes_ask_cents is None:
            return Decision(
                action=Action.HOLD,
                market_ticker=context.market_ticker,
                strategy_name=self.name,
                hold_reason="no_quote",
            )
        return Decision(
            action=Action.BUY_YES,
            market_ticker=context.market_ticker,
            strategy_name=self.name,
            bs_probability=0.99,
            entry_price_cents=context.yes_ask_cents,
        )


@pytest.fixture
def session() -> Session:
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)
    return sessionmaker(bind=engine, expire_on_commit=False)()


async def test_concurrent_same_timestep_entries_share_a_shrinking_bankroll(session):
    # N_MARKETS markets, ALL with a candle at the exact same timestamp — the
    # scenario that produced the phantom HALT in the real run.
    tickers = [f"M{i}" for i in range(N_MARKETS)]
    for ticker in tickers:
        session.add(
            KalshiMarket(
                ticker=ticker,
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
                market_ticker=ticker,
                series_ticker="KXBTCD",
                period_minutes=1,
                end_period_ts=BASE + 60,
                price_open=10,
                price_high=11,
                price_low=9,
                price_close=10,
                yes_bid_low=9,
                yes_bid_close=9,
                yes_ask_high=11,
                yes_ask_close=10,  # cheap contract -> large Kelly quantity
                # High enough that BacktestBroker's own liquidity cap
                # (volume * liquidity_cap_frac) never binds here — bankroll
                # sizing must be the constraint this test actually exercises,
                # not the unrelated fill-liquidity cap.
                volume=1_000_000,
                open_interest=10,
            )
        )
    # Spot data required for the engine to even build a StrategyContext
    # (vol estimation needs daily history; the strategy itself doesn't use
    # spot at all, but the engine gates evaluation on it existing).
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

    strategy = AlwaysBuyMaxConfidence()
    broker = BacktestBroker(starting_cash_usd=STARTING_CASH)
    engine = BacktestEngine(
        strategy=strategy,
        broker=broker,
        session=session,
        starting_cash_usd=STARTING_CASH,
        kelly_fraction=1.0,  # aggressive: full Kelly, no fractional damping
        max_position_pct=0.5,  # loose cap so bankroll re-marking is what binds
        guard=DrawdownGuard(pause_pct=0.90, halt_pct=0.95, initial_equity=STARTING_CASH),
        candle_period_minutes=1,
        eval_stride_s=1,
    )
    await engine.run(start_ts=BASE, end_ts=END, split_ts=BASE + 500)

    # Reconstruct entry order via SimulatedTrade rows (all candidates share the
    # same ts, but the engine processes candles_by_ts[ts] in a fixed list
    # order, so "first" vs "last" within the batch is well-defined and
    # deterministic).
    from sqlalchemy import select

    from kalshi_bot.storage.models import SimulatedTrade

    rows = session.execute(select(SimulatedTrade).order_by(SimulatedTrade.id)).scalars().all()
    quantities = [r.quantity for r in rows]

    # The old bug: every position in the batch sized off the SAME stale
    # pre-batch equity ($60 for all six candidates here), so every request
    # asked for the same large quantity regardless of what earlier same-batch
    # entries had already spent. BacktestBroker.place_order's own
    # `cost > self._cash` guard still protects against a literal negative
    # balance, but it can only reject a too-big order outright — it can't
    # downsize it — so the bug's real effect is REJECTING opportunities that
    # a correctly-shrinking bankroll could have partially filled: exactly one
    # of the six all-identical $31-ish requests fits in $60, and the other
    # five are turned away entirely even though real bankroll remained.
    #
    # The fix re-marks bankroll before each sizing call, so:
    # (a) more than one opportunity in the batch should be takeable — the
    #     second (smaller, correctly-sized) request should still fit in the
    #     bankroll left after the first, where the bug would have rejected it
    #     outright for requesting the full-bankroll-sized quantity again.
    assert len(rows) >= 2, (
        "fix should let a second, appropriately-smaller same-batch entry "
        "through on the remaining bankroll — only 1 entry landing would "
        "mean sizing is still requesting a stale (too-large) quantity that "
        "gets rejected outright instead of correctly shrunk"
    )
    # (b) whichever entries DID happen must be non-increasing in quantity
    #     (later entries never see MORE bankroll than earlier ones in the
    #     same batch).
    assert quantities == sorted(quantities, reverse=True)
    assert quantities[-1] < quantities[0], "later same-batch entry must be sized smaller"
    # (c) aggregate spend across the whole batch must respect the broker's
    #     real starting cash.
    total_cost = sum(r.quantity * r.entry_price_cents / 100 for r in rows)
    assert total_cost <= STARTING_CASH + 1e-6

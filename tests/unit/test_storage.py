"""Schema-of-record invariants: round-trips and dedup constraints."""

import pytest
from sqlalchemy import create_engine, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session, sessionmaker

from kalshi_bot.storage.models import (
    BacktestRun,
    Base,
    Candle,
    SignalRecord,
    SimulatedTrade,
)


@pytest.fixture
def session() -> Session:
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)
    return sessionmaker(bind=engine, expire_on_commit=False)()


def _candle(**overrides) -> Candle:
    defaults = dict(
        market_ticker="KXBTCD-25JUL15-T118000",
        series_ticker="KXBTCD",
        period_minutes=60,
        end_period_ts=1_752_534_000,
        price_open=42,
        price_high=47,
        price_low=40,
        price_close=45,
        yes_bid_close=44,
        yes_ask_close=46,
        volume=120,
        open_interest=800,
    )
    defaults.update(overrides)
    return Candle(**defaults)


def test_candle_roundtrip(session):
    session.add(_candle())
    session.commit()
    row = session.execute(select(Candle)).scalar_one()
    assert row.price_close == 45
    assert row.yes_ask_close == 46
    assert row.series_ticker == "KXBTCD"


def test_candle_duplicate_rejected(session):
    """Same (market, period, ts) must violate the unique constraint —
    this is what makes re-fetches idempotent at the DB layer."""
    session.add(_candle())
    session.commit()
    session.add(_candle(price_close=99))
    with pytest.raises(IntegrityError):
        session.commit()


def test_candle_distinct_periods_allowed(session):
    session.add(_candle(period_minutes=60))
    session.add(_candle(period_minutes=1440))
    session.commit()
    assert len(session.execute(select(Candle)).scalars().all()) == 2


def test_candle_nullable_prices_when_no_trades(session):
    session.add(
        _candle(price_open=None, price_high=None, price_low=None, price_close=None, volume=0)
    )
    session.commit()
    row = session.execute(select(Candle)).scalar_one()
    assert row.price_close is None
    assert row.yes_ask_close == 46  # bid/ask still quoted


def test_signal_records_hold_with_reason(session):
    """The audit trail requirement: HOLDs persist with reasoning."""
    session.add(
        SignalRecord(
            evaluated_at_ts=1_752_534_000,
            mode="backtest",
            strategy_name="crypto_mispricing",
            market_ticker="KXBTCD-25JUL15-T118000",
            action="HOLD",
            market_yes_price=45,
            bs_probability=0.48,
            mc_probability=0.55,
            raw_edge=0.03,
            fee_adjusted_edge=-0.004,
            hold_reason="bs_mc_divergence",
        )
    )
    session.commit()
    row = session.execute(select(SignalRecord)).scalar_one()
    assert row.action == "HOLD"
    assert row.hold_reason == "bs_mc_divergence"
    assert row.fee_adjusted_edge < 0


def test_backtest_run_with_trades_roundtrip(session):
    run = BacktestRun(
        strategy_name="crypto_mispricing",
        params={"kelly_fraction": 0.25},
        data_start_ts=1_700_000_000,
        data_end_ts=1_752_000_000,
        split_ts=1_740_000_000,
    )
    session.add(run)
    session.flush()
    session.add(
        SimulatedTrade(
            backtest_run_id=run.id,
            mode="backtest",
            market_ticker="KXBTCD-25JUL15-T118000",
            side="yes",
            quantity=10,
            entry_price_cents=45,
            entry_ts=1_752_534_000,
            status="settled_won",
            gross_pnl_usd=5.50,
            fee_usd=0.385,
            net_pnl_usd=5.115,
        )
    )
    session.commit()
    trade = session.execute(select(SimulatedTrade)).scalar_one()
    assert trade.backtest_run_id == run.id
    assert trade.net_pnl_usd == pytest.approx(5.115)
    stored_run = session.execute(select(BacktestRun)).scalar_one()
    assert stored_run.params == {"kelly_fraction": 0.25}
    assert stored_run.status == "running"

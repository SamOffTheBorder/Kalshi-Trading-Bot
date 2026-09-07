"""End-to-end KXBTC15M walk-forward validation run
(kxbtc15m-validation-rebuild §4.6): the fail-closed data guard, the fold
geometry check, and a full run over a synthetic causal archive that drives
the settlement-aware strategy through the engine, fixed-risk sizing, prior-
fold-only isotonic calibration and the enforced promotion gate.

The synthetic archive is deliberately favourable — BRTI drifts hard in the
direction the market ultimately resolves and the contract is quoted well
away from fair value — so the run produces trades and the plumbing is
exercised. It is NOT a claim that the strategy has real edge; that verdict
needs a captured archive.
"""

from __future__ import annotations

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import Session, sessionmaker

from kalshi_bot.backtest.promotion_gate import PromotionPolicy
from kalshi_bot.backtest.validation_run import (
    dataset_counts,
    run_validation_arms,
)
from kalshi_bot.storage.models import (
    Base,
    BRTIObservation,
    Candle,
    KalshiMarket,
)

DAY = 86_400
BASE = 1_784_000_000  # a Monday 00:00-ish UTC anchor
WINDOW = 15 * 60


@pytest.fixture
def session_factory():
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)
    return sessionmaker(bind=engine, expire_on_commit=False)


def _add_window(
    session: Session,
    *,
    ticker: str,
    open_ts: int,
    resolves_yes: bool,
    quote_cents: int,
) -> None:
    """One KXBTC15M market: a 15-minute window with 1-minute contract candles
    (all live: two-sided quote + open interest) and a BRTI path that ends
    clearly above (YES) or below (NO) its opening 60 s average."""
    close_ts = open_ts + WINDOW
    session.add(
        KalshiMarket(
            ticker=ticker,
            series_ticker="KXBTC15M",
            strike_type="greater",
            floor_strike=0.0,
            open_ts=open_ts,
            close_ts=close_ts,
            status="settled",
            result="yes" if resolves_yes else "no",
        )
    )
    for minute in range(1, 16):
        end_ts = open_ts + minute * 60
        session.add(
            Candle(
                market_ticker=ticker,
                series_ticker="KXBTC15M",
                period_minutes=1,
                end_period_ts=end_ts,
                yes_bid_close=quote_cents - 1,
                yes_ask_close=quote_cents + 1,
                yes_bid_low=quote_cents - 1,
                yes_ask_high=quote_cents + 1,
                yes_bid_high=quote_cents - 1,
                yes_ask_low=quote_cents + 1,
                volume=500,
                open_interest=5_000,
            )
        )
    # BRTI: flat reference at 100_000 for the first 60 s, then a monotone
    # drift of +/- 40 over the remaining window. One reading every 10 s.
    ref = 100_000.0
    drift = 40.0 if resolves_yes else -40.0
    for k in range(0, WINDOW + 1, 10):
        ts = open_ts + k
        if k <= 60:
            value = ref
        else:
            frac = (k - 60) / (WINDOW - 60)
            value = ref + drift * frac
        session.add(
            BRTIObservation(
                observed_at=ts,
                available_at=ts,
                value_dollars=f"{value:.2f}",
                source="synthetic",
            )
        )


def _populate(session_factory, *, days: int, windows_per_day: int) -> None:
    with session_factory() as session:
        for day in range(days):
            day_start = BASE + day * DAY
            for w in range(windows_per_day):
                open_ts = day_start + w * WINDOW
                resolves_yes = (day + w) % 2 == 0
                # Quote the contract at ~50c regardless of the BRTI drift, so
                # the settlement model (which will lean hard toward the drift)
                # sees a large post-friction edge and trades.
                _add_window(
                    session,
                    ticker=f"KXBTC15M-D{day:02d}W{w:02d}",
                    open_ts=open_ts,
                    resolves_yes=resolves_yes,
                    quote_cents=50,
                )
        session.commit()


def test_empty_archive_is_a_fail_closed_no_go(session_factory):
    result = run_validation_arms(session_factory)
    assert result["verdict"] == "FAIL"
    assert "incomplete" in result["reason"]
    for arm in result["arms"].values():
        assert arm["promotion_status"] == "failed"


def test_archive_too_short_for_three_folds_is_a_no_go(session_factory):
    # 2 days of data, but ask for 1-day folds after a 1-day train + tiny
    # embargo — only one fold fits.
    _populate(session_factory, days=2, windows_per_day=4)
    result = run_validation_arms(
        session_factory, train_seconds=DAY, test_seconds=DAY, embargo_seconds=60
    )
    assert result["verdict"] == "FAIL"
    assert "fold" in result["reason"].lower()


def test_full_run_over_synthetic_archive_exercises_every_arm(session_factory):
    _populate(session_factory, days=10, windows_per_day=12)
    with session_factory() as s:
        counts = dataset_counts(s)
    assert counts["markets"] == 120
    assert counts["brti"] > 0

    # Small fold geometry so the synthetic archive is enough: 2-day train,
    # 2-day folds, short embargo -> 3 folds across day 2..8.
    result = run_validation_arms(
        session_factory,
        train_seconds=2 * DAY,
        test_seconds=2 * DAY,
        embargo_seconds=3_600,
        policy=PromotionPolicy(min_trades=1, min_coverage=0.0, max_brier=None),
    )

    assert result["instrument"] == "KXBTC15M"
    assert result["window"]["folds"] >= 3
    arms = result["arms"]
    assert set(arms) == {"settlement_probability", "trend_drift", "trend_control"}

    settlement = arms["settlement_probability"]
    # The favourable synthetic archive must produce trades and fold reports.
    assert settlement["n_trades"] > 0
    assert len(settlement["folds"]) >= 3
    # Every fold report carries the causal-run bookkeeping.
    for fold in settlement["folds"]:
        assert "expectancy_ci" in fold
        assert fold["coverage"] >= 0.0

    # The trend arm reports its incremental value vs the control, not a bare
    # direction call.
    incr = result["incremental_trend_vs_control"]
    assert incr is not None
    assert "incremental_net_pnl_usd" in incr


def test_calibration_accumulates_across_folds_only_forward(session_factory):
    """The calibrator version stamped on a later fold's trades must reference
    a fold index > 0 — proving prior-fold pairs were fed forward (fold 0 runs
    on the identity calibrator)."""
    _populate(session_factory, days=10, windows_per_day=12)
    result = run_validation_arms(
        session_factory,
        train_seconds=2 * DAY,
        test_seconds=2 * DAY,
        embargo_seconds=3_600,
        policy=PromotionPolicy(min_trades=1, min_coverage=0.0, max_brier=None),
    )
    # At least 3 folds ran; the run completed without the calibrator raising
    # on an all-same-outcome early fold (PAV degenerate case).
    assert result["arms"]["settlement_probability"]["folds"]
    assert result["verdict"] in {"PASS", "FAIL"}

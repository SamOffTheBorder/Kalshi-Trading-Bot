from __future__ import annotations

import pytest

from kalshi_bot.backtest.underlying import (
    UnderlyingBacktestPlan,
    UnderlyingSignal,
    run_underlying_backtest,
)
from kalshi_bot.strategy.underlying_features import UnderlyingBar


def _plan(**changes) -> UnderlyingBacktestPlan:
    values = dict(
        asset_id="BTC",
        cadence_minutes=1,
        train_start_ts=0,
        train_end_ts=240,
        validation_start_ts=420,
        validation_end_ts=540,
        holdout_start_ts=720,
        holdout_end_ts=900,
        lookback_bars=2,
        horizon_bars=1,
        purge_seconds=180,
        seed=7,
        manifest_sha256="manifest-btc",
        feature_version="features-v1",
        model_version="model-v1",
    )
    values.update(changes)
    return UnderlyingBacktestPlan(**values)


def _bars() -> tuple[UnderlyingBar, ...]:
    prices = (
        100.0, 101.0, 102.0, 101.0, 103.0, 104.0, 105.0, 104.0,
        106.0, 107.0, 108.0, 107.0, 109.0, 110.0, 111.0,
    )
    return tuple(
        UnderlyingBar("BTC", 1, i * 60, i * 60 + 60, price, i * 60 + 60)
        for i, price in enumerate(prices)
    )


def test_underlying_backtest_is_causal_asset_isolated_and_reported_by_split():
    report = run_underlying_backtest(
        (*_bars(), UnderlyingBar("ETH", 1, 0, 60, 1_000, 60)),
        _plan(allowlisted_evidence_hashes=("captured-1",)),
        lambda features: UnderlyingSignal(
            expected_return=features.return_lookback or 0.0,
            probability=0.6,
            evidence_hashes=("captured-1",),
        ),
        cost_bps=10,
    )
    assert report.asset_id == "BTC"
    assert report.holdout_evaluations == 1
    assert [segment.split for segment in report.segments] == ["train", "validation", "holdout"]
    assert all(segment.asset_id == "BTC" for segment in report.segments)
    assert report.segments[-1].brier is not None


def test_uncaptured_evidence_is_excluded_from_every_split():
    report = run_underlying_backtest(
        _bars(),
        _plan(),
        lambda _features: UnderlyingSignal(0.1, evidence_hashes=("not-captured",)),
    )
    assert report.samples == 0
    assert report.rejected_uncaptured_evidence > 0


def test_holdout_cannot_be_reused_and_purge_is_required():
    with pytest.raises(ValueError, match="purge"):
        _plan(purge_seconds=1)
    with pytest.raises(ValueError, match="already evaluated"):
        run_underlying_backtest(
            _bars(), _plan(holdout_evaluation_count=1), lambda _f: UnderlyingSignal(0)
        )

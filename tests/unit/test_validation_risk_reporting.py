import pytest

from kalshi_bot.backtest.metrics import brier_score, day_block_bootstrap_ci, trade_economics
from kalshi_bot.backtest.promotion_gate import enforce_paper_promotion
from kalshi_bot.backtest.report import (
    aggregate_reports,
    build_fold_report,
    latency_outage_sensitivity,
    parameter_stability,
)
from kalshi_bot.backtest.walkforward import purged_walkforward_folds, rolling_folds, run_walkforward
from kalshi_bot.execution.backtest_broker import Settlement
from kalshi_bot.risk.fixed_risk import FixedRiskConfig, size_validation_position


def test_validation_sizing_includes_both_leg_costs():
    config = FixedRiskConfig(risk_pct=0.01, max_position_pct=1.0)
    size = size_validation_position(
        equity_usd=1_000, entry_price_cents=40, stop_price_cents=30, config=config
    )
    assert size == 71.0  # $10 / ($0.10 + entry fee + stop fee), floored


def test_trade_economics_uses_trade_specific_prices():
    economics = trade_economics(
        entry_price_dollars=0.40,
        stop_price_dollars=0.30,
        target_price_dollars=0.60,
        quantity=10,
        modeled_win_probability=0.60,
    )
    assert economics.target_exit_fee_usd > 0
    assert economics.breakeven_win_rate > 0.0


def test_brier_and_day_bootstrap_are_deterministic():
    assert brier_score([0.8, 0.2], [True, False]) == pytest.approx(0.04)
    values = [(0, 1.0), (1, 3.0), (86_400, 2.0)]
    assert day_block_bootstrap_ci(values, samples=100, seed=4) == day_block_bootstrap_ci(
        values, samples=100, seed=4
    )


def test_walkforward_factory_is_called_once_per_fold():
    folds = rolling_folds(start_ts=0, end_ts=10, train_seconds=4, test_seconds=2, embargo_seconds=1)
    created = []
    result = run_walkforward(
        folds, lambda fold: created.append(fold.index) or (lambda _: fold.index)
    )
    assert created == [0, 1, 2]
    assert result.reports == (0, 1, 2)


def test_purged_walkforward_enforces_lookback_plus_horizon_and_expands_train():
    folds = purged_walkforward_folds(
        start_ts=0,
        end_ts=100,
        train_seconds=20,
        test_seconds=10,
        max_lookback_seconds=5,
        prediction_horizon_seconds=3,
    )
    assert folds[0].embargo_seconds == 8
    assert folds[0].train_end_ts == folds[0].test_start_ts - 8
    assert all(fold.train_start_ts == 0 for fold in folds)


def test_report_aggregates_realized_costs_and_gate_defaults_to_failure():
    settlement = Settlement("m", "yes", 1, 40, 0, True, 0.6, 0.02, 0.0, 0.58, 10)
    fold = build_fold_report(0, [settlement], candidate_count=2)
    report = aggregate_reports([fold])
    assert report.realized_cost_usd == 0.02
    assert report.promotion_status == "not_evaluated"
    gated = enforce_paper_promotion(report)
    assert gated.promotion_status == "failed"
    assert gated.promotion_reasons


def test_report_exposes_stability_and_outage_sensitivity():
    assert parameter_stability({"threshold": [0.1, 0.2]})["threshold.range"] == 0.1
    sensitivity = latency_outage_sensitivity([1.0, 3.0], {"outage": [0.0, 1.0]})
    assert sensitivity["outage.drop_usd"] == 1.5

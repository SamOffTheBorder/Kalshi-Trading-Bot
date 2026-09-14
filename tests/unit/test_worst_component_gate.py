from kalshi_bot.backtest.promotion_gate import PromotionPolicy, evaluate_promotion
from kalshi_bot.backtest.report import ComponentGateResult, FoldReport, aggregate_reports


def _fold() -> FoldReport:
    return FoldReport(0, 5, 1.0, 5.0, 1.0, None, 0.0, 0.0, 5, 0, 0, None, None)


def test_pooled_success_cannot_override_a_failed_component():
    report = aggregate_reports(
        [_fold()],
        manifest_provenance_class="source_native",
        component_gates=(
            ComponentGateResult("BTC:1m:prediction", 5, 1, True, True, True),
            ComponentGateResult(
                "SOL:1m:prediction", 0, 1, False, True, True, ("no_data",)
            ),
        ),
    )
    policy = PromotionPolicy(
        min_trades=1,
        min_folds=1,
        min_coverage=0.0,
        require_positive_ci=False,
        max_brier=None,
    )
    decision = evaluate_promotion(report, policy)
    assert not decision.passed
    assert "component_failed:SOL:1m:prediction" in decision.reasons
    assert "component_failed:SOL:1m:prediction:data" in decision.reasons

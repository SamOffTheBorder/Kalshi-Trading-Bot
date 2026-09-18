from kalshi_bot.backtest.promotion_gate import (
    PromotionPolicy,
    enforce_paper_promotion,
    evaluate_promotion,
    is_diagnostic_only,
)
from kalshi_bot.backtest.report import FoldReport, aggregate_reports

_POLICY = PromotionPolicy(
    min_trades=1, min_folds=1, min_coverage=0.0, require_positive_ci=False, max_brier=None
)


def _fold(net_pnl_usd: float) -> FoldReport:
    return FoldReport(
        fold_index=0,
        n_trades=5,
        expectancy_usd=net_pnl_usd / 5,
        net_pnl_usd=net_pnl_usd,
        coverage=1.0,
        brier=None,
        modeled_cost_usd=0.0,
        realized_cost_usd=0.0,
        fills=5,
        cancels=0,
        partial_fills=0,
        adverse_selection_usd=None,
        expectancy_ci=None,
    )


def test_source_native_manifest_is_not_diagnostic_only():
    report = aggregate_reports([_fold(10.0)], manifest_provenance_class="source_native")
    assert is_diagnostic_only(report) is False


def test_reconstructed_manifest_is_diagnostic_only():
    report = aggregate_reports([_fold(10.0)], manifest_provenance_class="reconstructed")
    assert is_diagnostic_only(report) is True


def test_unset_manifest_provenance_defaults_diagnostic_only_fail_closed():
    report = aggregate_reports([_fold(10.0)])  # manifest_provenance_class omitted
    assert is_diagnostic_only(report) is True


def test_diagnostic_only_run_that_clears_every_bar_never_reports_passed():
    """A strategy that *wins* on reconstructed history never satisfies a
    promotion criterion (§D6) -- reject-but-never-admit."""
    report = aggregate_reports([_fold(10.0)], manifest_provenance_class="reconstructed")
    decision = evaluate_promotion(report, _POLICY)
    assert decision.diagnostic_only is True
    assert decision.passed is False
    assert "diagnostic_only_requires_captured_brti_validation" in decision.reasons

    gated = enforce_paper_promotion(report, _POLICY)
    assert gated.promotion_status == "diagnostic_pending_validation"
    assert gated.promotion_status != "passed"


def test_diagnostic_only_run_that_fails_is_directly_actionable():
    """A strategy that *loses* on reconstructed history is falsified cheaply
    and its rejection is actionable on its own -- no special-casing needed
    for a failing diagnostic-only result."""
    report = aggregate_reports([_fold(-10.0)], manifest_provenance_class="reconstructed")
    decision = evaluate_promotion(report, _POLICY)
    assert decision.diagnostic_only is True
    assert decision.passed is False
    assert "diagnostic_only_requires_captured_brti_validation" not in decision.reasons

    gated = enforce_paper_promotion(report, _POLICY)
    assert gated.promotion_status == "failed"


def test_source_native_run_passes_normally_when_it_clears_the_bar():
    report = aggregate_reports([_fold(10.0)], manifest_provenance_class="source_native")
    decision = evaluate_promotion(report, _POLICY)
    assert decision.diagnostic_only is False
    assert decision.passed is True

    gated = enforce_paper_promotion(report, _POLICY)
    assert gated.promotion_status == "passed"


def test_source_native_run_fails_normally_when_it_does_not_clear_the_bar():
    report = aggregate_reports([_fold(-10.0)], manifest_provenance_class="source_native")
    gated = enforce_paper_promotion(report, _POLICY)
    assert gated.promotion_status == "failed"


def test_reconstruction_error_is_carried_onto_the_aggregate_report():
    report = aggregate_reports(
        [_fold(10.0)],
        manifest_provenance_class="reconstructed",
        reconstruction_error={"status": "measured", "resolution_agreement": 0.6},
    )
    assert report.reconstruction_error == {"status": "measured", "resolution_agreement": 0.6}

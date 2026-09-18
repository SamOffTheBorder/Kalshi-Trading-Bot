from kalshi_bot.data.quality import CoverageReport
from kalshi_bot.data.quality_policy import (
    QualityPolicy,
    evaluate_quality,
    evaluate_reconstruction_quality,
)


def test_quality_policy_exposes_fail_closed_reasons():
    empty = CoverageReport("binance", "BTCUSDT", "bar", 0, None, None, ())
    assert evaluate_quality("BTC", empty).reason == "no_data"
    stale = CoverageReport("binance", "ETHUSDT", "bar", 200, 1, 2, (), max_source_lag_ms=999000)
    assert (
        evaluate_quality("ETH", stale, policy=QualityPolicy(max_source_lag_seconds=10)).reason
        == "stale_data"
    )


def test_unmeasured_reconstruction_never_passes():
    verdict = evaluate_reconstruction_quality(
        "BTC", status="unmeasured", resolution_agreement=None
    )
    assert verdict.eligible is False
    assert verdict.reason == "unmeasured"


def test_measured_reconstruction_passes_when_threshold_is_unset():
    # The admission threshold is deliberately unset pending first
    # measurement (design.md Open Questions) -- a measured reconstruction
    # passes without a numeric bar until one is chosen.
    verdict = evaluate_reconstruction_quality(
        "BTC", status="measured", resolution_agreement=0.5
    )
    assert verdict.eligible is True


def test_measured_reconstruction_is_checked_against_an_explicit_threshold():
    policy = QualityPolicy(min_resolution_agreement=0.7)
    below = evaluate_reconstruction_quality(
        "BTC", status="measured", resolution_agreement=0.6, policy=policy
    )
    assert below.eligible is False
    assert below.reason == "resolution_agreement_below_threshold"

    above = evaluate_reconstruction_quality(
        "BTC", status="measured", resolution_agreement=0.8, policy=policy
    )
    assert above.eligible is True

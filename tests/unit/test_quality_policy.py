from kalshi_bot.data.quality import CoverageReport
from kalshi_bot.data.quality_policy import QualityPolicy, evaluate_quality


def test_quality_policy_exposes_fail_closed_reasons():
    empty = CoverageReport("binance", "BTCUSDT", "bar", 0, None, None, ())
    assert evaluate_quality("BTC", empty).reason == "no_data"
    stale = CoverageReport("binance", "ETHUSDT", "bar", 200, 1, 2, (), max_source_lag_ms=999000)
    assert (
        evaluate_quality("ETH", stale, policy=QualityPolicy(max_source_lag_seconds=10)).reason
        == "stale_data"
    )

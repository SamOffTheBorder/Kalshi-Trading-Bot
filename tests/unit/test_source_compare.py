from kalshi_bot.data.source_compare import SourcePoint, compare_sources


def _point(source, symbol, quote, ts, close, available):
    return SourcePoint(source, symbol, quote, ts, close, available)


def test_compare_sources_reports_divergence_gaps_and_lag_without_merging():
    result = compare_sources(
        [_point("binance", "BTCUSDT", "USDT", 1, 100, 10),
         _point("binance", "BTCUSDT", "USDT", 2, 102, 20)],
        [_point("coinbase", "BTC-USD", "USD", 1, 100.5, 12),
         _point("coinbase", "BTC-USD", "USD", 3, 103, 30)],
    )
    assert result.aligned_rows == 1
    assert result.left_only_rows == 1
    assert result.right_only_rows == 1
    assert result.quote_compatible is False
    assert set(result.warnings) == {"quote_currency_mismatch", "coverage_mismatch"}
    assert result.max_availability_lag == 2

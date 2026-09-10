from kalshi_bot.strategy.underlying_features import UnderlyingBar, build_underlying_features


def test_features_are_causal_and_asset_isolated():
    bars = [UnderlyingBar("BTC", 1, i * 60, (i + 1) * 60, 100 + i, (i + 1) * 60) for i in range(5)]
    bars.append(UnderlyingBar("BTC", 1, 300, 360, 999, 9999))
    bars.append(UnderlyingBar("ETH", 1, 300, 360, 1, 360))
    result = build_underlying_features(
        bars, asset_id="BTC", cadence_minutes=1, decision_ts=300, lookback_bars=2
    )
    assert result.available is True
    assert result.close == 104
    assert result.return_lookback is not None and result.return_lookback < 0.03


def test_features_fail_closed_without_history():
    result = build_underlying_features([], asset_id="SOL", cadence_minutes=15, decision_ts=100)
    assert result.available is False
    assert result.reason == "insufficient_causal_history"

from __future__ import annotations

from kalshi_bot.backtest.engine import BacktestEngine
from kalshi_bot.strategy.underlying_features import UnderlyingFeatures


def _feature(
    *, asof_ts: int, available: bool = True, alignment: str = "aligned"
) -> UnderlyingFeatures:
    return UnderlyingFeatures(
        asset_id="BTC",
        cadence_minutes=1,
        asof_ts=asof_ts,
        close=100.0,
        return_lookback=0.01,
        realized_volatility=0.02,
        sample_count=21,
        available=available,
        reason="ok" if available else "unavailable",
        source_alignment=alignment,
    )


def test_contract_ticker_features_are_asset_isolated_and_causal():
    engine = BacktestEngine.__new__(BacktestEngine)
    engine.underlying_features = (
        _feature(asof_ts=90),
        _feature(asof_ts=110),
        _feature(asof_ts=80, available=False),
        UnderlyingFeatures("ETH", 1, 70, 2_000.0, 0.01, 0.02, 21, True, "ok"),
    )

    result = engine._underlying_features_before("KXBTC15M-market", 100)

    assert [feature.asof_ts for feature in result] == [90]


def test_alignment_metadata_is_preserved_for_fail_closed_callers():
    feature = _feature(asof_ts=100, alignment="unknown")

    assert feature.source_alignment == "unknown"

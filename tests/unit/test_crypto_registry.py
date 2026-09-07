import pytest

from kalshi_bot.config.crypto_registry import (
    DEFAULT_CRYPTO_REGISTRY,
    CryptoAssetConfig,
    CryptoInstrumentConfig,
    get_asset,
    validate_registry,
)


def test_shipped_registry_has_expected_modes_and_btc_series():
    assert get_asset("BTC").instrument("15m").series_ticker == "KXBTC15M"
    assert get_asset("ETH").instrument("15m").lifecycle == "backtest"
    assert all(
        get_asset(asset).instrument("60m").lifecycle == "observe"
        for asset in ("SOL", "XRP", "DOGE", "BNB", "HYPE", "NEAR", "ZEC")
    )
    assert get_asset("LINK").event_instruments == {}


def test_duplicate_assets_and_series_are_rejected():
    with pytest.raises(ValueError, match="duplicate asset IDs"):
        validate_registry([DEFAULT_CRYPTO_REGISTRY[0], DEFAULT_CRYPTO_REGISTRY[0]])
    duplicate = CryptoAssetConfig(
        asset_id="ETH2",
        display_name="ETH2",
        correlation_group="major-crypto",
        spot_symbols=("ETH-USD",),
        event_instruments={
            "15m": CryptoInstrumentConfig(
                cadence="15m", series_ticker="KXBTC15M", contract_shape="binary"
            )
        },
    )
    with pytest.raises(ValueError, match="duplicate event series"):
        validate_registry([DEFAULT_CRYPTO_REGISTRY[0], duplicate])


def test_missing_spot_mapping_is_rejected_for_event_asset():
    with pytest.raises(ValueError, match="spot mapping"):
        CryptoAssetConfig(
            asset_id="BAD",
            display_name="Bad",
            correlation_group="major-crypto",
            event_instruments={
                "15m": CryptoInstrumentConfig(series_ticker="KXBAD15M", cadence="15m")
            },
        )

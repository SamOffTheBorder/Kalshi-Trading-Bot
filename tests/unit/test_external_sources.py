import pytest

from kalshi_bot.data.external_sources import (
    ACTIVE_CRYPTO_ASSETS,
    binance_instrument,
    primary_binance_mappings,
)


def test_primary_binance_mappings_are_exactly_requested_assets():
    assert ACTIVE_CRYPTO_ASSETS == ("BTC", "ETH", "SOL", "XRP")
    mappings = primary_binance_mappings()
    assert len(mappings) == 8
    assert {m.asset_id for m in mappings} == set(ACTIVE_CRYPTO_ASSETS)
    assert {m.market_type for m in mappings} == {"spot", "perp"}
    assert all(m.native_symbol.endswith("USDT") for m in mappings)
    assert all(m.source_role == "primary" for m in mappings)


def test_unknown_asset_cannot_be_mapped():
    with pytest.raises(ValueError, match="outside the active"):
        binance_instrument("DOGE", "spot")

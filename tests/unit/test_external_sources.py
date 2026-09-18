import pytest

from kalshi_bot.data.external_sources import (
    ACTIVE_CRYPTO_ASSETS,
    BRTI_INDEX_ID,
    binance_instrument,
    bitstamp_constituent_mappings,
    coinbase_constituent_mappings,
    gemini_constituent_mappings,
    kraken_constituent_mappings,
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


def test_binance_mappings_are_refused_the_constituent_role():
    # Binance is the deepest 1s-resolution archive available, but it is not
    # a documented BRTI constituent and is USDT- not USD-quoted. Depth of
    # coverage must never be conflated with index membership.
    mappings = primary_binance_mappings()
    assert all(m.source_role != "constituent" for m in mappings)
    assert all(m.quote_currency == "USDT" for m in mappings)
    assert all(m.target_index is None for m in mappings)


@pytest.mark.parametrize(
    "mappings_fn",
    [
        kraken_constituent_mappings,
        coinbase_constituent_mappings,
        bitstamp_constituent_mappings,
        gemini_constituent_mappings,
    ],
)
def test_constituent_mappings_declare_role_and_index_explicitly(mappings_fn):
    # Role assignment is a declared fact about each mapping, not something
    # derived from how much history the venue happens to have.
    mappings = mappings_fn()
    assert len(mappings) == len(ACTIVE_CRYPTO_ASSETS)
    assert {m.asset_id for m in mappings} == set(ACTIVE_CRYPTO_ASSETS)
    assert all(m.source_role == "constituent" for m in mappings)
    assert all(m.target_index == BRTI_INDEX_ID for m in mappings)
    assert all(m.quote_currency == "USD" for m in mappings)


def test_kraken_and_coinbase_constituents_are_usd_quoted_not_usdt():
    kraken = {m.asset_id: m for m in kraken_constituent_mappings()}
    coinbase = {m.asset_id: m for m in coinbase_constituent_mappings()}
    for asset in ACTIVE_CRYPTO_ASSETS:
        assert kraken[asset].quote_currency == "USD"
        assert coinbase[asset].quote_currency == "USD"
        assert not kraken[asset].native_symbol.upper().endswith("USDT")
        assert not coinbase[asset].native_symbol.upper().endswith("USDT")

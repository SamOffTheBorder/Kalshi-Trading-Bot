"""Typed, explicit external-market source mappings.

These mappings describe data authority and symbols; they do not grant venue
execution permission.  The importer must still discover and validate the
requested artifact before a manifest can use it.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Literal

ExternalMarketType = Literal["spot", "perp"]
SourceRole = Literal["primary", "secondary", "constituent", "manual_comparison"]

ACTIVE_CRYPTO_ASSETS: tuple[str, ...] = ("BTC", "ETH", "SOL", "XRP")

# CME CF Real-Time Index (BRTI) Constituent Platforms, per the CF Benchmarks
# methodology. Membership can drift over history; this is the current list
# (brti-constituent-history tasks.md 9.2).
BRTI_INDEX_ID = "BRTI"


@dataclass(frozen=True)
class ExternalInstrument:
    asset_id: str
    source: str
    source_role: SourceRole
    venue: str
    native_symbol: str
    market_type: ExternalMarketType
    quote_currency: str
    archive_family: str
    # The settlement index this venue is a documented constituent of. Only
    # set when source_role == "constituent"; a primary/secondary archive
    # being deep or reproducible does not imply index membership.
    target_index: str | None = None


def binance_instrument(asset_id: str, market_type: ExternalMarketType) -> ExternalInstrument:
    asset = asset_id.upper()
    if asset not in ACTIVE_CRYPTO_ASSETS:
        raise ValueError(f"asset is outside the active crypto universe: {asset_id!r}")
    family = "spot" if market_type == "spot" else "futures/um"
    return ExternalInstrument(
        asset_id=asset,
        source="binance",
        source_role="primary",
        venue="binance",
        native_symbol=f"{asset}USDT",
        market_type=market_type,
        quote_currency="USDT",
        archive_family=family,
    )


def primary_binance_mappings() -> tuple[ExternalInstrument, ...]:
    return tuple(
        instrument
        for asset in ACTIVE_CRYPTO_ASSETS
        for instrument in (binance_instrument(asset, "spot"), binance_instrument(asset, "perp"))
    )


def _constituent_instrument(
    asset_id: str, *, source: str, venue: str, native_symbol: str, archive_family: str
) -> ExternalInstrument:
    asset = asset_id.upper()
    if asset not in ACTIVE_CRYPTO_ASSETS:
        raise ValueError(f"asset is outside the active crypto universe: {asset_id!r}")
    return ExternalInstrument(
        asset_id=asset,
        source=source,
        source_role="constituent",
        venue=venue,
        native_symbol=native_symbol,
        market_type="spot",
        quote_currency="USD",
        archive_family=archive_family,
        target_index=BRTI_INDEX_ID,
    )


def kraken_constituent_instrument(asset_id: str) -> ExternalInstrument:
    """Kraken BTC/ETH/SOL/XRP USD, a documented BRTI constituent platform."""
    asset = asset_id.upper()
    return _constituent_instrument(
        asset,
        source="kraken",
        venue="kraken",
        native_symbol=f"{asset}USD" if asset != "XRP" else "XRPUSD",
        archive_family="spot",
    )


def coinbase_constituent_instrument(asset_id: str) -> ExternalInstrument:
    """Coinbase BTC/ETH/SOL/XRP USD, alongside its existing secondary role."""
    asset = asset_id.upper()
    return _constituent_instrument(
        asset,
        source="coinbase",
        venue="coinbase",
        native_symbol=f"{asset}-USD",
        archive_family="spot",
    )


def bitstamp_constituent_instrument(asset_id: str) -> ExternalInstrument:
    """Bitstamp BRTI constituent.

    Acquired via ``data/bitstamp_public.py`` (a rolling-window trade feed --
    no deep pagination, unlike Coinbase's ``cb-after`` cursor).
    """
    asset = asset_id.upper()
    return _constituent_instrument(
        asset,
        source="bitstamp",
        venue="bitstamp",
        native_symbol=f"{asset.lower()}usd",
        archive_family="spot",
    )


def gemini_constituent_instrument(asset_id: str) -> ExternalInstrument:
    """Gemini BRTI constituent.

    Acquired via ``data/gemini_public.py`` (bounded, ``since_tid``-paginated
    trade history).
    """
    asset = asset_id.upper()
    return _constituent_instrument(
        asset,
        source="gemini",
        venue="gemini",
        native_symbol=f"{asset}USD",
        archive_family="spot",
    )


def kraken_constituent_mappings() -> tuple[ExternalInstrument, ...]:
    return tuple(kraken_constituent_instrument(asset) for asset in ACTIVE_CRYPTO_ASSETS)


def coinbase_constituent_mappings() -> tuple[ExternalInstrument, ...]:
    return tuple(coinbase_constituent_instrument(asset) for asset in ACTIVE_CRYPTO_ASSETS)


def bitstamp_constituent_mappings() -> tuple[ExternalInstrument, ...]:
    return tuple(bitstamp_constituent_instrument(asset) for asset in ACTIVE_CRYPTO_ASSETS)


def gemini_constituent_mappings() -> tuple[ExternalInstrument, ...]:
    return tuple(gemini_constituent_instrument(asset) for asset in ACTIVE_CRYPTO_ASSETS)


__all__ = [
    "ACTIVE_CRYPTO_ASSETS",
    "BRTI_INDEX_ID",
    "ExternalInstrument",
    "ExternalMarketType",
    "SourceRole",
    "binance_instrument",
    "bitstamp_constituent_instrument",
    "bitstamp_constituent_mappings",
    "coinbase_constituent_instrument",
    "coinbase_constituent_mappings",
    "gemini_constituent_instrument",
    "gemini_constituent_mappings",
    "kraken_constituent_instrument",
    "kraken_constituent_mappings",
    "primary_binance_mappings",
]

"""Typed, explicit external-market source mappings.

These mappings describe data authority and symbols; they do not grant venue
execution permission.  The importer must still discover and validate the
requested artifact before a manifest can use it.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Literal

ExternalMarketType = Literal["spot", "perp"]
SourceRole = Literal["primary", "secondary", "manual_comparison"]

ACTIVE_CRYPTO_ASSETS: tuple[str, ...] = ("BTC", "ETH", "SOL", "XRP")


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


__all__ = [
    "ACTIVE_CRYPTO_ASSETS",
    "ExternalInstrument",
    "ExternalMarketType",
    "SourceRole",
    "binance_instrument",
    "primary_binance_mappings",
]

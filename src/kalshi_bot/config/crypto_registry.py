"""Canonical, operator-reviewed crypto asset registry.

The registry is deliberately data, not venue discovery: discovering a ticker
never grants it execution authority.
"""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator

Cadence = Literal["15m", "60m"]
LifecycleMode = Literal["observe", "backtest", "shadow", "paper", "live"]
ContractShape = Literal["binary", "strike_ladder"]


class CryptoInstrumentConfig(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    cadence: Cadence | None = None
    series_ticker: str | None = None
    contract_shape: ContractShape | None = None
    lifecycle: LifecycleMode = "observe"
    enabled: bool = True
    market_ticker: str | None = None


class CryptoPerpConfig(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    market_ticker: str
    reference_index: str
    multiplier: float | None = Field(default=None, gt=0)
    minimum_order_size: float | None = Field(default=None, gt=0)
    max_leverage: float | None = Field(default=None, gt=0, le=3)


class CryptoAssetConfig(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    asset_id: str = Field(pattern=r"^[A-Z0-9]+$")
    display_name: str
    correlation_group: str
    spot_symbols: tuple[str, ...] = ()
    event_instruments: dict[Cadence, CryptoInstrumentConfig] = Field(default_factory=dict)
    perp: CryptoPerpConfig | None = None

    @model_validator(mode="after")
    def validate_asset(self) -> CryptoAssetConfig:
        if not self.spot_symbols and self.event_instruments:
            raise ValueError(f"{self.asset_id}: spot mapping is required for event instruments")
        if not self.correlation_group.strip():
            raise ValueError(f"{self.asset_id}: correlation group is required")
        return self

    def instrument(self, cadence: Cadence) -> CryptoInstrumentConfig | None:
        return self.event_instruments.get(cadence)


def _event(
    asset: str, cadence: Cadence, shape: ContractShape, lifecycle: LifecycleMode
) -> CryptoInstrumentConfig:
    suffix = "15M" if cadence == "15m" else "D"
    return CryptoInstrumentConfig(
        cadence=cadence,
        series_ticker=f"KX{asset}{suffix}",
        contract_shape=shape,
        lifecycle=lifecycle,
    )


def _asset(
    asset: str,
    lifecycle: LifecycleMode,
    *,
    btc: bool = False,
    perp_lifecycle: LifecycleMode = "observe",
) -> CryptoAssetConfig:
    if btc:
        events: dict[Cadence, CryptoInstrumentConfig] = {
            "15m": CryptoInstrumentConfig(
                cadence="15m",
                series_ticker="KXBTC15M",
                contract_shape="binary",
                lifecycle=lifecycle,
            ),
            "60m": CryptoInstrumentConfig(
                cadence="60m",
                series_ticker="KXBTC",
                contract_shape="strike_ladder",
                lifecycle=lifecycle,
            ),
        }
    else:
        events = {
            "15m": _event(asset, "15m", "binary", lifecycle),
            "60m": _event(asset, "60m", "strike_ladder", lifecycle),
        }
    return CryptoAssetConfig(
        asset_id=asset,
        display_name=asset,
        correlation_group="major-crypto",
        spot_symbols=(f"{asset}-USD",),
        event_instruments=events,
        perp=CryptoPerpConfig(
            market_ticker=f"KX{asset}PERP",
            reference_index=f"{asset}USD_RTI",
        ),
    )


DEFAULT_CRYPTO_REGISTRY: tuple[CryptoAssetConfig, ...] = (
    _asset("BTC", "shadow", btc=True),
    _asset("ETH", "backtest"),
    _asset("SOL", "observe"),
    _asset("XRP", "observe"),
)


def validate_registry(
    registry: tuple[CryptoAssetConfig, ...] | list[CryptoAssetConfig],
) -> tuple[CryptoAssetConfig, ...]:
    """Validate uniqueness and required mappings before a registry is used."""
    assets = tuple(registry)
    ids = [a.asset_id for a in assets]
    if len(ids) != len(set(ids)):
        raise ValueError("duplicate asset IDs in crypto registry")
    series: list[str] = []
    for asset in assets:
        if not asset.correlation_group:
            raise ValueError(f"{asset.asset_id}: missing correlation group")
        for cadence, instrument in asset.event_instruments.items():
            if instrument.cadence != cadence:
                raise ValueError(f"{asset.asset_id}: cadence key does not match instrument")
            if instrument.series_ticker:
                series.append(instrument.series_ticker)
            if instrument.lifecycle not in {"observe", "backtest", "shadow", "paper", "live"}:
                raise ValueError(f"{asset.asset_id}: unsupported lifecycle mode")
    if len(series) != len(set(series)):
        raise ValueError("duplicate event series in crypto registry")
    return assets


def get_asset(
    asset_id: str,
    registry: tuple[CryptoAssetConfig, ...] = DEFAULT_CRYPTO_REGISTRY,
) -> CryptoAssetConfig:
    for asset in registry:
        if asset.asset_id == asset_id.upper():
            return asset
    raise KeyError(f"unknown crypto asset {asset_id!r}")


def resolve_series(
    series_ticker: str,
    registry: tuple[CryptoAssetConfig, ...] = DEFAULT_CRYPTO_REGISTRY,
) -> tuple[CryptoAssetConfig, CryptoInstrumentConfig] | None:
    for asset in registry:
        for instrument in asset.event_instruments.values():
            if instrument.series_ticker == series_ticker:
                return asset, instrument
    return None


validate_registry(DEFAULT_CRYPTO_REGISTRY)

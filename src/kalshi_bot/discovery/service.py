from __future__ import annotations

import time
from collections.abc import Callable
from dataclasses import dataclass
from typing import Any

from sqlalchemy.orm import Session

from kalshi_bot.config.crypto_registry import CryptoAssetConfig, CryptoInstrumentConfig
from kalshi_bot.storage import DiscoveryResult


@dataclass(frozen=True)
class DiscoverySnapshot:
    asset_id: str
    instrument: str
    identifier: str
    cadence: str | None
    checked_at: int
    eligible: bool
    failure_reason: str | None
    metadata: dict[str, Any]

    def persist(self, session: Session) -> DiscoveryResult:
        row = DiscoveryResult(
            asset_id=self.asset_id,
            instrument=self.instrument,
            identifier=self.identifier,
            cadence=self.cadence,
            checked_at=self.checked_at,
            eligible=self.eligible,
            failure_reason=self.failure_reason,
            metadata_json=self.metadata,
        )
        session.add(row)
        return row


def _shape_matches(series: dict[str, Any], instrument: CryptoInstrumentConfig) -> bool:
    declared = str(series.get("contract_shape") or series.get("market_shape") or "").lower()
    if not declared:
        return True  # Older public responses omit shape; market inspection remains authoritative.
    if instrument.contract_shape == "binary":
        return declared in {"binary", "yes_no", "up_down"}
    return declared in {"strike_ladder", "ladder", "binary", "yes_no"}


class EventSeriesDiscovery:
    def __init__(self, client: Any, *, clock: Callable[[], float] = time.time) -> None:
        self.client = client
        self.clock = clock

    def check(
        self, asset: CryptoAssetConfig, instrument: CryptoInstrumentConfig
    ) -> DiscoverySnapshot:
        identifier = instrument.series_ticker or ""
        now = int(self.clock())
        try:
            series = self.client.get_series(identifier)
            markets = list(self.client.iter_markets(series_ticker=identifier, status="open"))
            if not _shape_matches(series, instrument):
                raise ValueError("contract_shape_mismatch")
            if not markets:
                raise ValueError("no_active_markets")
            cadence = str(series.get("cadence") or series.get("frequency") or instrument.cadence)
            if instrument.cadence == "15m" and cadence.lower() not in {
                "15m",
                "15",
                "15minute",
                "15_minutes",
                "fifteen_min",
            }:
                raise ValueError("cadence_mismatch")
            if instrument.cadence == "60m" and cadence.lower() not in {
                "60m",
                "60",
                "hourly",
                "1h",
                "60minute",
                "hour",
            }:
                raise ValueError("cadence_mismatch")
            metadata = {
                "series": series,
                "active_market_count": len(markets),
                "market_shape": instrument.contract_shape,
            }
            return DiscoverySnapshot(
                asset.asset_id,
                "event",
                identifier,
                instrument.cadence,
                now,
                True,
                None,
                metadata,
            )
        except Exception as exc:
            return DiscoverySnapshot(
                asset.asset_id, "event", identifier, instrument.cadence, now, False, str(exc), {}
            )

    def refresh(self, asset: CryptoAssetConfig, session: Session) -> list[DiscoverySnapshot]:
        snapshots = [
            self.check(asset, instrument)
            for instrument in asset.event_instruments.values()
            if instrument.enabled
        ]
        for snapshot in snapshots:
            snapshot.persist(session)
        session.commit()
        return snapshots


class PerpDiscovery:
    def __init__(self, client: Any, *, clock: Callable[[], float] = time.time) -> None:
        self.client = client
        self.clock = clock

    def check(self, asset: CryptoAssetConfig) -> DiscoverySnapshot | None:
        if asset.perp is None:
            return None
        now = int(self.clock())
        identifier = asset.perp.market_ticker
        try:
            raw = self.client.get_market(identifier)
            metadata = {
                "multiplier": raw.get("multiplier", asset.perp.multiplier),
                "minimum_order_size": raw.get(
                    "min_order_size", raw.get("minimum_order_size", asset.perp.minimum_order_size)
                ),
                "max_leverage": raw.get("max_leverage", asset.perp.max_leverage),
                "funding_available": bool(raw.get("funding_available", False)),
                "reference_index": raw.get("reference_index", asset.perp.reference_index),
                "status": raw.get("status"),
            }
            if str(raw.get("status", "active")).lower() not in {"active", "open"}:
                raise ValueError("perp_not_active")
            return DiscoverySnapshot(
                asset.asset_id, "perp", identifier, None, now, True, None, metadata
            )
        except Exception as exc:
            return DiscoverySnapshot(
                asset.asset_id, "perp", identifier, None, now, False, str(exc), {}
            )

    def refresh(self, asset: CryptoAssetConfig, session: Session) -> DiscoverySnapshot | None:
        snapshot = self.check(asset)
        if snapshot:
            snapshot.persist(session)
            session.commit()
        return snapshot


@dataclass(frozen=True)
class CompatibilityResult:
    compatible: bool
    reason: str | None = None


def check_event_perp_compatibility(
    asset: CryptoAssetConfig,
    event: DiscoverySnapshot,
    perp: DiscoverySnapshot,
    *,
    max_age_s: int = 900,
    now: int | None = None,
) -> CompatibilityResult:
    now = int(time.time()) if now is None else now
    if event.asset_id != asset.asset_id or perp.asset_id != asset.asset_id:
        return CompatibilityResult(False, "asset_mismatch")
    if not event.eligible or not perp.eligible:
        return CompatibilityResult(False, "instrument_ineligible")
    if now - max(event.checked_at, perp.checked_at) > max_age_s:
        return CompatibilityResult(False, "stale_snapshot")
    event_index = event.metadata.get("reference_index") or event.metadata.get("settlement_index")
    perp_index = perp.metadata.get("reference_index")
    if event_index and perp_index and event_index != perp_index:
        return CompatibilityResult(False, "reference_index_mismatch")
    if event.metadata.get("market_shape") == "binary":
        return CompatibilityResult(False, "binary_event_not_linear_hedge")
    return CompatibilityResult(True)

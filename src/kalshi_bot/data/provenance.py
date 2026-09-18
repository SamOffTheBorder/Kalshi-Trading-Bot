"""Reproducibility metadata for validation datasets and deliberate captures."""

from __future__ import annotations

import hashlib
import json
import subprocess
from dataclasses import asdict, dataclass

from sqlalchemy import select
from sqlalchemy.orm import Session

from kalshi_bot.signals.fees import DEFAULT_FEE_CONFIG, DEFAULT_RESOLUTION_SPEC
from kalshi_bot.storage.models import Candle, KalshiMarket


def git_commit() -> str | None:
    try:
        return subprocess.check_output(["git", "rev-parse", "HEAD"], text=True).strip()
    except (OSError, subprocess.SubprocessError):
        return None


def dataset_fingerprint(
    session: Session, start_ts: int, end_ts: int, series: str | None = "KXBTC15M"
) -> dict[str, object]:
    """Return stable counts/hash inputs for rows consumed by a run."""
    market_query = select(KalshiMarket.ticker, KalshiMarket.open_ts, KalshiMarket.close_ts).where(
        KalshiMarket.close_ts > start_ts, KalshiMarket.open_ts <= end_ts)
    candle_query = select(Candle.market_ticker, Candle.end_period_ts, Candle.period_minutes).where(
        Candle.end_period_ts >= start_ts, Candle.end_period_ts <= end_ts)
    if series:
        market_query = market_query.where(KalshiMarket.series_ticker == series)
        candle_query = candle_query.where(Candle.series_ticker == series)
    markets = session.execute(market_query.order_by(KalshiMarket.ticker)).all()
    candles = session.execute(
        candle_query.order_by(Candle.market_ticker, Candle.end_period_ts)
    ).all()
    payload = json.dumps(
        [tuple(r) for r in markets] + [tuple(r) for r in candles], separators=(",", ":")
    )
    return {"series": series, "start_ts": start_ts, "end_ts": end_ts,
            "market_rows": len(markets), "candle_rows": len(candles),
            "sha256": hashlib.sha256(payload.encode()).hexdigest()}


@dataclass(frozen=True)
class ValidationRunConfig:
    series_ticker: str = "KXBTC15M"
    evidence_class: str = "validation"
    fee_config_version: str = DEFAULT_FEE_CONFIG.version
    resolution_config_version: str = DEFAULT_RESOLUTION_SPEC.version

    def as_dict(self) -> dict[str, object]:
        return asdict(self)

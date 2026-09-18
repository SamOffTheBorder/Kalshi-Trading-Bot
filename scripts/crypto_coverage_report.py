"""Produce a read-only BTC/ETH/SOL/XRP coverage and source comparison report.

The report compares Binance's normalized 1-minute spot history with the
independent Coinbase hourly capture where it exists. Missing secondary rows
are reported as unavailable; this command never fills, merges, or promotes a
source. It is intentionally diagnostic and cannot place orders.
"""

from __future__ import annotations

import argparse
import json
import time
from pathlib import Path
from typing import Any

from sqlalchemy import text

from kalshi_bot.config.crypto_registry import DEFAULT_CRYPTO_REGISTRY
from kalshi_bot.config.settings import Settings
from kalshi_bot.data.source_compare import SourcePoint, compare_sources
from kalshi_bot.storage.db import get_engine

ASSETS = tuple(asset.asset_id for asset in DEFAULT_CRYPTO_REGISTRY)
BINANCE_STEP_MS = 60_000
COINBASE_STEP_S = 3_600


def _coverage(
    connection: Any,
    *,
    table: str,
    filters: str,
    parameters: dict[str, object],
    step: int,
    timestamp_unit: str,
    quality_expression: str,
) -> dict[str, object]:
    query = text(
        f"""
        SELECT observed_count, first_ts, last_ts, gap_count, rejected_count
        FROM (
            SELECT
                COUNT(*) OVER () AS observed_count,
                MIN(open_ts) OVER () AS first_ts,
                MAX(open_ts) OVER () AS last_ts,
                SUM(CASE WHEN previous_ts IS NOT NULL AND open_ts - previous_ts > :step
                         THEN 1 ELSE 0 END) OVER () AS gap_count,
                SUM(CASE WHEN {quality_expression} != 'accepted' THEN 1 ELSE 0 END) OVER ()
                    AS rejected_count
            FROM (
                SELECT open_ts, {quality_expression} AS quality_status,
                       LAG(open_ts) OVER (ORDER BY open_ts) AS previous_ts
                FROM {table}
                WHERE {filters}
            ) ordered
        ) summary
        LIMIT 1
        """
    )
    row = connection.execute(query, {**parameters, "step": step}).first()
    if row is None:
        return {
            "rows": 0,
            "first_ts": None,
            "last_ts": None,
            "gap_count": 0,
            "rejected_rows": 0,
            "timestamp_unit": timestamp_unit,
        }
    return {
        "rows": int(row.observed_count),
        "first_ts": int(row.first_ts),
        "last_ts": int(row.last_ts),
        "gap_count": int(row.gap_count or 0),
        "rejected_rows": int(row.rejected_count or 0),
        "timestamp_unit": timestamp_unit,
    }


def _binance_comparison_points(connection: Any, asset_id: str) -> tuple[SourcePoint, ...]:
    rows = connection.execute(
        text(
            """
            SELECT open_ts, close, available_at, native_symbol
            FROM normalized_market_bars
            WHERE asset_id = :asset_id
              AND source = 'binance'
              AND market_type = 'spot'
              AND period_minutes = 1
              AND open_ts % :hour_ms = 0
            ORDER BY open_ts
            """
        ),
        {"asset_id": asset_id, "hour_ms": COINBASE_STEP_S * 1_000},
    ).all()
    return tuple(
        SourcePoint(
            source="binance",
            native_symbol=str(row.native_symbol),
            quote_currency="USD",
            observed_at=int(row.open_ts) // 1_000,
            close=float(row.close),
            available_at=int(row.available_at) // 1_000,
        )
        for row in rows
    )


def _coinbase_comparison_points(connection: Any, asset_id: str) -> tuple[SourcePoint, ...]:
    rows = connection.execute(
        text(
            """
            SELECT open_ts, close, available_at, symbol
            FROM spot_candles
            WHERE symbol = :symbol AND period_minutes = 60
            ORDER BY open_ts
            """
        ),
        {"symbol": f"{asset_id}-USD"},
    ).all()
    return tuple(
        SourcePoint(
            source="coinbase",
            native_symbol=str(row.symbol),
            quote_currency="USD",
            observed_at=int(row.open_ts),
            close=float(row.close),
            available_at=int(row.available_at or row.open_ts),
        )
        for row in rows
    )


def build_report(db_path: Path) -> dict[str, object]:
    engine = get_engine(Settings(db_path=db_path))
    try:
        with engine.connect() as connection:
            assets: dict[str, object] = {}
            for asset_id in ASSETS:
                primary = _coverage(
                    connection,
                    table="normalized_market_bars",
                    filters=(
                        "asset_id = :asset_id AND source = 'binance' "
                        "AND market_type = 'spot' AND period_minutes = 1"
                    ),
                    parameters={"asset_id": asset_id},
                    step=BINANCE_STEP_MS,
                    timestamp_unit="epoch_ms",
                    quality_expression="quality_status",
                )
                perp = _coverage(
                    connection,
                    table="normalized_market_bars",
                    filters=(
                        "asset_id = :asset_id AND source = 'binance' "
                        "AND market_type = 'perp' AND period_minutes = 1"
                    ),
                    parameters={"asset_id": asset_id},
                    step=BINANCE_STEP_MS,
                    timestamp_unit="epoch_ms",
                    quality_expression="quality_status",
                )
                secondary = _coverage(
                    connection,
                    table="spot_candles",
                    filters="symbol = :symbol AND period_minutes = 60",
                    parameters={"symbol": f"{asset_id}-USD"},
                    step=COINBASE_STEP_S,
                    timestamp_unit="epoch_s",
                    quality_expression="'accepted'",
                )
                left = _binance_comparison_points(connection, asset_id)
                right = _coinbase_comparison_points(connection, asset_id)
                if left and right:
                    comparison: dict[str, object] = compare_sources(left, right).as_dict()
                else:
                    comparison = {
                        "status": "unavailable",
                        "warnings": ["missing_secondary_or_primary_overlap"],
                        "binance_comparison_rows": len(left),
                        "coinbase_comparison_rows": len(right),
                    }
                assets[asset_id] = {
                    "primary_binance_spot_1m": primary,
                    "primary_binance_perp_1m": perp,
                    "secondary_coinbase_spot_1h": secondary,
                    "source_comparison": comparison,
                    "promotion_status": "diagnostic_only",
                }
    finally:
        engine.dispose()
    return {
        "report_version": "crypto-coverage-source-v1",
        "generated_at": int(time.time()),
        "assets": assets,
        "notes": [
            "No historical rows were interpolated or merged.",
            "Coverage and source comparison are diagnostic-only; no promotion decision is made.",
            "Missing Coinbase coverage remains unavailable evidence.",
        ],
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--db", type=Path, default=Path("data/kalshi_bot.db"))
    parser.add_argument("--output", type=Path, default=None)
    args = parser.parse_args()
    report = build_report(args.db)
    encoded = json.dumps(report, indent=2, sort_keys=True)
    print(encoded)
    if args.output is not None:
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(encoded + "\n", encoding="utf-8")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

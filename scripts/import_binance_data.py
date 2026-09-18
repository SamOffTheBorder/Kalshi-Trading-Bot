"""Foreground Binance archive import into the external-data schema.

This command is read-only against Binance and writes only the local database
and raw cache. It never creates an exchange client capable of submitting an
order.
"""

from __future__ import annotations

import argparse
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src"))

from kalshi_bot.config.settings import Settings
from kalshi_bot.data.binance_normalize import normalize_klines
from kalshi_bot.data.binance_public import BinancePublicClient, archive_artifact
from kalshi_bot.data.external_sources import binance_instrument
from kalshi_bot.storage.db import create_all_tables, get_engine, get_session_factory
from kalshi_bot.storage.models import NormalizedMarketBar, RawMarketArtifact


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--asset", choices=("BTC", "ETH", "SOL", "XRP"), required=True)
    parser.add_argument("--market-type", choices=("spot", "perp"), default="spot")
    parser.add_argument("--dataset", choices=("klines",), default="klines")
    parser.add_argument("--interval", default="1m")
    parser.add_argument("--year", type=int, required=True)
    parser.add_argument("--month", type=int, required=True)
    parser.add_argument("--day", type=int)
    parser.add_argument("--timestamp-unit", choices=("s", "ms", "us", "ns"), required=True)
    parser.add_argument("--db", type=Path, default=Path("data/kalshi_bot.db"))
    parser.add_argument("--raw-dir", type=Path, default=Path("data/raw/external"))
    args = parser.parse_args()

    instrument = binance_instrument(args.asset, args.market_type)
    artifact = archive_artifact(
        instrument,
        dataset=args.dataset,
        interval=args.interval,
        year=args.year,
        month=args.month,
        day=args.day,
    )
    destination = args.raw_dir / artifact.filename
    with BinancePublicClient() as client:
        digest = client.download_verified(artifact, destination)
    payload = destination.read_bytes()
    retrieved_at = int(time.time())
    parsed = normalize_klines(
        payload,
        instrument,
        interval=args.interval,
        timestamp_unit=args.timestamp_unit,
        retrieved_at=retrieved_at * 1_000,
    )

    engine = get_engine(Settings(db_path=args.db))
    create_all_tables(engine)
    with get_session_factory(engine)() as session:
        row = session.query(RawMarketArtifact).filter_by(
            source="binance", content_sha256=digest, parser_version="binance-kline-v1"
        ).one_or_none()
        if row is None:
            row = RawMarketArtifact(
                source="binance", source_role="primary", venue="binance",
                native_symbol=instrument.native_symbol, market_type=instrument.market_type,
                quote_currency=instrument.quote_currency, content_sha256=digest,
                byte_size=len(payload), source_url=artifact.url, storage_path=str(destination),
                retrieved_at=retrieved_at, checksum_status="verified",
                parser_version="binance-kline-v1", status="accepted",
            )
            session.add(row)
            session.flush()
        inserted = 0
        for item in parsed:
            # market_type is part of the identity: spot and USD-M perp share the
            # native symbol (BTCUSDT), so omitting it makes every perp bar look
            # like a duplicate of the spot bar and silently drops the series.
            exists = session.query(NormalizedMarketBar).filter_by(
                source="binance", venue="binance", native_symbol=instrument.native_symbol,
                market_type=instrument.market_type,
                period_minutes=item.period_minutes, open_ts=item.open_ts,
                parser_version=item.parser_version,
            ).one_or_none()
            if exists is not None:
                continue
            session.add(NormalizedMarketBar(
                artifact_id=row.id, source="binance", venue="binance",
                native_symbol=instrument.native_symbol, asset_id=instrument.asset_id,
                market_type=instrument.market_type, quote_currency=instrument.quote_currency,
                period_minutes=item.period_minutes, open_ts=item.open_ts, close_ts=item.close_ts,
                open=item.open, high=item.high, low=item.low, close=item.close, volume=item.volume,
                observed_at=item.observed_at, available_at=item.available_at,
                retrieved_at=item.retrieved_at, parser_version=item.parser_version,
                quality_status="accepted",
            ))
            inserted += 1
        session.commit()
    print({"asset": args.asset, "market_type": args.market_type, "artifact_sha256": digest,
           "rows_seen": len(parsed), "rows_inserted": inserted, "destination": str(destination)})
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

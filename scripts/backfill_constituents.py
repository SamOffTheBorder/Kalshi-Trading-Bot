"""Foreground, bounded constituent-venue trade backfill (brti-constituent-
history §3-4).

Downloads one venue/asset's USD trade history and normalizes it into
`normalized_aggregate_trades` with `source_role="constituent"`, following
the same immutable raw-artifact rules as `import_binance_data.py`. Read-only
against the venue's public API; never constructs an execution client.

Kraken publishes no checksum, so its artifacts are always recorded
`checksum_status="unverified"` -- never as verified.

**Kraken's download URL is itself unverified** (see
`data/kraken_public.py`'s module docstring): `data.kraken.com` does not
resolve. Confirm the real historical-trade distribution URL at
https://support.kraken.com/articles/360047124832-downloadable-historical-ohlcvt-open-high-low-close-volume-trades-data
before running `--venue kraken` for real.

Usage:
  uv run python scripts/backfill_constituents.py --venue kraken --asset BTC
  uv run python scripts/backfill_constituents.py --venue coinbase --asset ETH \
      --max-pages 10
"""

from __future__ import annotations

import argparse
import hashlib
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src"))

from kalshi_bot.config.settings import Settings
from kalshi_bot.data.coinbase_public import (
    CoinbasePublicClient,
    parse_trades,
)
from kalshi_bot.data.external_sources import (
    ACTIVE_CRYPTO_ASSETS,
    coinbase_constituent_instrument,
    kraken_constituent_instrument,
)
from kalshi_bot.data.kraken_public import (
    KrakenPublicClient,
    archive_artifact,
    raw_artifact_provenance,
)
from kalshi_bot.data.kraken_trades import normalize_kraken_trades
from kalshi_bot.storage.db import create_all_tables, get_engine, get_session_factory
from kalshi_bot.storage.models import NormalizedAggregateTrade, RawMarketArtifact


def _backfill_kraken(*, asset: str, db: Path, raw_dir: Path) -> dict[str, object]:
    instrument = kraken_constituent_instrument(asset)
    artifact = archive_artifact(instrument)
    destination = raw_dir / artifact.filename
    with KrakenPublicClient() as client:
        digest = client.download(artifact, destination)
    payload = destination.read_bytes()
    retrieved_at = int(time.time())
    provenance = raw_artifact_provenance(
        artifact, content_sha256=digest, byte_size=len(payload), retrieved_at=retrieved_at
    )
    parsed = normalize_kraken_trades(payload, instrument, retrieved_at=retrieved_at * 1_000)

    engine = get_engine(Settings(db_path=db))
    create_all_tables(engine)
    with get_session_factory(engine)() as session:
        row = (
            session.query(RawMarketArtifact)
            .filter_by(
                source="kraken", content_sha256=digest, parser_version=provenance.parser_version
            )
            .one_or_none()
        )
        if row is None:
            row = RawMarketArtifact(
                source=provenance.source,
                source_role=provenance.source_role,
                venue=provenance.venue,
                native_symbol=provenance.native_symbol,
                market_type=provenance.market_type,
                quote_currency=provenance.quote_currency,
                content_sha256=provenance.content_sha256,
                byte_size=provenance.byte_size,
                source_url=provenance.source_url,
                storage_path=str(destination),
                retrieved_at=provenance.retrieved_at,
                checksum_status=provenance.checksum_status,
                parser_version=provenance.parser_version,
                status="accepted",
            )
            session.add(row)
            session.flush()
        inserted = 0
        for item in parsed:
            exists = (
                session.query(NormalizedAggregateTrade)
                .filter_by(
                    source="kraken",
                    venue="kraken",
                    native_symbol=instrument.native_symbol,
                    trade_id=item.trade_id,
                    parser_version=item.parser_version,
                )
                .one_or_none()
            )
            if exists is not None:
                continue
            session.add(
                NormalizedAggregateTrade(
                    artifact_id=row.id,
                    source="kraken",
                    venue="kraken",
                    native_symbol=instrument.native_symbol,
                    asset_id=instrument.asset_id,
                    market_type=instrument.market_type,
                    quote_currency=instrument.quote_currency,
                    trade_id=item.trade_id,
                    observed_at=item.observed_at,
                    available_at=item.available_at,
                    retrieved_at=item.retrieved_at,
                    price=item.price,
                    quantity=item.quantity,
                    parser_version=item.parser_version,
                    quality_status="accepted",
                )
            )
            inserted += 1
        session.commit()
    return {
        "venue": "kraken",
        "asset": asset,
        "artifact_sha256": digest,
        "checksum_status": provenance.checksum_status,
        "rows_seen": len(parsed),
        "rows_inserted": inserted,
        "destination": str(destination),
    }


def _backfill_coinbase(*, asset: str, db: Path, max_pages: int) -> dict[str, object]:
    instrument = coinbase_constituent_instrument(asset)
    retrieved_at = int(time.time())
    engine = get_engine(Settings(db_path=db))
    create_all_tables(engine)
    seen = inserted = pages = 0
    with get_session_factory(engine)() as session, CoinbasePublicClient() as client:
        artifact_id = _coinbase_placeholder_artifact_id(session, instrument)
        for raw_page in client.fetch_trade_pages(
            product_id=instrument.native_symbol, max_pages=max_pages
        ):
            pages += 1
            trades = parse_trades(raw_page, asset_id=asset, retrieved_at=retrieved_at)
            seen += len(trades)
            for trade in trades:
                exists = (
                    session.query(NormalizedAggregateTrade)
                    .filter_by(
                        source="coinbase",
                        venue="coinbase",
                        native_symbol=instrument.native_symbol,
                        trade_id=trade.trade_id,
                        parser_version="coinbase-trade-v1",
                    )
                    .one_or_none()
                )
                if exists is not None:
                    continue
                session.add(
                    NormalizedAggregateTrade(
                        artifact_id=artifact_id,
                        source="coinbase",
                        venue="coinbase",
                        native_symbol=instrument.native_symbol,
                        asset_id=instrument.asset_id,
                        market_type=instrument.market_type,
                        quote_currency=instrument.quote_currency,
                        trade_id=trade.trade_id,
                        observed_at=trade.observed_at,
                        available_at=trade.available_at,
                        retrieved_at=trade.retrieved_at,
                        price=trade.price,
                        quantity=trade.quantity,
                        parser_version="coinbase-trade-v1",
                        quality_status="accepted",
                    )
                )
                inserted += 1
        session.commit()
    return {
        "venue": "coinbase",
        "asset": asset,
        "pages_fetched": pages,
        "rows_seen": seen,
        "rows_inserted": inserted,
    }


def _coinbase_placeholder_artifact_id(session, instrument) -> int:
    """Coinbase's /trades endpoint has no single downloadable archive file
    the way Kraken/Binance do, so a lightweight raw-artifact row (empty
    body) still records the API call itself for provenance continuity.

    `content_sha256` is derived from the native symbol rather than a fixed
    placeholder: the raw-artifact uniqueness constraint is
    (source, content_sha256, parser_version) with no native_symbol column,
    so a fixed all-zero hash would collide across assets sharing the same
    source/parser_version.
    """
    placeholder_hash = hashlib.sha256(
        f"coinbase-trade-placeholder:{instrument.native_symbol}".encode()
    ).hexdigest()
    row = (
        session.query(RawMarketArtifact)
        .filter_by(
            source="coinbase",
            native_symbol=instrument.native_symbol,
            parser_version="coinbase-trade-v1",
            content_sha256=placeholder_hash,
        )
        .one_or_none()
    )
    if row is not None:
        return row.id
    row = RawMarketArtifact(
        source="coinbase",
        source_role="constituent",
        venue="coinbase",
        native_symbol=instrument.native_symbol,
        market_type=instrument.market_type,
        quote_currency=instrument.quote_currency,
        content_sha256=placeholder_hash,
        byte_size=0,
        source_url="https://api.exchange.coinbase.com/products/"
        f"{instrument.native_symbol}/trades",
        storage_path="",
        retrieved_at=int(time.time()),
        checksum_status="unverified",
        parser_version="coinbase-trade-v1",
        status="accepted",
    )
    session.add(row)
    session.flush()
    return row.id


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--venue", choices=("kraken", "coinbase"), required=True)
    parser.add_argument("--asset", choices=sorted(ACTIVE_CRYPTO_ASSETS), required=True)
    parser.add_argument("--db", type=Path, default=Path("data/kalshi_bot.db"))
    parser.add_argument("--raw-dir", type=Path, default=Path("data/raw/external/kraken"))
    parser.add_argument(
        "--max-pages",
        type=int,
        default=10,
        help="Coinbase only: bounded page count (each page is a public API request)",
    )
    args = parser.parse_args()

    if args.venue == "kraken":
        result = _backfill_kraken(asset=args.asset, db=args.db, raw_dir=args.raw_dir)
    else:
        result = _backfill_coinbase(asset=args.asset, db=args.db, max_pages=args.max_pages)
    print(result)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

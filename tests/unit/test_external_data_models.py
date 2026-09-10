from sqlalchemy import create_engine, select
from sqlalchemy.orm import sessionmaker

from kalshi_bot.storage.db import create_all_tables
from kalshi_bot.storage.models import (
    DataQualityGap,
    DatasetManifest,
    NormalizedAggregateTrade,
    NormalizedMarketBar,
    RawMarketArtifact,
)


def test_external_data_tables_store_provenance_and_are_idempotency_ready():
    engine = create_engine("sqlite://")
    create_all_tables(engine)
    factory = sessionmaker(bind=engine)
    with factory() as session:
        artifact = RawMarketArtifact(
            source="binance",
            source_role="primary",
            venue="binance",
            native_symbol="BTCUSDT",
            market_type="spot",
            quote_currency="USDT",
            content_sha256="a" * 64,
            byte_size=10,
            source_url="https://data.binance.vision/example.zip",
            storage_path="data/raw/sha256/aa",
            retrieved_at=100,
            checksum_status="verified",
            parser_version="binance-v1",
        )
        session.add(artifact)
        session.flush()
        session.add(
            NormalizedMarketBar(
                artifact_id=artifact.id,
                source="binance",
                venue="binance",
                native_symbol="BTCUSDT",
                asset_id="BTC",
                market_type="spot",
                quote_currency="USDT",
                period_minutes=1,
                open_ts=100,
                close_ts=159,
                open=100.0,
                high=101.0,
                low=99.0,
                close=100.5,
                volume=2.0,
                observed_at=159,
                available_at=160,
                retrieved_at=161,
                parser_version="binance-v1",
            )
        )
        session.add(
            NormalizedAggregateTrade(
                artifact_id=artifact.id,
                source="binance",
                venue="binance",
                native_symbol="BTCUSDT",
                asset_id="BTC",
                market_type="spot",
                quote_currency="USDT",
                trade_id="1",
                observed_at=150,
                available_at=151,
                retrieved_at=152,
                price=100.2,
                quantity=0.1,
                parser_version="binance-v1",
            )
        )
        session.add(DataQualityGap(
            source="binance", venue="binance", native_symbol="BTCUSDT", asset_id="BTC",
            observation_type="bar", start_ts=200, end_ts=260, reason="missing_archive",
            created_at=300,
        ))
        session.add(DatasetManifest(
            manifest_sha256="b" * 64, created_at=400, asset_ids=["BTC"],
            source_ids=[artifact.content_sha256], start_ts=100, end_ts=300,
            parser_version="binance-v1", feature_version="features-v1",
            code_revision="test", config_sha256="c" * 64,
        ))
        session.commit()
        assert session.scalar(select(RawMarketArtifact.content_sha256)) == "a" * 64
        assert session.scalar(select(DatasetManifest.status)) == "frozen"

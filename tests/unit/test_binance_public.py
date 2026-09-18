import hashlib

import pytest

from kalshi_bot.data.binance_public import (
    BinanceArchiveError,
    archive_artifact,
    verify_checksum,
)
from kalshi_bot.data.external_sources import binance_instrument


def test_binance_archive_paths_are_explicit_and_read_only():
    spot = archive_artifact(
        binance_instrument("BTC", "spot"),
        dataset="klines",
        interval="1m",
        year=2026,
        month=9,
    )
    assert spot.filename == "BTCUSDT-1m-2026-09.zip"
    assert "/spot/monthly/klines/BTCUSDT/1m/" in spot.url
    perp = archive_artifact(
        binance_instrument("SOL", "perp"),
        dataset="aggTrades",
        interval="1m",
        year=2026,
        month=9,
        day=8,
    )
    assert "/futures/um/daily/aggTrades/SOLUSDT/1m/" in perp.url
    assert perp.checksum_url.endswith(".zip.CHECKSUM")


def test_checksum_verification_rejects_wrong_or_missing_file():
    payload = b"fixture"
    digest = hashlib.sha256(payload).hexdigest()
    assert verify_checksum(payload, f"{digest}  fixture.zip", filename="fixture.zip") == digest
    with pytest.raises(BinanceArchiveError, match="mismatch"):
        verify_checksum(payload, f"{'0' * 64}  fixture.zip", filename="fixture.zip")
    with pytest.raises(BinanceArchiveError, match="no entry"):
        verify_checksum(payload, f"{digest}  other.zip", filename="fixture.zip")


def test_archive_builder_rejects_unknown_dataset_and_asset():
    with pytest.raises(BinanceArchiveError, match="unsupported"):
        archive_artifact(
            binance_instrument("ETH", "spot"),
            dataset="bookTicker",
            interval="1m",
            year=2026,
            month=1,
        )

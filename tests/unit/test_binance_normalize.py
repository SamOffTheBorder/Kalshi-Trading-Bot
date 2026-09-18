import csv
import io
import zipfile

import pytest

from kalshi_bot.data.binance_normalize import normalize_klines
from kalshi_bot.data.external_sources import binance_instrument
from kalshi_bot.data.normalization import DataNormalizationError


def _zip_csv(rows: list[list[str]]) -> bytes:
    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, "w") as archive:
        content = io.StringIO()
        csv.writer(content, lineterminator="\n").writerows(rows)
        archive.writestr("BTCUSDT-1m.csv", content.getvalue())
    return buffer.getvalue()


def test_normalize_klines_preserves_causal_times_and_precision():
    payload = _zip_csv(
        [
            [
                "1700000000000",
                "100",
                "101",
                "99",
                "100.5",
                "2",
                "1700000059999",
                "0",
                "1",
                "0",
                "0",
                "0",
            ],
        ]
    )
    rows = normalize_klines(
        payload,
        binance_instrument("BTC", "spot"),
        interval="1m",
        timestamp_unit="ms",
        retrieved_at=1700000061000,
    )
    assert len(rows) == 1
    assert rows[0].open_ts == 1700000000000
    assert rows[0].observed_at == 1700000059999
    assert rows[0].available_at == 1700000061000
    assert rows[0].period_minutes == 1


def test_normalize_klines_rejects_bad_zip_shape_and_ordering():
    with pytest.raises(DataNormalizationError, match="valid ZIP"):
        normalize_klines(
            b"bad",
            binance_instrument("ETH", "spot"),
            interval="1m",
            timestamp_unit="ms",
            retrieved_at=1,
        )


@pytest.mark.parametrize("asset", ("BTC", "ETH", "SOL", "XRP"))
def test_all_active_assets_have_deterministic_kline_schema(asset: str):
    row = ["1000", "100", "101", "99", "100.5", "2", "59999", "0", "1", "0", "0", "0"]
    result = normalize_klines(
        _zip_csv([row]),
        binance_instrument(asset, "spot"),
        interval="1m",
        timestamp_unit="ms",
        retrieved_at=60_000,
    )
    assert result[0].instrument.asset_id == asset
    assert result[0].available_at == 60_000


def test_kline_empty_and_invalid_price_are_rejected_or_empty_without_imputation():
    assert (
        normalize_klines(
            _zip_csv([]),
            binance_instrument("BTC", "spot"),
            interval="1m",
            timestamp_unit="ms",
            retrieved_at=1,
        )
        == ()
    )
    invalid = ["1000", "-1", "1", "1", "1", "1", "1999", "0", "1", "0", "0", "0"]
    with pytest.raises(DataNormalizationError, match="invalid kline"):
        normalize_klines(
            _zip_csv([invalid]),
            binance_instrument("BTC", "spot"),
            interval="1m",
            timestamp_unit="ms",
            retrieved_at=2_000,
        )
    row = ["1000", "1", "1", "1", "1", "1", "1999", "0", "1", "0", "0", "0"]
    with pytest.raises(DataNormalizationError, match="strictly increasing"):
        normalize_klines(
            _zip_csv([row, row]),
            binance_instrument("SOL", "spot"),
            interval="1m",
            timestamp_unit="ms",
            retrieved_at=2_000,
        )


def test_microsecond_archive_inclusive_close_is_accepted():
    """Binance's real monthly archives are microsecond-precision and publish an
    INCLUSIVE close (``...59999999``) that is not millisecond-aligned. Parsing
    that column directly used to trip the sub-millisecond guard and reject the
    whole file; the close is floored to whole ms instead. Verified against
    BTCUSDT-1m-2026-07 row 1."""
    row = [
        "1782864000000000", "58624.71", "58726.07", "58624.70", "58706.01",
        "207.53912", "1782864059999999", "0", "1", "0", "0", "0",
    ]
    rows = normalize_klines(
        _zip_csv([row]),
        binance_instrument("BTC", "spot"),
        interval="1m",
        timestamp_unit="us",
        retrieved_at=1782864100000,
    )
    assert len(rows) == 1
    assert rows[0].open_ts == 1782864000000
    # Floored down within its own bar, never past the bar's true end.
    assert rows[0].close_ts == 1782864059999
    assert rows[0].open_ts < rows[0].close_ts


def test_open_timestamp_precision_is_still_enforced():
    """Only the close column is floored. A genuinely misaligned OPEN time still
    means the declared unit is wrong, and must be rejected rather than rounded."""
    row = [
        "1782864000000001", "1", "1", "1", "1",
        "1", "1782864059999999", "0", "1", "0", "0", "0",
    ]
    with pytest.raises(DataNormalizationError):
        normalize_klines(
            _zip_csv([row]),
            binance_instrument("BTC", "spot"),
            interval="1m",
            timestamp_unit="us",
            retrieved_at=1782864100000,
        )


def test_futures_archive_header_row_is_skipped():
    """Binance USD-M futures archives ship a CSV header row (and millisecond
    timestamps); spot archives ship neither. The header must be skipped without
    dropping a real first data row. Verified against the perp 2026-07 archive."""
    header = [
        "open_time", "open", "high", "low", "close", "volume",
        "close_time", "quote_volume", "count", "taker_buy_volume",
        "taker_buy_quote_volume", "ignore",
    ]
    data = [
        "1782864000000", "58605.40", "58688.50", "58605.40", "58675.80",
        "113.536", "1782864059999", "0", "1", "0", "0", "0",
    ]
    rows = normalize_klines(
        _zip_csv([header, data]),
        binance_instrument("BTC", "perp"),
        interval="1m",
        timestamp_unit="ms",
        retrieved_at=1782864100000,
    )
    assert len(rows) == 1
    assert rows[0].open_ts == 1782864000000
    assert rows[0].open == 58605.40


def test_headerless_first_row_is_not_dropped():
    """Skipping the header by shape must never eat a legitimate first bar."""
    data = [
        "1782864000000", "1", "2", "0.5", "1.5",
        "10", "1782864059999", "0", "1", "0", "0", "0",
    ]
    rows = normalize_klines(
        _zip_csv([data]),
        binance_instrument("BTC", "perp"),
        interval="1m",
        timestamp_unit="ms",
        retrieved_at=1782864100000,
    )
    assert len(rows) == 1
    assert rows[0].open_ts == 1782864000000

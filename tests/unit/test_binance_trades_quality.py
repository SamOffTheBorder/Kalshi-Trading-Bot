import csv
import io
import zipfile

import pytest

from kalshi_bot.data.binance_trades import normalize_aggregate_trades
from kalshi_bot.data.external_sources import binance_instrument
from kalshi_bot.data.quality import coverage_report


def _zip_rows(rows):
    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, "w") as archive:
        text = io.StringIO()
        csv.writer(text, lineterminator="\n").writerows(rows)
        archive.writestr("trades.csv", text.getvalue())
    return buffer.getvalue()


def test_aggregate_trade_normalization_preserves_aggressor_and_availability():
    rows = normalize_aggregate_trades(
        _zip_rows(
            [
                ["1", "100", "2", "1", "1", "1000", "true"],
                ["2", "101", "1", "2", "2", "1100", "false"],
            ]
        ),
        binance_instrument("BTC", "perp"),
        timestamp_unit="ms",
        retrieved_at=2_000,
    )
    assert rows[0].aggressor_side == "sell"
    assert rows[1].aggressor_side == "buy"
    assert rows[0].available_at == 2_000


def test_trade_ids_and_quality_gaps_are_fail_closed():
    with pytest.raises(ValueError, match="strictly increasing"):
        normalize_aggregate_trades(
            _zip_rows(
                [
                    ["2", "100", "1", "1", "1", "1000", "true"],
                    ["1", "100", "1", "1", "1", "1100", "true"],
                ]
            ),
            binance_instrument("ETH", "spot"),
            timestamp_unit="ms",
            retrieved_at=2_000,
        )
    report = coverage_report(
        [0, 60, 180],
        source="binance",
        native_symbol="SOLUSDT",
        observation_type="bar",
        expected_step=60,
    )
    assert report.gaps == ((120, 180),)
    assert report.as_dict()["rows"] == 3


def test_trade_normalization_rejects_empty_zip_and_invalid_size():
    assert (
        normalize_aggregate_trades(
            _zip_rows([]), binance_instrument("XRP", "spot"), timestamp_unit="ms", retrieved_at=1
        )
        == ()
    )
    with pytest.raises(ValueError, match="positive"):
        normalize_aggregate_trades(
            _zip_rows([["1", "100", "0", "1", "1", "1000", "true"]]),
            binance_instrument("XRP", "spot"),
            timestamp_unit="ms",
            retrieved_at=2_000,
        )

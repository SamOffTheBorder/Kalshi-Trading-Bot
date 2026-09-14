import pytest

from kalshi_bot.data.external_sources import (
    binance_instrument,
    kraken_constituent_instrument,
)
from kalshi_bot.data.kraken_trades import (
    KrakenTradeParseError,
    normalize_kraken_trades,
)


def _rows(*lines: str) -> bytes:
    return ("\n".join(lines) + "\n").encode("utf-8")


def test_normalizes_fractional_second_timestamps_and_availability():
    payload = _rows("100.5,2.0,1000.250", "101.0,1.0,1001.750")
    rows = normalize_kraken_trades(
        payload, kraken_constituent_instrument("BTC"), retrieved_at=1_010_000
    )
    assert len(rows) == 2
    assert rows[0].observed_at == 1_000_250
    assert rows[1].observed_at == 1_001_750
    assert rows[0].available_at == 1_010_000  # retrieved_at dominates
    assert rows[0].trade_id != rows[1].trade_id


def test_requires_constituent_kraken_instrument():
    with pytest.raises(KrakenTradeParseError, match="constituent"):
        normalize_kraken_trades(
            _rows("100,1,1000"), binance_instrument("BTC", "spot"), retrieved_at=1
        )


def test_malformed_csv_row_is_rejected():
    with pytest.raises(KrakenTradeParseError, match="columns"):
        normalize_kraken_trades(
            _rows("100,1"), kraken_constituent_instrument("BTC"), retrieved_at=1
        )
    with pytest.raises(KrakenTradeParseError, match="invalid trade row"):
        normalize_kraken_trades(
            _rows("not-a-number,1,1000"), kraken_constituent_instrument("BTC"), retrieved_at=1
        )


def test_empty_archive_returns_empty_tuple():
    assert normalize_kraken_trades(b"", kraken_constituent_instrument("BTC"), retrieved_at=1) == ()
    assert (
        normalize_kraken_trades(b"\n\n", kraken_constituent_instrument("BTC"), retrieved_at=1)
        == ()
    )


def test_duplicate_rows_get_the_same_synthetic_id_not_rejected():
    # Kraken publishes no trade ID; two textually-identical rows (a genuine
    # duplicate print in the export) synthesize the same id rather than
    # raising -- the strictly-increasing check operates on time, not id.
    payload = _rows("100,1,1000", "100,1,1000")
    rows = normalize_kraken_trades(payload, kraken_constituent_instrument("BTC"), retrieved_at=1)
    assert len(rows) == 2
    assert rows[0].trade_id == rows[1].trade_id


def test_non_monotonic_timestamps_are_rejected():
    payload = _rows("100,1,1000", "101,1,999")
    with pytest.raises(KrakenTradeParseError, match="monotonic"):
        normalize_kraken_trades(payload, kraken_constituent_instrument("BTC"), retrieved_at=1)


def test_mixed_time_precision_is_handled_via_float_seconds():
    # Whole-second and fractional-second rows both parse through the same
    # float-seconds path without unit ambiguity.
    payload = _rows("100,1,1000", "101,1,1000.5")
    rows = normalize_kraken_trades(payload, kraken_constituent_instrument("BTC"), retrieved_at=1)
    assert rows[0].observed_at == 1_000_000
    assert rows[1].observed_at == 1_000_500


def test_non_positive_price_or_quantity_is_rejected():
    with pytest.raises(KrakenTradeParseError, match="positive"):
        normalize_kraken_trades(
            _rows("0,1,1000"), kraken_constituent_instrument("BTC"), retrieved_at=1
        )
    with pytest.raises(KrakenTradeParseError, match="positive"):
        normalize_kraken_trades(
            _rows("100,0,1000"), kraken_constituent_instrument("BTC"), retrieved_at=1
        )

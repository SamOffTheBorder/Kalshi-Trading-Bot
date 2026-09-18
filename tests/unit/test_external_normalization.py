import pytest

from kalshi_bot.data.normalization import (
    DataNormalizationError,
    causal_available_at,
    epoch_ms,
)


def test_explicit_timestamp_units_are_converted_to_ms():
    assert epoch_ms(1_700_000_000, unit="s") == 1_700_000_000_000
    assert epoch_ms(1_700_000_000_123, unit="ms") == 1_700_000_000_123
    assert epoch_ms(1_700_000_000_000, unit="us") == 1_700_000_000
    assert epoch_ms(1_700_000_000_000_000, unit="ns") == 1_700_000_000


def test_timestamp_unit_and_causal_availability_fail_closed():
    with pytest.raises(DataNormalizationError, match="sub-millisecond"):
        epoch_ms(1_001, unit="us")
    with pytest.raises(DataNormalizationError):
        epoch_ms(-1, unit="ms")
    with pytest.raises(DataNormalizationError):
        epoch_ms(True, unit="s")
    assert causal_available_at(observed_at_ms=100, retrieved_at_ms=120) == 120
    assert causal_available_at(observed_at_ms=140, retrieved_at_ms=120) == 140

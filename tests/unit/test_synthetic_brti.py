import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from kalshi_bot.data.external_sources import (
    binance_instrument,
    coinbase_constituent_instrument,
    kraken_constituent_instrument,
)
from kalshi_bot.data.synthetic_brti import (
    CompositionError,
    ConstituentTrade,
    compose_synthetic_brti,
    persist_reconstructed_seconds,
)
from kalshi_bot.storage.db import create_all_tables
from kalshi_bot.storage.models import ReconstructedIndexObservation

KRAKEN_BTC = kraken_constituent_instrument("BTC")
COINBASE_BTC = coinbase_constituent_instrument("BTC")
BINANCE_BTC = binance_instrument("BTC", "spot")


def _trade(instrument, second, price, ms_offset=0):
    return ConstituentTrade(
        instrument=instrument, observed_at_ms=second * 1_000 + ms_offset, price=price
    )


def test_single_venue_second_uses_that_venues_price():
    result = compose_synthetic_brti(
        {"kraken": (_trade(KRAKEN_BTC, 100, 50_000.0),)}, start_ts=100, end_ts=101
    )
    assert len(result.seconds) == 1
    row = result.seconds[0]
    assert row.value == 50_000.0
    assert row.contributor_count == 1
    assert row.contributing_venues == ("kraken",)


def test_two_venue_second_is_the_median():
    result = compose_synthetic_brti(
        {
            "kraken": (_trade(KRAKEN_BTC, 100, 50_000.0),),
            "coinbase": (_trade(COINBASE_BTC, 100, 50_100.0),),
        },
        start_ts=100,
        end_ts=101,
    )
    row = result.seconds[0]
    assert row.value == 50_050.0
    assert row.contributor_count == 2
    assert row.contributing_venues == ("coinbase", "kraken")


def test_all_silent_second_is_a_gap_not_a_value():
    result = compose_synthetic_brti({"kraken": ()}, start_ts=100, end_ts=103)
    assert result.seconds == ()
    assert result.gap_seconds == (100, 101, 102)


def test_a_venue_silent_for_one_second_does_not_forward_fill():
    result = compose_synthetic_brti(
        {
            "kraken": (_trade(KRAKEN_BTC, 100, 50_000.0), _trade(KRAKEN_BTC, 102, 50_200.0)),
            "coinbase": (_trade(COINBASE_BTC, 100, 50_100.0),),
        },
        start_ts=100,
        end_ts=103,
    )
    by_second = {row.observed_at: row for row in result.seconds}
    assert by_second[100].contributor_count == 2
    assert 101 not in by_second
    assert 101 in result.gap_seconds
    assert by_second[102].contributor_count == 1
    assert by_second[102].value == 50_200.0


def test_outlier_print_is_resisted_by_median_not_mean():
    result = compose_synthetic_brti(
        {
            "kraken": (_trade(KRAKEN_BTC, 100, 50_000.0),),
            "coinbase": (_trade(COINBASE_BTC, 100, 50_010.0),),
            # A third, wildly-off constituent (e.g. a fat-finger print).
            "gemini": (_trade(kraken_constituent_instrument("BTC"), 100, 999_999.0),),
        },
        start_ts=100,
        end_ts=101,
    )
    assert result.seconds[0].value == 50_010.0


def test_venue_with_a_stale_run_of_prints_only_covers_seconds_it_actually_traded():
    # Kraken has one print at t=100 and nothing again until t=105 -- a
    # "stale run" should show up as gaps for 101-104, not a flat line.
    result = compose_synthetic_brti(
        {"kraken": (_trade(KRAKEN_BTC, 100, 50_000.0), _trade(KRAKEN_BTC, 105, 50_500.0))},
        start_ts=100,
        end_ts=106,
    )
    observed = {row.observed_at for row in result.seconds}
    assert observed == {100, 105}
    assert set(result.gap_seconds) == {101, 102, 103, 104}


def test_non_constituent_input_is_refused_not_silently_dropped():
    result = compose_synthetic_brti(
        {
            "kraken": (_trade(KRAKEN_BTC, 100, 50_000.0),),
            "binance": (_trade(BINANCE_BTC, 100, 50_000.0),),
        },
        start_ts=100,
        end_ts=101,
    )
    assert len(result.refusals) == 1
    assert result.refusals[0].venue == "binance"
    assert "non-constituent" in result.refusals[0].reason
    # Kraken still composes; only binance was refused.
    assert result.seconds[0].contributor_count == 1
    assert result.seconds[0].contributing_venues == ("kraken",)


def test_quote_currency_mismatch_is_refused():
    usdt_kraken = kraken_constituent_instrument("BTC")
    usdt_kraken = usdt_kraken.__class__(**{**usdt_kraken.__dict__, "quote_currency": "USDT"})
    result = compose_synthetic_brti(
        {"kraken": (_trade(usdt_kraken, 100, 50_000.0),)}, start_ts=100, end_ts=101
    )
    assert result.refusals[0].reason.count("quote_currency_mismatch") == 1
    assert result.seconds == ()


def test_start_ts_must_precede_end_ts():
    with pytest.raises(CompositionError, match="precede"):
        compose_synthetic_brti({}, start_ts=100, end_ts=100)


def test_persisted_rows_are_never_in_brti_observations_table():
    engine = create_engine("sqlite://")
    create_all_tables(engine)
    result = compose_synthetic_brti(
        {"kraken": (_trade(KRAKEN_BTC, 100, 50_000.0),)}, start_ts=100, end_ts=101
    )
    with sessionmaker(bind=engine)() as session:
        written = persist_reconstructed_seconds(session, result, composed_at=1_000)
        session.commit()
        assert written == 1
        row = session.query(ReconstructedIndexObservation).one()
        assert row.provenance == "reconstructed_index"
        assert row.contributing_venues == ["kraken"]


def test_reconstructed_values_are_invisible_to_the_captured_brti_read_path():
    from kalshi_bot.data.brti_index_read import read_captured_brti

    engine = create_engine("sqlite://")
    create_all_tables(engine)
    result = compose_synthetic_brti(
        {"kraken": (_trade(KRAKEN_BTC, 100, 50_000.0),)}, start_ts=100, end_ts=101
    )
    with sessionmaker(bind=engine)() as session:
        persist_reconstructed_seconds(session, result, composed_at=1_000)
        session.commit()
        read = read_captured_brti(session, start_ts=100, end_ts=101)
        assert read.sufficient is False
        assert read.reason == "insufficient_captured_data"
        assert read.readings == ()

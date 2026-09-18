"""Representative cross-venue rows survive schema creation and upgrades."""

from sqlalchemy import create_engine, select, text
from sqlalchemy.orm import Session

from kalshi_bot.storage import create_all_tables
from kalshi_bot.storage.migrations import SCHEMA_VERSION
from kalshi_bot.storage.models import (
    BRTIObservation,
    KalshiMarket,
    SimulatedTrade,
    SportsMarketDiscovery,
    SportsSeries,
)


def test_cross_venue_rows_round_trip_with_current_schema() -> None:
    engine = create_engine("sqlite://")
    create_all_tables(engine)
    with Session(engine) as session:
        session.add_all(
            [
                KalshiMarket(
                    ticker="KXBTC15M-26SEP0512-T100000",
                    series_ticker="KXBTC15M",
                    open_ts=1_700_000_000,
                    close_ts=1_700_000_900,
                    status="active",
                    result=None,
                ),
                BRTIObservation(
                    observed_at=1_700_000_100,
                    available_at=1_700_000_101,
                    value_dollars="100000.25",
                    source="cfbenchmarks",
                ),
                SportsSeries(
                    series_ticker="KXNBAGAME",
                    sport="basketball",
                    title="NBA game",
                    observed_at=1_700_000_100,
                    available_at=1_700_000_101,
                ),
                SportsMarketDiscovery(
                    series_ticker="KXNBAGAME",
                    market_ticker="KXNBAGAME-26SEP05-LAL",
                    sport="basketball",
                    observed_at=1_700_000_100,
                    available_at=1_700_000_101,
                    eligible=False,
                    failure_reason="missing_depth",
                ),
                SimulatedTrade(
                    mode="paper",
                    market_ticker="BTC-PERP",
                    side="long",
                    quantity=0.01,
                    entry_price_cents=100000,
                    entry_ts=1_700_000_101,
                    status="open",
                ),
            ]
        )
        session.commit()
        assert session.execute(select(KalshiMarket)).scalar_one().ticker.startswith("KXBTC")
        assert session.execute(select(BRTIObservation)).scalar_one().value_dollars == "100000.25"
        assert session.execute(select(SportsSeries)).scalar_one().sport == "basketball"
        assert session.execute(select(SportsMarketDiscovery)).scalar_one().eligible is False
        assert session.execute(select(SimulatedTrade)).scalar_one().quantity == 0.01

    with engine.connect() as conn:
        assert conn.execute(text("PRAGMA user_version")).scalar_one() == SCHEMA_VERSION

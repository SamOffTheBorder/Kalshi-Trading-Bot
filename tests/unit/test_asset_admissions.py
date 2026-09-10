import time

from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from kalshi_bot.storage import DiscoveryResult, create_all_tables
from kalshi_bot.web.queries import asset_admissions


def _btc15m(session, now_ts):
    return next(
        item
        for item in asset_admissions(session, now_ts=now_ts)
        if item.asset_id == "BTC" and item.domain == "prediction" and item.cadence == "15m"
    )


def test_asset_admissions_never_treats_discovery_as_source_alignment():
    """A verified, fresh snapshot that is *not* source-aligned is still not
    eligible on the dashboard (multi-venue-paper-trading §12.2)."""
    engine = create_engine("sqlite://")
    create_all_tables(engine)
    now = int(time.time())
    with sessionmaker(bind=engine)() as session:
        session.add(
            DiscoveryResult(
                asset_id="BTC",
                instrument="event",
                cadence="15m",
                identifier="KXBTC15M",
                checked_at=now,
                eligible=True,
                failure_reason=None,
                metadata_json={},  # no source_aligned flag
            )
        )
        session.commit()
        btc = _btc15m(session, now)
        assert btc.discovered is True
        assert btc.source_aligned is False
        assert btc.eligible is False
        assert btc.blocker == "source_not_aligned"


def test_fresh_aligned_verified_snapshot_is_eligible():
    engine = create_engine("sqlite://")
    create_all_tables(engine)
    now = int(time.time())
    with sessionmaker(bind=engine)() as session:
        session.add(
            DiscoveryResult(
                asset_id="BTC",
                instrument="event",
                cadence="15m",
                identifier="KXBTC15M",
                checked_at=now - 60,
                eligible=True,
                failure_reason=None,
                metadata_json={"source_aligned": True},
            )
        )
        session.commit()
        btc = _btc15m(session, now)
        assert btc.eligible is True
        assert btc.blocker is None


def test_stale_snapshot_never_renders_eligible():
    """Even a verified + aligned snapshot that is too old must not read as
    eligible — staleness is a first-class blocker (§12.2)."""
    engine = create_engine("sqlite://")
    create_all_tables(engine)
    now = int(time.time())
    with sessionmaker(bind=engine)() as session:
        session.add(
            DiscoveryResult(
                asset_id="ETH",
                instrument="event",
                cadence="15m",
                identifier="KXETH15M",
                checked_at=now - 10_000,  # well past DISCOVERY_FRESH_MAX_AGE_S
                eligible=True,
                failure_reason=None,
                metadata_json={"source_aligned": True},
            )
        )
        session.commit()
        eth = next(
            item
            for item in asset_admissions(session, now_ts=now)
            if item.asset_id == "ETH" and item.domain == "prediction"
        )
        assert eth.eligible is False
        assert eth.blocker == "stale_discovery_snapshot"


def test_undiscovered_asset_is_not_eligible():
    engine = create_engine("sqlite://")
    create_all_tables(engine)
    with sessionmaker(bind=engine)() as session:
        rows = asset_admissions(session, now_ts=int(time.time()))
    assert rows, "registry should yield admission rows even with no discovery"
    assert all(not r.eligible for r in rows)
    assert all(r.blocker == "not_discovered" for r in rows)


def test_failure_reason_takes_precedence_as_blocker():
    engine = create_engine("sqlite://")
    create_all_tables(engine)
    now = int(time.time())
    with sessionmaker(bind=engine)() as session:
        session.add(
            DiscoveryResult(
                asset_id="SOL",
                instrument="event",
                cadence="15m",
                identifier="KXSOL15M",
                checked_at=now,
                eligible=False,
                failure_reason="one_sided_quote",
                metadata_json={"source_aligned": True},
            )
        )
        session.commit()
        sol = next(
            item
            for item in asset_admissions(session, now_ts=now)
            if item.asset_id == "SOL" and item.domain == "prediction"
        )
        assert sol.eligible is False
        assert sol.blocker == "one_sided_quote"

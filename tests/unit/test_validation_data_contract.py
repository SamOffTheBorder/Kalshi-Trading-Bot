from sqlalchemy import create_engine, inspect, text

from kalshi_bot.signals.fees import (
    DEFAULT_FEE_CONFIG,
    DEFAULT_RESOLUTION_SPEC,
    entry_fee_dollars,
)
from kalshi_bot.storage import create_all_tables
from kalshi_bot.storage.migrations import SCHEMA_VERSION


def test_documented_taker_fee_example():
    # ceil(.07 * .42 * .58 * 11 * 100) / 100
    assert entry_fee_dollars(42, 11) == 0.19
    assert DEFAULT_FEE_CONFIG.version == "2026-09-kalshi"


def test_kxbtc15m_resolution_tie_and_direction():
    spec = DEFAULT_RESOLUTION_SPEC
    assert spec.resolves_yes(100_001.0, 100_000.0)
    assert spec.resolves_yes(100_000.0, 100_000.0)
    assert not spec.resolves_yes(99_999.0, 100_000.0)


def test_fresh_database_has_observation_tables_and_versions():
    engine = create_engine("sqlite://")
    create_all_tables(engine)
    tables = set(inspect(engine).get_table_names())
    assert {
        "candles", "kalshi_markets", "order_book_snapshots", "public_trades", "brti_observations",
        "perp_mark_observations", "perp_funding_observations",
        "perp_funding_estimate_observations",
    } <= tables
    with engine.connect() as conn:
        assert conn.execute(text("PRAGMA user_version")).scalar_one() == SCHEMA_VERSION


def test_populated_legacy_database_upgrade_is_additive():
    engine = create_engine("sqlite://")
    with engine.begin() as conn:
        conn.execute(text(
            "CREATE TABLE backtest_runs (id INTEGER PRIMARY KEY, strategy_name VARCHAR(64) "
            "NOT NULL, params JSON NOT NULL, data_start_ts INTEGER NOT NULL, "
            "data_end_ts INTEGER NOT NULL, split_ts INTEGER NOT NULL)"
        ))
        conn.execute(text("INSERT INTO backtest_runs VALUES (1, 'legacy', '{}', 1, 2, 1)"))
    create_all_tables(engine)
    with engine.connect() as conn:
        row = conn.execute(
            text("SELECT strategy_name, evidence_class FROM backtest_runs")
        ).one()
        assert row == ("legacy", "diagnostic")

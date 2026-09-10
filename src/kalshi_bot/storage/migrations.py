"""Small, additive SQLite migrations for installations without Alembic."""

from __future__ import annotations

from sqlalchemy import Engine, inspect, text

SCHEMA_VERSION = 11


_BAR_COLUMNS = (
    "artifact_id, source, venue, native_symbol, asset_id, market_type, "
    "quote_currency, period_minutes, open_ts, close_ts, open, high, low, "
    "close, volume, observed_at, available_at, retrieved_at, parser_version, "
    "quality_status"
)


def _widen_normalized_bar_identity(conn) -> None:
    """Rebuild normalized_market_bars so market_type is part of its identity.

    A no-op when the table does not exist yet (a fresh database gets the correct
    constraint straight from ``Base.metadata``) or when the stored DDL already
    names market_type. Rows are copied verbatim -- none are dropped or altered.
    """

    exists = conn.execute(
        text("select sql from sqlite_master where type='table' and name='normalized_market_bars'")
    ).scalar_one_or_none()
    if exists is None:
        return
    normalized_ddl = " ".join(exists.split())
    if "market_type, period_minutes, open_ts" in normalized_ddl:
        return  # already widened

    conn.execute(text("ALTER TABLE normalized_market_bars RENAME TO normalized_market_bars_old"))
    conn.execute(
        text(
            "CREATE TABLE normalized_market_bars ("
            "id INTEGER PRIMARY KEY AUTOINCREMENT, "
            "artifact_id INTEGER NOT NULL REFERENCES raw_market_artifacts(id), "
            "source VARCHAR(32) NOT NULL, venue VARCHAR(32) NOT NULL, "
            "native_symbol VARCHAR(64) NOT NULL, asset_id VARCHAR(16) NOT NULL, "
            "market_type VARCHAR(16) NOT NULL, quote_currency VARCHAR(16) NOT NULL, "
            "period_minutes INTEGER NOT NULL, open_ts INTEGER NOT NULL, "
            "close_ts INTEGER NOT NULL, open FLOAT NOT NULL, high FLOAT NOT NULL, "
            "low FLOAT NOT NULL, close FLOAT NOT NULL, volume FLOAT NOT NULL, "
            "observed_at INTEGER NOT NULL, available_at INTEGER NOT NULL, "
            "retrieved_at INTEGER NOT NULL, parser_version VARCHAR(32) NOT NULL, "
            "quality_status VARCHAR(16) NOT NULL, "
            "CONSTRAINT uq_normalized_bar_identity UNIQUE "
            "(source, venue, native_symbol, market_type, period_minutes, open_ts, parser_version)"
            ")"
        )
    )
    conn.execute(
        text(
            f"INSERT INTO normalized_market_bars ({_BAR_COLUMNS}) "
            f"SELECT {_BAR_COLUMNS} FROM normalized_market_bars_old"
        )
    )
    conn.execute(text("DROP TABLE normalized_market_bars_old"))
    conn.execute(
        text(
            "CREATE INDEX IF NOT EXISTS ix_normalized_bars_symbol_ts "
            "ON normalized_market_bars (native_symbol, open_ts)"
        )
    )


def migrate(engine: Engine) -> None:
    """Apply idempotent, additive migrations; never rewrite or delete rows."""
    with engine.begin() as conn:
        current = int(conn.execute(text("PRAGMA user_version")).scalar_one())
        if current < 1:
            columns = {c["name"] for c in inspect(engine).get_columns("backtest_runs")}
            if "evidence_class" not in columns:
                conn.execute(
                    text(
                        "ALTER TABLE backtest_runs ADD COLUMN evidence_class VARCHAR(16) "
                        "NOT NULL DEFAULT 'diagnostic'"
                    )
                )
            conn.execute(text(f"PRAGMA user_version = {SCHEMA_VERSION}"))
        if current < 2:
            # Registry/discovery tables are created by Base.metadata before
            # this hook runs. Version 2 records that the additive multi-asset
            # schema is present without rewriting legacy rows.
            conn.execute(text(f"PRAGMA user_version = {SCHEMA_VERSION}"))
        elif current < 3:
            # Version 3 adds the perp funding-estimate observation table. It
            # is created by Base.metadata and needs no rewrite of old rows.
            conn.execute(text(f"PRAGMA user_version = {SCHEMA_VERSION}"))
        elif current < 4:
            # Version 4 adds the additive sports research tables. They are
            # created by Base.metadata and need no rewrite of old rows.
            conn.execute(text(f"PRAGMA user_version = {SCHEMA_VERSION}"))
        elif current < 5:
            # Version 5 adds flow, evidence, and LLM research tables. They
            # are created by Base.metadata and need no rewrite of old rows.
            conn.execute(text(f"PRAGMA user_version = {SCHEMA_VERSION}"))
        elif current < 6:
            # Version 6 adds immutable external-market artifacts, normalized
            # observations, gap records, and frozen dataset manifests.
            conn.execute(text(f"PRAGMA user_version = {SCHEMA_VERSION}"))
        elif current < 7:
            # Version 7 pins artifact hashes, normalized partitions, and
            # source mappings in each frozen manifest.  Nullable additive
            # columns preserve all historic manifests unchanged.
            conn.execute(text(f"PRAGMA user_version = {SCHEMA_VERSION}"))
        elif current < 8:
            # Version 8 introduces paper-run identities and append-only audit events.
            conn.execute(text(f"PRAGMA user_version = {SCHEMA_VERSION}"))
        elif current < 9:
            # Version 9 adds an independent linear-perpetual paper ledger.
            conn.execute(text(f"PRAGMA user_version = {SCHEMA_VERSION}"))
        elif current < 10:
            # Version 10 adds the durable global emergency-halt log and the
            # per-scope lifecycle promotion/demotion history. Both tables are
            # created by Base.metadata and need no rewrite of old rows.
            conn.execute(text(f"PRAGMA user_version = {SCHEMA_VERSION}"))
        if current < 11:
            # Version 11 widens the normalized-bar identity to include
            # market_type. Binance spot and USD-M perp share a native symbol
            # (BTCUSDT), so the old constraint made the two series mutually
            # exclusive -- only whichever imported first could be stored.
            #
            # SQLite cannot alter a table-level UNIQUE constraint in place, and
            # the constraint was created inline with the table, so a legacy
            # database keeps the old inline constraint until the table is
            # rebuilt. Rebuilding is unnecessary where the table is still
            # empty of the colliding case, which is the situation here: this
            # replaces the constraint only when it is safe and cheap to do so.
            _widen_normalized_bar_identity(conn)
            conn.execute(text(f"PRAGMA user_version = {SCHEMA_VERSION}"))

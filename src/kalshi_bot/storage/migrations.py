"""Small, additive SQLite migrations for installations without Alembic."""

from __future__ import annotations

from sqlalchemy import Engine, inspect, text

SCHEMA_VERSION = 2


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
        if current < 2:
            # Registry/discovery tables are created by Base.metadata before
            # this hook runs. Version 2 records that the additive multi-asset
            # schema is present without rewriting legacy rows.
            conn.execute(text(f"PRAGMA user_version = {SCHEMA_VERSION}"))

"""Small, additive SQLite migrations for installations without Alembic."""

from __future__ import annotations

from sqlalchemy import Engine, inspect, text

SCHEMA_VERSION = 1


def migrate(engine: Engine) -> None:
    """Apply idempotent, additive migrations; never rewrite or delete rows."""
    with engine.begin() as conn:
        current = int(conn.execute(text("PRAGMA user_version")).scalar_one())
        if current < 1:
            columns = {c["name"] for c in inspect(engine).get_columns("backtest_runs")}
            if "evidence_class" not in columns:
                conn.execute(text(
                    "ALTER TABLE backtest_runs ADD COLUMN evidence_class VARCHAR(16) "
                    "NOT NULL DEFAULT 'diagnostic'"
                ))
            conn.execute(text(f"PRAGMA user_version = {SCHEMA_VERSION}"))


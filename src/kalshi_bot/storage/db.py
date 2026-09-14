"""Engine and session factory for the schema of record.

SQLite now, Postgres-portable later: nothing here or in models.py assumes
SQLite beyond the default URL scheme.
"""

from __future__ import annotations

import sqlite3
from pathlib import Path

from loguru import logger
from sqlalchemy import Engine, create_engine, event, inspect, text
from sqlalchemy.orm import Session, sessionmaker
from sqlalchemy.types import NullType

from kalshi_bot.config.settings import Settings, get_settings
from kalshi_bot.storage.migrations import migrate
from kalshi_bot.storage.models import Base


def _set_sqlite_pragmas(dbapi_connection: object, _connection_record: object) -> None:
    """WAL lets readers (the dashboard, ad-hoc queries) proceed while a
    writer (capture, a backtest/validation run) holds the connection open --
    the default `DELETE` journal mode takes an exclusive lock for the
    duration of a write transaction, which previously left the dashboard and
    read-only queries raising "database is locked" for as long as a
    multi-minute validation run was active. `synchronous=NORMAL` is WAL's
    documented pairing: still durable against an application crash, only a
    rare OS-crash-during-write window is no longer fsync-guaranteed, which is
    an acceptable trade for a local research/paper-trading database.

    Only applies to sqlite3 DBAPI connections; harmless no-op check keeps
    this safe if the engine is ever pointed at Postgres.
    """
    if not isinstance(dbapi_connection, sqlite3.Connection):
        return
    cursor = dbapi_connection.cursor()
    cursor.execute("PRAGMA journal_mode=WAL")
    cursor.execute("PRAGMA synchronous=NORMAL")
    cursor.close()


def get_engine(settings: Settings | None = None, *, echo: bool = False) -> Engine:
    settings = settings or get_settings()
    db_path = Path(settings.db_path)
    db_path.parent.mkdir(parents=True, exist_ok=True)
    engine = create_engine(f"sqlite:///{db_path.as_posix()}", echo=echo)
    event.listen(engine, "connect", _set_sqlite_pragmas)
    return engine


def get_session_factory(engine: Engine) -> sessionmaker[Session]:
    return sessionmaker(bind=engine, expire_on_commit=False)


def create_all_tables(engine: Engine) -> None:
    """Create any missing tables, then add any missing columns. Idempotent;
    safe to call at startup.

    `Base.metadata.create_all` only creates absent *tables* — it never
    ALTERs an existing one, so a model that gained a column since the DB was
    created would silently keep the stale schema (a known hazard on this
    project). `_add_missing_columns` closes that gap for the additive,
    nullable columns this codebase uses: it never drops, renames, retypes,
    or backfills anything, so historical rows are untouched
    (kxbtc15m-validation-rebuild §1.2 / §3.3). A destructive change still
    needs a real migration.
    """
    Base.metadata.create_all(engine)
    migrate(engine)
    _add_missing_columns(engine)


def _add_missing_columns(engine: Engine) -> None:
    inspector = inspect(engine)
    existing_tables = set(inspector.get_table_names())
    with engine.begin() as conn:
        for table in Base.metadata.sorted_tables:
            if table.name not in existing_tables:
                continue  # just created with the full, current schema
            have = {col["name"] for col in inspector.get_columns(table.name)}
            for column in table.columns:
                if column.name in have:
                    continue
                if not column.nullable and column.default is None:
                    # Can't add a NOT NULL column with no default to a table
                    # that already has rows — that's a real migration, not
                    # this helper's job. Skip loudly rather than crash startup.
                    logger.warning(
                        "schema drift: {}.{} is missing and NOT NULL with no "
                        "default; needs a manual migration",
                        table.name,
                        column.name,
                    )
                    continue
                ddl_type = column.type.compile(engine.dialect)
                if isinstance(column.type, NullType):
                    continue
                conn.execute(
                    text(f'ALTER TABLE "{table.name}" ADD COLUMN "{column.name}" {ddl_type}')
                )
                logger.info("schema: added {}.{} ({})", table.name, column.name, ddl_type)

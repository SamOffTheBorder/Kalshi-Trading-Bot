"""Engine and session factory for the schema of record.

SQLite now, Postgres-portable later: nothing here or in models.py assumes
SQLite beyond the default URL scheme.
"""

from __future__ import annotations

from pathlib import Path

from sqlalchemy import Engine, create_engine
from sqlalchemy.orm import Session, sessionmaker

from kalshi_bot.config.settings import Settings, get_settings
from kalshi_bot.storage.models import Base


def get_engine(settings: Settings | None = None, *, echo: bool = False) -> Engine:
    settings = settings or get_settings()
    db_path = Path(settings.db_path)
    db_path.parent.mkdir(parents=True, exist_ok=True)
    return create_engine(f"sqlite:///{db_path.as_posix()}", echo=echo)


def get_session_factory(engine: Engine) -> sessionmaker[Session]:
    return sessionmaker(bind=engine, expire_on_commit=False)


def create_all_tables(engine: Engine) -> None:
    """Create any missing tables. Idempotent; safe to call at startup."""
    Base.metadata.create_all(engine)

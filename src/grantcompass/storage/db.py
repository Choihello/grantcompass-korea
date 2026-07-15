"""Async SQLAlchemy engine and session factories for SQLite."""

from typing import Final

from sqlalchemy import event
from sqlalchemy.engine.interfaces import DBAPIConnection
from sqlalchemy.ext.asyncio import (
    AsyncEngine,
    AsyncSession,
    async_sessionmaker,
    create_async_engine,
)
from sqlalchemy.pool import ConnectionPoolEntry

DEFAULT_DATABASE_URL: Final = "sqlite+aiosqlite:///./grantcompass.db"


def create_engine(database_url: str = DEFAULT_DATABASE_URL) -> AsyncEngine:
    """Create a production-equivalent async SQLite engine."""
    engine = create_async_engine(database_url, pool_pre_ping=True)
    enable_sqlite_foreign_keys(engine)
    return engine


def enable_sqlite_foreign_keys(engine: AsyncEngine) -> None:
    """Enable foreign-key checks on every connection owned by an async engine."""
    event.listen(engine.sync_engine, "connect", _enable_sqlite_foreign_keys)


def _enable_sqlite_foreign_keys(
    connection: DBAPIConnection,
    _record: ConnectionPoolEntry,
) -> None:
    cursor = connection.cursor()
    cursor.execute("PRAGMA foreign_keys=ON")
    cursor.close()


def create_session_factory(engine: AsyncEngine) -> async_sessionmaker[AsyncSession]:
    """Create async sessions that retain loaded values after commit."""
    return async_sessionmaker(engine, expire_on_commit=False)

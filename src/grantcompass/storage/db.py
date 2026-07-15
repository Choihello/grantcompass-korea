"""Async SQLAlchemy engine and session factories for SQLite."""

from typing import Final

from sqlalchemy.ext.asyncio import (
    AsyncEngine,
    AsyncSession,
    async_sessionmaker,
    create_async_engine,
)

DEFAULT_DATABASE_URL: Final = "sqlite+aiosqlite:///./grantcompass.db"


def create_engine(database_url: str = DEFAULT_DATABASE_URL) -> AsyncEngine:
    """Create a production-equivalent async SQLite engine."""
    return create_async_engine(database_url, pool_pre_ping=True)


def create_session_factory(engine: AsyncEngine) -> async_sessionmaker[AsyncSession]:
    """Create async sessions that retain loaded values after commit."""
    return async_sessionmaker(engine, expire_on_commit=False)

"""CLI-owned database engine lifecycle."""

from sqlalchemy.exc import ArgumentError
from sqlalchemy.ext.asyncio import AsyncEngine

from grantcompass.cli.errors import CliError, CliErrorCode
from grantcompass.storage.db import create_engine
from grantcompass.storage.tables import Base


def create_cli_engine(database_url: str) -> AsyncEngine:
    """Create an engine or translate an invalid explicit URL to a finite code."""
    try:
        return create_engine(database_url)
    except ArgumentError:
        raise CliError(CliErrorCode.INVALID_DATABASE_URL, 4) from None


async def initialize_database(database_url: str) -> None:
    """Create the complete current schema idempotently and dispose its engine."""
    engine = create_cli_engine(database_url)
    try:
        async with engine.begin() as connection:
            await connection.run_sync(Base.metadata.create_all)
    finally:
        await engine.dispose()

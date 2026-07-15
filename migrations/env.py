"""Async Alembic environment for the GrantCompass SQLite database."""

from logging.config import fileConfig

import anyio
from alembic import context
from sqlalchemy import Connection, pool
from sqlalchemy.ext.asyncio import async_engine_from_config

from grantcompass.storage.db import enable_sqlite_foreign_keys
from grantcompass.storage.tables import Base

config = context.config
if config.config_file_name is not None:
    fileConfig(config.config_file_name)
target_metadata = Base.metadata


def run_migrations_offline() -> None:
    """Run migrations without creating a database connection."""
    context.configure(
        url=config.get_main_option("sqlalchemy.url"),
        target_metadata=target_metadata,
        literal_binds=True,
        dialect_opts={"paramstyle": "named"},
        compare_type=True,
    )
    with context.begin_transaction():
        context.run_migrations()


def apply_migrations(connection: Connection) -> None:
    """Apply configured migrations through one synchronous Alembic connection."""
    context.configure(connection=connection, target_metadata=target_metadata, compare_type=True)
    with context.begin_transaction():
        context.run_migrations()


async def run_async_migrations() -> None:
    """Create and dispose the async engine around one migration run."""
    section = config.get_section(config.config_ini_section, {})
    engine = async_engine_from_config(section, prefix="sqlalchemy.", poolclass=pool.NullPool)
    enable_sqlite_foreign_keys(engine)
    async with engine.connect() as connection:
        await connection.run_sync(apply_migrations)
    await engine.dispose()


def run_migrations_online() -> None:
    """Run migrations through the AnyIO-managed async boundary."""
    anyio.run(run_async_migrations)


if context.is_offline_mode():
    run_migrations_offline()
else:
    run_migrations_online()

"""Stable access to migration resources shipped in installed artifacts."""

from pathlib import Path


def packaged_alembic_config() -> Path:
    """Return the Alembic configuration beside the installed package."""
    return Path(__file__).with_name("alembic.ini")


__all__ = ["packaged_alembic_config"]

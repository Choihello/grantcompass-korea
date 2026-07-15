"""Shared SQLAlchemy declarative registry."""

from sqlalchemy.orm import DeclarativeBase


class Base(DeclarativeBase):
    """Declarative base for mutable unit-of-work rows."""

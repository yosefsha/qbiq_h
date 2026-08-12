"""Declarative base shared by every SQLAlchemy ORM model.

Alembic's `env.py` imports `Base.metadata` from here as the single source of
truth for autogeneration and for building the schema on an empty database.
"""

from __future__ import annotations

from sqlalchemy.orm import DeclarativeBase


class Base(DeclarativeBase):
    """Base class for all SQLAlchemy ORM models."""

"""Declarative base factory.

Each service creates its own Base (and therefore its own MetaData), so a model
can only ever reference tables in the same service database. The naming
convention keeps constraint names stable across Alembic autogenerate runs.
"""

from __future__ import annotations

from sqlalchemy import MetaData
from sqlalchemy.orm import DeclarativeBase

NAMING_CONVENTION = {
    "ix": "ix_%(table_name)s_%(column_0_N_name)s",
    "uq": "uq_%(table_name)s_%(column_0_N_name)s",
    "ck": "ck_%(table_name)s_%(constraint_name)s",
    "fk": "fk_%(table_name)s_%(column_0_name)s_%(referred_table_name)s",
    "pk": "pk_%(table_name)s",
}


def make_base(name: str = "Base") -> type[DeclarativeBase]:
    """Return a fresh declarative base with its own MetaData."""
    metadata = MetaData(naming_convention=NAMING_CONVENTION)
    return type(name, (DeclarativeBase,), {"metadata": metadata, "__abstract__": True})

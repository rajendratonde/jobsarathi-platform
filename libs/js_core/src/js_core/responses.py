"""Common response models: pagination and sorting (Implementation Blueprint §22)."""

from __future__ import annotations

from typing import Annotated, Generic, TypeVar

from fastapi import Query
from pydantic import BaseModel

from js_core.errors import FieldError, ValidationFailed

T = TypeVar("T")

DEFAULT_PAGE_SIZE = 20
MAX_PAGE_SIZE = 100


class PageParams(BaseModel):
    page: int = 1
    size: int = DEFAULT_PAGE_SIZE

    @property
    def offset(self) -> int:
        return (self.page - 1) * self.size


def page_params(page: Annotated[int, Query(ge=1)] = 1,
                size: Annotated[int, Query(ge=1, le=MAX_PAGE_SIZE)] = DEFAULT_PAGE_SIZE) -> PageParams:
    """FastAPI dependency: ?page=1&size=20 (max 100)."""
    return PageParams(page=page, size=size)


class Page(BaseModel, Generic[T]):
    items: list[T]
    page: int
    size: int
    total: int


def parse_sort(sort: str | None, allowed: set[str], default: str) -> list[tuple[str, bool]]:
    """Parse ``sort=-applied_at,title`` against an allow-list.

    Returns ``[(field, descending), ...]``. Unknown fields are a 422, never
    passed through to SQL.
    """
    raw = sort or default
    result: list[tuple[str, bool]] = []
    for part in [p.strip() for p in raw.split(",") if p.strip()]:
        desc = part.startswith("-")
        name = part[1:] if desc else part
        if name not in allowed:
            raise ValidationFailed(errors=[FieldError(field="sort", code="NOT_SORTABLE",
                                                      message=f"Cannot sort by '{name}'.")])
        result.append((name, desc))
    return result

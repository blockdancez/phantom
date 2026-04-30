"""Tests for DB URL coercion: libpq URL → asyncpg URL."""

from __future__ import annotations

from src.db import _coerce_async_url


def test_passthrough_for_asyncpg_url():
    url = "postgresql+asyncpg://u:p@h:5432/db"
    assert _coerce_async_url(url) == url


def test_coerces_bare_postgresql_to_asyncpg():
    assert (
        _coerce_async_url("postgresql://u:p@h:5432/db")
        == "postgresql+asyncpg://u:p@h:5432/db"
    )


def test_leaves_non_postgres_urls_alone():
    url = "sqlite+aiosqlite:///:memory:"
    assert _coerce_async_url(url) == url


def test_coerce_preserves_query_params():
    src = "postgresql://u:p@h:5432/db?sslmode=require"
    assert (
        _coerce_async_url(src)
        == "postgresql+asyncpg://u:p@h:5432/db?sslmode=require"
    )

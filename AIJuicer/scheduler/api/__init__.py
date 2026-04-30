"""API 共享依赖：数据库单例、session dependency。"""

from __future__ import annotations

from collections.abc import AsyncIterator

from sqlalchemy.ext.asyncio import AsyncSession

from scheduler.config import Settings, get_settings
from scheduler.storage.db import Database

_db_singleton: Database | None = None


def set_database(db: Database) -> None:
    global _db_singleton
    _db_singleton = db


def get_database() -> Database:
    if _db_singleton is None:
        raise RuntimeError("Database not initialized; call set_database in startup")
    return _db_singleton


async def get_session() -> AsyncIterator[AsyncSession]:
    db = get_database()
    async with db.session() as session:
        yield session


def settings_dep() -> Settings:
    return get_settings()

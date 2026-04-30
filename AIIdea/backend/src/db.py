from functools import lru_cache

from sqlalchemy.ext.asyncio import create_async_engine, async_sessionmaker, AsyncSession
from sqlalchemy.orm import DeclarativeBase


class Base(DeclarativeBase):
    pass


def _coerce_async_url(url: str) -> str:
    # Settings.database_url may arrive as "postgresql://..." (env-default) but
    # create_async_engine requires an async driver. Transparently swap the
    # scheme so ops can paste a standard libpq URL without us loading psycopg2.
    if url.startswith("postgresql+"):
        return url
    if url.startswith("postgresql://"):
        return "postgresql+asyncpg://" + url[len("postgresql://") :]
    return url


@lru_cache
def _get_engine():
    from src.config import Settings
    settings = Settings()
    url = _coerce_async_url(settings.database_url)
    return create_async_engine(url, echo=False)


@lru_cache
def _get_session_factory():
    return async_sessionmaker(_get_engine(), class_=AsyncSession, expire_on_commit=False)


def get_async_session_factory():
    return _get_session_factory()


async def get_session():
    factory = _get_session_factory()
    async with factory() as session:
        yield session

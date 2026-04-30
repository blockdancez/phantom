from sqlalchemy.ext.asyncio import create_async_engine, async_sessionmaker, AsyncSession

from app.config import get_settings


def create_engine():
    settings = get_settings()
    return create_async_engine(settings.database_url, echo=False)


def create_session_factory(engine) -> async_sessionmaker[AsyncSession]:
    return async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)


engine = None
SessionLocal = None


async def init_db():
    global engine, SessionLocal
    engine = create_engine()
    SessionLocal = create_session_factory(engine)


async def get_db():
    async with SessionLocal() as session:
        yield session


async def close_db():
    global engine
    if engine:
        await engine.dispose()

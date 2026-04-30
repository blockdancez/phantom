"""Pytest fixtures: testcontainers Postgres + 测试用 Database。

测试隔离：`db_session` 开启外层 transaction + SAVEPOINT，被测代码即使 commit
也只是提交到 SAVEPOINT，teardown 时 rollback 外层 transaction 清空所有写入。

若环境变量 TEST_DATABASE_URL 存在，则跳过 testcontainer，直接使用该 URL 连接。
这允许在 CI 或本地开发时复用已有的 postgres 实例。
"""

from __future__ import annotations

import os
from collections.abc import AsyncIterator, Iterator

import pytest
import pytest_asyncio
from sqlalchemy import event
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker
from testcontainers.postgres import PostgresContainer

from scheduler.config import Settings
from scheduler.storage.db import Database
from scheduler.storage.models import Base
from scheduler.storage.redis_queue import InMemoryTaskQueue

_TEST_DATABASE_URL: str | None = os.environ.get("TEST_DATABASE_URL")


@pytest.fixture(scope="session")
def postgres_container() -> Iterator[PostgresContainer | None]:
    if _TEST_DATABASE_URL:
        # 跳过 testcontainer，直接 yield None
        yield None
        return
    container = PostgresContainer("postgres:16-alpine")
    container.start()
    try:
        yield container
    finally:
        container.stop()


@pytest.fixture(scope="session")
def test_settings(postgres_container: PostgresContainer | None, tmp_path_factory) -> Settings:
    if _TEST_DATABASE_URL:
        async_url = _TEST_DATABASE_URL
    else:
        assert postgres_container is not None
        raw_url = postgres_container.get_connection_url()
        async_url = raw_url.replace("postgresql+psycopg2://", "postgresql+asyncpg://").replace(
            "postgresql://", "postgresql+asyncpg://"
        )
    artifact_root = tmp_path_factory.mktemp("artifacts")
    return Settings(
        database_url=async_url,
        redis_url="redis://localhost:6379/0",
        artifact_root=artifact_root,
    )


@pytest_asyncio.fixture(scope="session")
async def database(test_settings: Settings) -> AsyncIterator[Database]:
    db = Database(test_settings, task_queue=InMemoryTaskQueue())
    async with db.engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    yield db
    await db.dispose()


@pytest.fixture
def task_queue(database: Database) -> InMemoryTaskQueue:
    """每个测试前清空内存队列，返回同一实例方便断言。"""
    tq = database.task_queue
    assert isinstance(tq, InMemoryTaskQueue)
    tq.enqueued.clear()
    return tq


@pytest_asyncio.fixture
async def db_session(database: Database) -> AsyncIterator[AsyncSession]:
    """每测试隔离：外层 transaction + SAVEPOINT，teardown 全部回滚。"""
    async with database.engine.connect() as connection:
        outer_trans = await connection.begin()

        factory = async_sessionmaker(bind=connection, expire_on_commit=False, class_=AsyncSession)
        session = factory()

        # 启动 SAVEPOINT；被测代码 commit 只提交到 SAVEPOINT
        await session.begin_nested()

        # 被测代码 commit 后，自动重新开一个 SAVEPOINT，保持嵌套状态
        @event.listens_for(session.sync_session, "after_transaction_end")
        def _restart_savepoint(sess, trans):  # type: ignore[no-untyped-def]
            if trans.nested and not trans._parent.nested:
                sess.begin_nested()

        try:
            yield session
        finally:
            await session.close()
            await outer_trans.rollback()

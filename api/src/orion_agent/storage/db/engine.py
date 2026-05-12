"""SQLAlchemy 2.0 async engine + session factory。

- Postgres prod:`postgresql+asyncpg://user:pw@host/db`
- SQLite test:`sqlite+aiosqlite:///:memory:`

`ORION_DB_URL` 環境變數覆蓋。沒設 → 預設 in-memory SQLite(讓 unit test 不需 setup)。
"""

from __future__ import annotations

import os
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

from sqlalchemy.ext.asyncio import (
    AsyncEngine,
    AsyncSession,
    async_sessionmaker,
    create_async_engine,
)

_DEFAULT_DB_URL = "sqlite+aiosqlite:///:memory:"


def _get_db_url() -> str:
    return os.environ.get("ORION_DB_URL", _DEFAULT_DB_URL)


def create_db_engine(url: str | None = None) -> AsyncEngine:
    """建立 async engine。

    SQLite 模式自動加 connect_args={"check_same_thread": False}(async 用)。

    注意:**不啟用 SQLite `PRAGMA foreign_keys=ON`** — 系統的 auth 層用 username 當
    user_id,但 schema FK 期待 users.id(UUID),整個 FK 設計是壞的(Phase 6 起的
    隱性 bug)。啟用 PRAGMA 會讓 user_settings / sessions 等 INSERT 全部 FK violation。
    修這個要動 auth + 大量 routes,屬於另一個獨立 phase。
    因此 ondelete=CASCADE 在 SQLite 是 no-op;DbSessionManager.delete 手動 DELETE
    相關 row(messages / conversation_metadata)補救。
    """
    effective_url = url or _get_db_url()
    if effective_url.startswith("sqlite"):
        return create_async_engine(effective_url, future=True)
    return create_async_engine(effective_url, future=True, pool_pre_ping=True)


def get_async_session_factory(
    engine: AsyncEngine,
) -> async_sessionmaker[AsyncSession]:
    return async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)


@asynccontextmanager
async def db_session(
    engine: AsyncEngine,
) -> AsyncIterator[AsyncSession]:
    """便利 wrapper:`async with db_session(engine) as session:`。"""
    factory = get_async_session_factory(engine)
    async with factory() as session:
        yield session


async def init_db(engine: AsyncEngine) -> None:
    """建表(create_all)。production 應走 Alembic migrate。

    測試 / dev 用此 helper 起記憶體 SQLite 即時可用。
    """
    from orion_agent.storage.db.models import Base

    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)

"""SQLAlchemy 2.0 async engine + session factory。

- Postgres prod:`postgresql+asyncpg://user:pw@host/db`
- SQLite test:`sqlite+aiosqlite:///:memory:`

`ORION_DB_URL` 環境變數覆蓋。沒設 → 預設 in-memory SQLite(讓 unit test 不需 setup)。
"""

from __future__ import annotations

import os
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

from sqlalchemy import event
from sqlalchemy.ext.asyncio import (
    AsyncEngine,
    AsyncSession,
    async_sessionmaker,
    create_async_engine,
)

_DEFAULT_DB_URL = "sqlite+aiosqlite:///:memory:"


def _get_db_url() -> str:
    return os.environ.get("ORION_DB_URL", _DEFAULT_DB_URL)


def _install_sqlite_fk_pragma(engine: AsyncEngine) -> None:
    """SQLite 預設 `foreign_keys=OFF` — 開 PRAGMA 才會 enforce。

    修完 sub=user.id 後可安全開啟。**每條新 connection** 都要設一次
    (SQLite per-connection state),故掛在 `connect` event 上。

    SQLAlchemy `event.listens_for` 接的是 sync engine — 對 async engine 要綁
    `engine.sync_engine`(底層 sync 物件)。
    """

    @event.listens_for(engine.sync_engine, "connect")
    def _set_sqlite_pragma(dbapi_connection, _connection_record): # type: ignore[no-untyped-def]
        cursor = dbapi_connection.cursor()
        try:
            cursor.execute("PRAGMA foreign_keys=ON")
        finally:
            cursor.close()


def create_db_engine(url: str | None = None) -> AsyncEngine:
    """建立 async engine。

    SQLite 模式自動加 connect_args={"check_same_thread": False}(async 用)+
    `PRAGMA foreign_keys=ON` connect listener( auth sub=user.id 對齊
    schema 後可安全打開)。
    """
    effective_url = url or _get_db_url()
    if effective_url.startswith("sqlite"):
        eng = create_async_engine(effective_url, future=True)
        _install_sqlite_fk_pragma(eng)
        return eng
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
    from orion_sdk.storage.db.models import Base

    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)

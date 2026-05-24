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


def _add_missing_columns(conn) -> None:  # type: ignore[no-untyped-def]
    """對既有表補上 model 新增的欄位(輕量 migration)。

    `create_all` 只建缺的「表」,不會 ALTER 既有表加「欄位」。各 phase 漸進地往
    `conversation_metadata` 等表加欄位(starred / budget / plan / project_id …),
    既有 DB(persistent SQLite / Postgres)需要這層補欄位才不會 OperationalError。

    **慣例:新增欄位一律 nullable**(這裡 ADD COLUMN 不帶 NOT NULL / DEFAULT),
    對既有 row 永遠安全;app 讀取時自行把 NULL 當預設值(如 `bool(row.starred)`)。
    production 仍建議走 Alembic;此 helper 是 dev / 漸進 schema 的安全網。
    """
    from sqlalchemy import inspect as sa_inspect

    from orion_sdk.storage.db.models import Base

    insp = sa_inspect(conn)
    existing_tables = set(insp.get_table_names())
    for table in Base.metadata.sorted_tables:
        if table.name not in existing_tables:
            continue  # create_all 剛建的新表已含所有欄位
        have = {c["name"] for c in insp.get_columns(table.name)}
        for col in table.columns:
            if col.name in have:
                continue
            coltype = col.type.compile(dialect=conn.dialect)
            conn.exec_driver_sql(
                f'ALTER TABLE "{table.name}" ADD COLUMN "{col.name}" {coltype}'
            )


async def init_db(engine: AsyncEngine) -> None:
    """建表(create_all)+ 補既有表缺的欄位。production 應走 Alembic migrate。

    測試 / dev 用此 helper 起記憶體 SQLite 即時可用。
    """
    from orion_sdk.storage.db.models import Base

    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
        await conn.run_sync(_add_missing_columns)

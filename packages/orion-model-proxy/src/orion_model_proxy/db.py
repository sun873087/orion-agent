"""DB engine + session factory。

Backend 由 `ORION_PROXY_DB_URL` env 切:
    dev / test:`sqlite+aiosqlite:///./proxy.db`(預設)
    prod:`postgresql+asyncpg://user:pass@host/db`

Schema 一份(`models.py`),SQLAlchemy async 兩邊跑同份 ORM。
"""

from __future__ import annotations

import os
from pathlib import Path
from typing import AsyncIterator

from sqlalchemy.ext.asyncio import (
    AsyncEngine,
    AsyncSession,
    async_sessionmaker,
    create_async_engine,
)

_engine: AsyncEngine | None = None
_session_factory: async_sessionmaker[AsyncSession] | None = None


def _default_sqlite_url() -> str:
    """`packages/orion-model-proxy/data/proxy.db` — package-local,不污染 user dir。"""
    here = Path(__file__).resolve().parents[2]
    data_dir = here / "data"
    data_dir.mkdir(parents=True, exist_ok=True)
    return f"sqlite+aiosqlite:///{data_dir / 'proxy.db'}"


def get_db_url() -> str:
    return os.environ.get("ORION_PROXY_DB_URL") or _default_sqlite_url()


def get_engine() -> AsyncEngine:
    global _engine, _session_factory
    if _engine is None:
        _engine = create_async_engine(
            get_db_url(),
            echo=False,
            future=True,
            # SQLite-specific:讓 multi-conn 共享 in-memory tmp db(test 用)
            connect_args={"check_same_thread": False} if "sqlite" in get_db_url() else {},
        )
        _session_factory = async_sessionmaker(
            _engine, expire_on_commit=False, class_=AsyncSession
        )
    return _engine


def get_session_factory() -> async_sessionmaker[AsyncSession]:
    if _session_factory is None:
        get_engine()
    assert _session_factory is not None
    return _session_factory


async def session() -> AsyncIterator[AsyncSession]:
    """FastAPI Depends use:
    async def handler(db: AsyncSession = Depends(session)): ...
    """
    factory = get_session_factory()
    async with factory() as s:
        yield s


async def init_db() -> None:
    """Idempotent create_all + 自動加缺少的 column(輕量 migration)。

    `create_all` 只建新表,不會在既有表上加新 column — Phase 33 加了
    `users.rate_limit_rpm` / `users.organization_id` 之後,舊 DB 啟動會撞
    `no such column`。這裡用 SQLAlchemy Inspector 比對 expected vs actual,
    缺的 column ALTER TABLE ADD。比 alembic 輕,給 single-instance dev /
    self-host 用足夠。
    """
    from orion_model_proxy.models import Base

    engine = get_engine()
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
        await conn.run_sync(_add_missing_columns)


def _add_missing_columns(conn) -> None:
    """Sync function 給 run_sync 用。Inspector 比 metadata 表 vs DB 實際 column,
    缺的 ADD COLUMN。Cross-backend(SQLite + Postgres 都支援 ALTER ADD COLUMN)。
    """
    import logging
    from sqlalchemy import inspect
    from sqlalchemy.exc import OperationalError, ProgrammingError

    from orion_model_proxy.models import Base

    _log = logging.getLogger(__name__)
    inspector = inspect(conn)
    for table_name, table in Base.metadata.tables.items():
        if not inspector.has_table(table_name):
            continue  # create_all 還沒建到(不該發生但保險)
        existing = {c["name"] for c in inspector.get_columns(table_name)}
        for col in table.columns:
            if col.name in existing:
                continue
            col_type = col.type.compile(dialect=conn.dialect)
            nullable = "" if col.nullable else " NOT NULL"
            default = ""
            if col.default is not None and hasattr(col.default, "arg"):
                v = col.default.arg
                if isinstance(v, (int, float)):
                    default = f" DEFAULT {v}"
                elif isinstance(v, str):
                    default = f" DEFAULT '{v}'"
            sql = f'ALTER TABLE "{table_name}" ADD COLUMN {col.name} {col_type}{nullable}{default}'
            try:
                conn.exec_driver_sql(sql)
                _log.info("auto-migrated: added %s.%s", table_name, col.name)
            except (OperationalError, ProgrammingError) as e:
                # column 已存在 / 不支援 default — swallow,下次啟動 inspector
                # 就會跳過。
                _log.debug("ALTER TABLE skipped for %s.%s: %s", table_name, col.name, e)


async def reset_for_tests() -> None:
    """測試用:drop + create all,reset cache。"""
    global _engine, _session_factory
    if _engine is not None:
        await _engine.dispose()
    _engine = None
    _session_factory = None
    from orion_model_proxy.models import Base

    engine = get_engine()
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.drop_all)
        await conn.run_sync(Base.metadata.create_all)


__all__ = [
    "get_db_url",
    "get_engine",
    "get_session_factory",
    "init_db",
    "reset_for_tests",
    "session",
]

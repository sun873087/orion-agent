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
    """Idempotent create_all — startup 跑一次。"""
    from orion_model_proxy.models import Base

    engine = get_engine()
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)


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

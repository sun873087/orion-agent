"""Shared fixtures — 給每個 test 獨立 SQLite tmp db。"""

from __future__ import annotations

import os
import tempfile
from pathlib import Path

import pytest
import pytest_asyncio


@pytest_asyncio.fixture
async def proxy_db():
    """獨立 tmp SQLite。yield 完 dispose engine + best-effort cleanup tmp dir。"""
    import asyncio
    import shutil

    d = tempfile.mkdtemp(prefix="proxy-test-")
    db_path = Path(d) / "proxy.db"
    old_url = os.environ.get("ORION_PROXY_DB_URL")
    old_admin = os.environ.get("ORION_MODEL_PROXY_ADMIN_KEY")
    os.environ["ORION_PROXY_DB_URL"] = f"sqlite+aiosqlite:///{db_path}"
    os.environ["ORION_MODEL_PROXY_ADMIN_KEY"] = "admin-test-token"

    from orion_model_proxy import auth as proxy_auth_mod
    from orion_model_proxy import db as proxy_db_mod
    from orion_model_proxy import usage_logger as proxy_usage_mod

    proxy_db_mod._engine = None
    proxy_db_mod._session_factory = None
    proxy_auth_mod._cache.clear()
    proxy_usage_mod._running_cost.clear()

    from orion_model_proxy.db import init_db
    await init_db()

    try:
        yield db_path
    finally:
        # 等背景 task 結束(fire-and-forget usage_log writers)
        pending = [t for t in asyncio.all_tasks() if not t.done() and t is not asyncio.current_task()]
        if pending:
            try:
                await asyncio.wait_for(asyncio.gather(*pending, return_exceptions=True), timeout=2.0)
            except asyncio.TimeoutError:
                pass

        if proxy_db_mod._engine is not None:
            await proxy_db_mod._engine.dispose()
        proxy_db_mod._engine = None
        proxy_db_mod._session_factory = None
        proxy_auth_mod._cache.clear()
        proxy_usage_mod._running_cost.clear()

        for var, old in [
            ("ORION_PROXY_DB_URL", old_url),
            ("ORION_MODEL_PROXY_ADMIN_KEY", old_admin),
        ]:
            if old is None:
                os.environ.pop(var, None)
            else:
                os.environ[var] = old

        # Best-effort tmpdir delete — SQLite WAL/SHM 偶爾還沒釋放
        shutil.rmtree(d, ignore_errors=True)


@pytest.fixture
def admin_token() -> str:
    return "admin-test-token"

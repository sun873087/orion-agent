"""schema auto-migration:既有 DB 缺欄會自動 ALTER ADD。"""

from __future__ import annotations

import os
import tempfile
from pathlib import Path

import pytest


@pytest.mark.asyncio
async def test_init_db_adds_missing_column_to_existing_table() -> None:
    """模擬 DB(沒 rate_limit_rpm)→ init_db 自動加 column。"""
    with tempfile.TemporaryDirectory(prefix="proxy-mig-") as d:
        db_path = Path(d) / "old-schema.db"

        # 1. 用 SQLite 直接建一個「舊 schema」的 users 表(缺 rate_limit_rpm)
        import sqlite3
        conn = sqlite3.connect(str(db_path))
        conn.execute("""
            CREATE TABLE users (
                id TEXT PRIMARY KEY,
                email TEXT UNIQUE NOT NULL,
                display_name TEXT,
                budget_usd REAL,
                created_at INTEGER NOT NULL
            )
        """)
        conn.execute("INSERT INTO users VALUES ('u1', 'a@x.com', 'Alice', NULL, 1000000)")
        conn.commit()
        conn.close()

        # 2. 切到這 DB,跑 init_db
        old_url = os.environ.get("ORION_PROXY_DB_URL")
        os.environ["ORION_PROXY_DB_URL"] = f"sqlite+aiosqlite:///{db_path}"
        try:
            from orion_model_proxy import db as proxy_db_mod
            proxy_db_mod._engine = None
            proxy_db_mod._session_factory = None

            from orion_model_proxy.db import init_db
            await init_db()

            # 3. 驗證 column 真的加了
            inspect_conn = sqlite3.connect(str(db_path))
            cols = {row[1] for row in inspect_conn.execute("PRAGMA table_info(users)").fetchall()}
            inspect_conn.close()
            assert "rate_limit_rpm" in cols
            assert "organization_id" in cols

            # 4. 既有 data 仍在
            check_conn = sqlite3.connect(str(db_path))
            rows = check_conn.execute("SELECT email FROM users").fetchall()
            check_conn.close()
            assert ("a@x.com",) in rows

            # 5. 既有 table(audit_log / webhooks / ...)也應該被 create_all 建
            check_conn = sqlite3.connect(str(db_path))
            tables = {r[0] for r in check_conn.execute(
                "SELECT name FROM sqlite_master WHERE type='table'"
            ).fetchall()}
            check_conn.close()
            assert "audit_log" in tables
            assert "webhooks" in tables
            assert "routing_aliases" in tables

            # cleanup engine
            if proxy_db_mod._engine is not None:
                await proxy_db_mod._engine.dispose()
            proxy_db_mod._engine = None
            proxy_db_mod._session_factory = None
        finally:
            if old_url is None:
                os.environ.pop("ORION_PROXY_DB_URL", None)
            else:
                os.environ["ORION_PROXY_DB_URL"] = old_url


@pytest.mark.asyncio
async def test_init_db_idempotent_on_fresh_db() -> None:
    """新 DB 跑兩次 init_db 不該 raise。"""
    with tempfile.TemporaryDirectory(prefix="proxy-fresh-") as d:
        db_path = Path(d) / "fresh.db"
        old_url = os.environ.get("ORION_PROXY_DB_URL")
        os.environ["ORION_PROXY_DB_URL"] = f"sqlite+aiosqlite:///{db_path}"
        try:
            from orion_model_proxy import db as proxy_db_mod
            proxy_db_mod._engine = None
            proxy_db_mod._session_factory = None

            from orion_model_proxy.db import init_db
            await init_db()
            await init_db() # 第二次不該 ALTER TABLE 撞 duplicate column

            if proxy_db_mod._engine is not None:
                await proxy_db_mod._engine.dispose()
            proxy_db_mod._engine = None
            proxy_db_mod._session_factory = None
        finally:
            if old_url is None:
                os.environ.pop("ORION_PROXY_DB_URL", None)
            else:
                os.environ["ORION_PROXY_DB_URL"] = old_url

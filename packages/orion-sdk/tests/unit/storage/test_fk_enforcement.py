"""SQLite PRAGMA `foreign_keys=ON` 應 enforce user_id → users.id FK。

兩條測試:
- 寫入 user_id 是不存在的 UUID → IntegrityError(FK 真的有 enforce)
- 寫入 user_id 是存在的 users.id → 正常成功

若 FK 沒打開(前狀態),負向測試會錯誤 pass(write 成功)。
"""

from __future__ import annotations

import uuid

import pytest
from sqlalchemy import insert
from sqlalchemy.exc import IntegrityError

from orion_chat_api.auth_db import create_user
from orion_sdk.storage.db.engine import create_db_engine, db_session, init_db
from orion_sdk.storage.db.models import UserSetting


@pytest.mark.anyio
async def test_fk_violates_when_user_id_not_in_users() -> None:
    """寫 user_settings 但 user_id 是亂造 UUID → SQLite 應 raise IntegrityError。"""
    engine = create_db_engine("sqlite+aiosqlite:///:memory:")
    await init_db(engine)
    async with db_session(engine) as s:
        await create_user(s, username="alice", password="passw0rd")

    bogus_uuid = str(uuid.uuid4()) # 不存在於 users.id
    with pytest.raises(IntegrityError):
        async with db_session(engine) as s:
            await s.execute(
                insert(UserSetting).values(
                    user_id=bogus_uuid, key="lang", value="en",
                )
            )
            await s.commit()


@pytest.mark.anyio
async def test_fk_passes_with_real_user_id() -> None:
    """user_id 是真實 users.id → user_settings 寫入正常。"""
    engine = create_db_engine("sqlite+aiosqlite:///:memory:")
    await init_db(engine)
    async with db_session(engine) as s:
        user = await create_user(s, username="alice", password="passw0rd")
        uid = user.id

    async with db_session(engine) as s:
        await s.execute(
            insert(UserSetting).values(
                user_id=uid, key="lang", value="en",
            )
        )
        await s.commit() # 不該 raise

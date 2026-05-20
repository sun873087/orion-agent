"""DB-backed auth(bcrypt password)。

是 dev 模式任意 username 通過。加 User table + bcrypt。

兩種登入路徑(動態切換):
- DB 模式(`ORION_DB_URL` 設):查 users 表,verify password
- Dev fallback(無 DB / verify_password 失敗 + ORION_AUTH_MODE=dev):任意 username 過

Caller 仍用 issue_token / verify_token(的 JWT 不變)。
"""

from __future__ import annotations

import bcrypt
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from orion_sdk.storage.db.models import User

_BCRYPT_ROUNDS = 12


def hash_password(password: str) -> str:
    """bcrypt hash,UTF-8 → bytes。"""
    if not isinstance(password, str) or len(password) < 1:
        raise ValueError("password must be non-empty string")
    salt = bcrypt.gensalt(rounds=_BCRYPT_ROUNDS)
    return bcrypt.hashpw(password.encode("utf-8"), salt).decode("ascii")


def verify_password(password: str, password_hash: str) -> bool:
    """常數時間比對。"""
    if not password_hash:
        return False
    try:
        return bcrypt.checkpw(
            password.encode("utf-8"), password_hash.encode("ascii"),
        )
    except (ValueError, TypeError):
        return False


async def create_user(
    db: AsyncSession,
    *,
    username: str,
    password: str,
) -> User:
    """新增 user。username 衝突 → IntegrityError(caller 處理)。"""
    user = User(username=username, password_hash=hash_password(password))
    db.add(user)
    await db.commit()
    await db.refresh(user)
    return user


async def get_user_by_username(db: AsyncSession, username: str) -> User | None:
    stmt = select(User).where(User.username == username)
    result = await db.execute(stmt)
    return result.scalar_one_or_none()


async def authenticate(
    db: AsyncSession,
    *,
    username: str,
    password: str,
) -> User | None:
    """密碼正確回 User,錯誤 / 不存在回 None(常數時間比對)。"""
    user = await get_user_by_username(db, username)
    if user is None:
        # 仍跑一次 hash 比對避免 timing attack
        verify_password(password, "$2b$12$" + "x" * 53)
        return None
    if not verify_password(password, user.password_hash):
        return None
    return user

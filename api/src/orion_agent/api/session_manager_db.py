"""DbSessionManager — Phase 7 取代 Phase 6 in-memory。

對應 spec § 5(主文件)。

設計:
- **DB**:Session row 存 metadata(id / user_id / provider / model / n_turns / 時間戳)
- **In-memory cache**:Conversation 物件本身(state_messages 等大物件)— 跨 worker 共享靠 Phase 7c Redis,Phase 7 範圍內 single-instance OK
- list_for_user 查 DB(永久)
- get / create / delete 同步 DB + cache

跟 Phase 6 in-memory 同 protocol — caller(routes / chat ws)無需改。
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from uuid import UUID, uuid4

from sqlalchemy import delete, select
from sqlalchemy.ext.asyncio import AsyncEngine

from orion_agent.api.session_manager import SessionInfo
from orion_agent.core.conversation import Conversation
from orion_agent.storage.db.engine import db_session
from orion_agent.storage.db.models import Session as SessionRow

logger = logging.getLogger(__name__)


@dataclass
class DbSessionManager:
    """Postgres / SQLite-backed session manager。"""

    engine: AsyncEngine
    _cache: dict[tuple[str, UUID], Conversation] = field(default_factory=dict)

    async def create(
        self,
        *,
        user_id: str,
        session_id: UUID | None = None,
        conversation: Conversation,
    ) -> UUID:
        sid = session_id if session_id is not None else uuid4()
        async with db_session(self.engine) as db:
            row = SessionRow(
                id=str(sid),
                user_id=user_id,
                provider=conversation.provider.name,
                model=conversation.provider.model,
                n_turns=0,
                n_messages=0,
            )
            db.add(row)
            await db.commit()
        self._cache[(user_id, sid)] = conversation
        return sid

    async def get(self, user_id: str, session_id: UUID) -> Conversation | None:
        cached = self._cache.get((user_id, session_id))
        if cached is not None:
            return cached
        # cache miss — DB row 存在表示曾建過,但 Conversation 物件本 process 沒有
        # Phase 7 範圍:回 None,caller 視同「新 session」自動建
        # Phase 7c 加 cross-instance 復原(Redis state + transcript replay)
        return None

    async def delete(self, user_id: str, session_id: UUID) -> bool:
        async with db_session(self.engine) as db:
            stmt = delete(SessionRow).where(
                SessionRow.id == str(session_id),
                SessionRow.user_id == user_id,
            )
            result = await db.execute(stmt)
            await db.commit()
            db_deleted = bool(getattr(result, "rowcount", 0))

        cached = self._cache.pop((user_id, session_id), None)
        return db_deleted or cached is not None

    async def list_for_user(self, user_id: str) -> list[SessionInfo]:
        async with db_session(self.engine) as db:
            stmt = (
                select(SessionRow)
                .where(SessionRow.user_id == user_id)
                .order_by(SessionRow.updated_at.desc())
            )
            result = await db.execute(stmt)
            rows = result.scalars().all()

        out: list[SessionInfo] = []
        for r in rows:
            try:
                sid = UUID(r.id)
            except ValueError:
                continue
            # 若有 in-memory cache,用快取的精確 stats;否則 DB 值
            cached = self._cache.get((user_id, sid))
            if cached is not None:
                out.append(
                    SessionInfo(
                        session_id=sid,
                        user_id=user_id,
                        n_messages=len(cached.state_messages),
                        n_turns=cached.stats.turns,
                    )
                )
            else:
                out.append(
                    SessionInfo(
                        session_id=sid,
                        user_id=user_id,
                        n_messages=r.n_messages,
                        n_turns=r.n_turns,
                    )
                )
        return out

    async def size(self) -> int:
        async with db_session(self.engine) as db:
            from sqlalchemy import func
            stmt = select(func.count(SessionRow.id))
            result = await db.execute(stmt)
            return int(result.scalar() or 0)

    async def sync_stats(
        self, user_id: str, session_id: UUID,
    ) -> None:
        """把 cache 的 Conversation.stats 同步進 DB 行(turn 結束時 caller 呼)。"""
        cached = self._cache.get((user_id, session_id))
        if cached is None:
            return
        async with db_session(self.engine) as db:
            stmt = select(SessionRow).where(SessionRow.id == str(session_id))
            row = (await db.execute(stmt)).scalar_one_or_none()
            if row is None:
                return
            row.n_turns = cached.stats.turns
            row.n_messages = len(cached.state_messages)
            row.input_tokens = cached.stats.input_tokens
            row.output_tokens = cached.stats.output_tokens
            await db.commit()

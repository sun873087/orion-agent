"""In-memory SessionManager — 保存 user × session_id → Conversation。

Phase 6 範圍。Phase 7 換 Postgres + cross-instance shared store。

設計:
- key: (user_id, session_id) tuple
- value: Conversation
- list_for_user(user_id) → 該 user 所有 session 摘要
- get / create / delete / contains
- Thread-safe via anyio.Lock(雖 FastAPI 單 thread,future-proof)
"""

from __future__ import annotations

from dataclasses import dataclass, field
from uuid import UUID, uuid4

import anyio

from orion_agent.core.conversation import Conversation


@dataclass
class SessionInfo:
    """給 list endpoint 用的簡略資訊。"""

    session_id: UUID
    user_id: str
    n_messages: int
    n_turns: int


@dataclass
class SessionManager:
    """記憶體中 sessions 表。"""

    _sessions: dict[tuple[str, UUID], Conversation] = field(default_factory=dict)
    _lock: anyio.Lock = field(default_factory=anyio.Lock)

    async def create(
        self,
        *,
        user_id: str,
        session_id: UUID | None = None,
        conversation: Conversation,
    ) -> UUID:
        """註冊一個 Conversation 進 manager。session_id 沒傳則自動產。"""
        sid = session_id if session_id is not None else uuid4()
        async with self._lock:
            self._sessions[(user_id, sid)] = conversation
        return sid

    async def get(self, user_id: str, session_id: UUID) -> Conversation | None:
        async with self._lock:
            return self._sessions.get((user_id, session_id))

    async def delete(self, user_id: str, session_id: UUID) -> bool:
        async with self._lock:
            return self._sessions.pop((user_id, session_id), None) is not None

    async def list_for_user(self, user_id: str) -> list[SessionInfo]:
        async with self._lock:
            out: list[SessionInfo] = []
            for (uid, sid), conv in self._sessions.items():
                if uid != user_id:
                    continue
                out.append(
                    SessionInfo(
                        session_id=sid,
                        user_id=uid,
                        n_messages=len(conv.state_messages),
                        n_turns=conv.stats.turns,
                    )
                )
            return out

    async def size(self) -> int:
        async with self._lock:
            return len(self._sessions)

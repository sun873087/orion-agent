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

import logging
import shutil
from dataclasses import dataclass, field
from uuid import UUID, uuid4

import anyio

from orion_agent.core.conversation import Conversation
from orion_agent.storage.paths import session_paths

logger = logging.getLogger(__name__)


def _rmtree_session_dir(session_id: UUID) -> None:
    """刪整個 `~/.orion/sessions/<sid>/`(transcript / file-history / tool-results /
    workspace)。Phase 28:介面刪 session 該把所有相關資料一起清。"""
    root = session_paths(session_id).root
    if root.exists():
        shutil.rmtree(root, ignore_errors=True)
        logger.info("session_fs_removed sid=%s", session_id)


@dataclass
class SessionInfo:
    """給 list endpoint 用的簡略資訊。"""

    session_id: UUID
    user_id: str
    n_messages: int
    n_turns: int
    provider: str
    model: str


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
            removed = self._sessions.pop((user_id, session_id), None) is not None
        # Phase 28:fs cleanup(in-memory mode 也有 transcript / file-history 等)
        await anyio.to_thread.run_sync(_rmtree_session_dir, session_id)
        return removed

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
                        provider=conv.provider.name,
                        model=conv.provider.model,
                    )
                )
            return out

    async def size(self) -> int:
        async with self._lock:
            return len(self._sessions)

    async def sync_stats(self, user_id: str, session_id: UUID) -> None:
        """In-memory 版不需要持久化 — list_for_user 直接讀 conv.state_messages。

        DbSessionManager 有實作把 cache stats 同步進 DB row;這裡是 no-op,讓
        chat handler 可以無條件呼叫,protocol 對齊。
        """
        _ = (user_id, session_id)

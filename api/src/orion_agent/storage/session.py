"""Session storage — JSONL transcript per session(+ optional DB message dual-write)。

對應 TS Claude Code `src/utils/sessionStorage.ts`。

每筆 record 一行 JSON,kind 字段區分:
- "session-meta":session 開始/結束時的元資料(start_time、provider、model)
- "message":NormalizedMessage 整份(role + content blocks)
- "tool-result-replacement":Phase 2 第 3 層做的替換決策(供 resume 重建 state)
- "transition":Terminal 訊號(loop 終止理由 + 統計)

並發保護:用 anyio.Lock 包 file append,確保多 task yield 訊息時不交錯寫亂。

對應 spec 踩雷 #1。

Phase 27:`SessionStorage.open(..., db_engine=...)` 時 `record_message` 額外 INSERT 進
`messages` table。JSONL 仍是事件 audit log(transitions / replacements 沒有 DB 表);
DB 是 message 的可查詢 mirror,resume 優先讀 DB。
"""

from __future__ import annotations

import json
import logging
from datetime import UTC, datetime
from pathlib import Path
from typing import Any
from uuid import UUID, uuid4

import anyio
from pydantic import BaseModel
from sqlalchemy.ext.asyncio import AsyncEngine

from orion_agent.llm.types import NormalizedMessage
from orion_agent.storage.db.engine import db_session
from orion_agent.storage.db.models import Message as MessageRow
from orion_agent.storage.paths import SessionPaths, session_paths
from orion_agent.storage.replacement_state import ReplacementDecision

logger = logging.getLogger(__name__)


def _message_raw_text(message: NormalizedMessage) -> str:
    """擷取 plain text 給 messages.raw_text 用(SQL search-friendly)。"""
    content = message.content
    if isinstance(content, str):
        return content
    parts: list[str] = []
    for block in content:
        text = getattr(block, "text", None)
        if isinstance(text, str):
            parts.append(text)
    return "\n".join(parts)


def _serialize_value(v: Any) -> Any:
    """把 NormalizedMessage / Pydantic model 轉 JSON-friendly。"""
    if isinstance(v, BaseModel):
        return v.model_dump(mode="json")
    if isinstance(v, UUID):
        return str(v)
    if isinstance(v, Path):
        return str(v)
    return v


def _serialize_record(record: dict[str, Any]) -> str:
    """整個 record 轉一行 JSON。"""
    cleaned = {k: _serialize_value(v) for k, v in record.items()}
    return json.dumps(cleaned, ensure_ascii=False, default=str)


class SessionStorage:
    """單一 session 的 JSONL transcript。

    用法:
        async with SessionStorage.open(session_id) as store:
            await store.record_meta(provider="anthropic", model="claude-sonnet-4-6")
            await store.record_message(msg)
            ...
    """

    def __init__(
        self,
        paths: SessionPaths,
        *,
        db_engine: AsyncEngine | None = None,
    ) -> None:
        self.paths = paths
        self.db_engine = db_engine
        """Phase 27:non-None → `record_message` 同步 INSERT 進 messages 表。"""
        self._lock = anyio.Lock()

    @classmethod
    def open(
        cls,
        session_id: UUID,
        *,
        db_engine: AsyncEngine | None = None,
    ) -> SessionStorage:
        """工廠方法。確保 session 目錄存在。"""
        sp = session_paths(session_id)
        sp.ensure_dirs()
        return cls(sp, db_engine=db_engine)

    async def append_raw(self, record: dict[str, Any]) -> None:
        """寫一筆任意 record(底層)。caller 通常用更高階的 record_* 方法。"""
        line = _serialize_record(record) + "\n"
        async with (
            self._lock,
            await anyio.open_file(self.paths.transcript, "a", encoding="utf-8") as f,
        ):
            await f.write(line)

    async def record_meta(
        self,
        *,
        provider: str,
        model: str,
        system_prompt: str = "",
    ) -> None:
        await self.append_raw({
            "kind": "session-meta",
            "session_id": str(self.paths.session_id),
            "started_at": datetime.now(UTC).isoformat(),
            "provider": provider,
            "model": model,
            "system_prompt": system_prompt,
        })

    async def record_message(self, message: NormalizedMessage) -> None:
        await self.append_raw({
            "kind": "message",
            "ts": datetime.now(UTC).isoformat(),
            "message": message,
        })
        if self.db_engine is not None:
            await self._db_insert_message(message)

    async def _db_insert_message(self, message: NormalizedMessage) -> None:
        """Phase 27:INSERT 進 messages 表。失敗 log warning,不擋 JSONL 路徑。"""
        engine = self.db_engine
        if engine is None:
            return  # type narrow,實際上 caller 已 check 過
        content = message.content
        if isinstance(content, str):
            content_json: Any = content
        else:
            content_json = [
                b.model_dump(mode="json") if isinstance(b, BaseModel) else b
                for b in content
            ]
        row = MessageRow(
            id=str(uuid4()),
            session_id=str(self.paths.session_id),
            role=message.role,
            content_json=content_json,
            metadata_json=None,
            raw_text=_message_raw_text(message),
        )
        try:
            async with db_session(engine) as db:
                db.add(row)
                await db.commit()
        except Exception as e:  # noqa: BLE001
            # FK violation(session row 不存在)/ DB down → 不擋 JSONL canonical 寫入
            logger.warning(
                "db_message_insert_failed session=%s role=%s err=%s",
                self.paths.session_id, message.role, e,
            )

    async def record_replacement(
        self,
        decisions: list[ReplacementDecision],
    ) -> None:
        """記錄 Phase 2 第 3 層的替換決策(每個 ID 一筆)。"""
        for d in decisions:
            await self.append_raw({
                "kind": "tool-result-replacement",
                "ts": datetime.now(UTC).isoformat(),
                "tool_use_id": d.tool_use_id,
                "replacement": d.replacement,
            })

    async def record_transition(
        self,
        *,
        reason: str,
        total_turns: int,
    ) -> None:
        await self.append_raw({
            "kind": "transition",
            "ts": datetime.now(UTC).isoformat(),
            "reason": reason,
            "total_turns": total_turns,
        })


def iter_records_sync(transcript_path: Path) -> list[dict[str, Any]]:
    """讀整個 transcript 回 list of dict(同步版,給 resume 用)。"""
    if not transcript_path.exists():
        return []
    out: list[dict[str, Any]] = []
    with transcript_path.open("r", encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            try:
                out.append(json.loads(line))
            except json.JSONDecodeError:
                # 跳過損壞行(可能 process kill 寫到一半)
                continue
    return out

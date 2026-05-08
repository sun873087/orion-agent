"""Multi-agent 訊息協議。Phase 15。

`TaskAssignment` / `WorkerReport`:Coordinator(leader-worker)用。
`PeerMessage`:Swarm(peer-to-peer)用。
"""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Any, Literal
from uuid import UUID, uuid4

from pydantic import BaseModel, ConfigDict, Field

AgentRole = Literal["coordinator", "worker", "peer"]


def _now() -> datetime:
    return datetime.now(UTC)


class TaskAssignment(BaseModel):
    """Coordinator → Worker 的任務分派。"""

    model_config = ConfigDict(extra="forbid")

    task_id: UUID = Field(default_factory=uuid4)
    description: str
    """task 描述(自然語言,worker 直接 work on it)。"""

    context: dict[str, Any] = Field(default_factory=dict)
    """額外脈絡(parent 任務、相關檔案 ref 等)。"""

    expected_format: str | None = None
    """期望結果格式(如 "JSON" / "markdown report")— optional hint。"""

    max_turns: int = 10
    """worker 內部 query_loop 最大 turn 數。"""


WorkerStatus = Literal["completed", "failed"]


class WorkerReport(BaseModel):
    """Worker → Coordinator 的最終報告。"""

    model_config = ConfigDict(extra="forbid")

    task_id: UUID
    worker_id: str
    status: WorkerStatus
    final_text: str = ""
    """Worker 結束時最末 assistant text(便利欄位)。"""

    summary: str = ""
    """AgentSummary 產生的兩三句摘要(可選)。"""

    error: str | None = None
    """status="failed" 時必填。"""

    total_usage: dict[str, int] = Field(default_factory=dict)
    """累積 token usage(input_tokens / output_tokens / cache_read_tokens)。"""

    written_paths: list[str] = Field(default_factory=list)
    """worker 期間 Edit / Write 過的檔案路徑。"""


class PeerMessage(BaseModel):
    """Swarm peer 間訊息。"""

    model_config = ConfigDict(extra="forbid")

    message_id: UUID = Field(default_factory=uuid4)
    from_agent: str
    to_agent: str | None = None
    """None = broadcast(所有 peer 都收,排除 sender)。"""

    timestamp: datetime = Field(default_factory=_now)
    content: str
    metadata: dict[str, Any] = Field(default_factory=dict)


__all__ = [
    "AgentRole",
    "PeerMessage",
    "TaskAssignment",
    "WorkerReport",
    "WorkerStatus",
]

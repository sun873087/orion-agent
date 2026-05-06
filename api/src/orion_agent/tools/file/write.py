"""FileWriteTool — 寫整個檔案(覆蓋既有內容,或建新檔)。

對應 TS Claude Code `src/tools/FileWriteTool/`(簡化版)。

安全:
- 路徑必須絕對
- 父目錄必須已存在(不自動 mkdir,避免意外建一堆深目錄)
- 限制 1 MB(Phase 1 範圍,大檔屬 streaming write 範疇,延後)
- non-concurrency-safe(寫入有副作用)
- non-read-only
"""

from __future__ import annotations

from collections.abc import AsyncIterator
from pathlib import Path

from pydantic import Field

from orion_agent.core.state import AgentContext
from orion_agent.core.tool import ErrorEvent, TextEvent, ToolEvent, ToolInput

_MAX_BYTES = 1024 * 1024  # 1 MB


class FileWriteInput(ToolInput):
    """FileWriteTool 的 input schema。"""

    path: str = Field(..., description="Absolute path to the file to write.")
    content: str = Field(..., description="The full file content to write.")


class FileWriteTool:
    name = "Write"
    description = (
        "Write content to a file at an absolute path. "
        "Overwrites if the file exists; the parent directory must already exist."
    )
    input_schema = FileWriteInput

    async def call(
        self,
        input: FileWriteInput,
        ctx: AgentContext,  # noqa: ARG002
    ) -> AsyncIterator[ToolEvent]:
        path = Path(input.path)

        if not path.is_absolute():
            yield ErrorEvent(message=f"Path must be absolute: {input.path!r}")
            return

        parent = path.parent
        if not parent.exists():
            yield ErrorEvent(
                message=f"Parent directory does not exist: {parent}"
            )
            return

        if not parent.is_dir():
            yield ErrorEvent(message=f"Parent is not a directory: {parent}")
            return

        data = input.content.encode("utf-8")
        if len(data) > _MAX_BYTES:
            yield ErrorEvent(
                message=(
                    f"Content too large: {len(data)} bytes (max {_MAX_BYTES}). "
                    "Use multiple smaller writes for now."
                )
            )
            return

        if path.exists() and not path.is_file():
            yield ErrorEvent(message=f"Path exists but is not a regular file: {path}")
            return

        existed = path.exists()
        try:
            path.write_bytes(data)
        except OSError as e:
            yield ErrorEvent(message=f"Failed to write {path}: {e}")
            return

        action = "overwrote" if existed else "created"
        yield TextEvent(
            text=f"{action} {path} ({len(data)} bytes, {len(input.content.splitlines())} lines)"
        )

    def is_concurrency_safe(self, input: FileWriteInput) -> bool:  # noqa: ARG002
        return False

    def is_read_only(self, input: FileWriteInput) -> bool:  # noqa: ARG002
        return False

    def max_result_size_chars(self) -> int | float:
        return 1_000  # 結果只是一行確認訊息

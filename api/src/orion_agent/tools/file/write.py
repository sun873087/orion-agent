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
from orion_agent.storage.file_history import make_snapshot

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
        ctx: AgentContext,
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

        # Phase 12:覆寫既有檔必須先 Read 過 + 沒被外部改動
        # 新建檔(existed=False)不需要 Read(沒得讀)
        from orion_agent.services.file_state import FileStateCache, require_fresh_read

        cache = (
            ctx.file_state_cache
            if isinstance(ctx.file_state_cache, FileStateCache)
            else None
        )
        if cache is not None and existed:
            err = require_fresh_read(cache, path)
            if err is not None:
                yield ErrorEvent(message=err)
                return

        # Phase 2:寫前快照(若原檔存在)
        snap_note = ""
        if existed:
            snap = make_snapshot(ctx.session_id, path)
            if snap.snapshot_path is not None:
                snap_note = f"  [snapshot: {snap.snapshot_path}]"

        try:
            path.write_bytes(data)
        except OSError as e:
            yield ErrorEvent(message=f"Failed to write {path}: {e}")
            return

        # Phase 12:更新 cache snapshot(無論新建 / 覆寫,寫完後新內容才是 baseline)
        if cache is not None:
            cache.record_read(path)

        action = "overwrote" if existed else "created"
        yield TextEvent(
            text=(
                f"{action} {path} ({len(data)} bytes, "
                f"{len(input.content.splitlines())} lines){snap_note}"
            )
        )

    def is_concurrency_safe(self, input: FileWriteInput) -> bool:  # noqa: ARG002
        return False

    def is_read_only(self, input: FileWriteInput) -> bool:  # noqa: ARG002
        return False

    def max_result_size_chars(self) -> int | float:
        return 1_000  # 結果只是一行確認訊息

"""FileReadTool 唯一示範工具。

對應 TS Claude Code `src/tools/FileReadTool/FileReadTool.tsx`(簡化版)。
讀本機檔案,做基本安全檢查(只允許絕對路徑、限制大小)。
"""

from __future__ import annotations

from collections.abc import AsyncIterator
from pathlib import Path

from pydantic import Field

from orion_sdk.core.state import AgentContext
from orion_sdk.core.tool import ErrorEvent, TextEvent, ToolEvent, ToolInput

_MAX_BYTES = 256 * 1024 # 256 KB


class FileReadInput(ToolInput):
    """FileReadTool 的 input schema。"""

    path: str = Field(
        ...,
        description="Absolute path to the file to read.",
    )
    offset: int = Field(
        default=0,
        ge=0,
        description="Line offset (0-indexed). 0 = start of file.",
    )
    limit: int = Field(
        default=2000,
        gt=0,
        le=10_000,
        description="Max lines to read.",
    )


class FileReadTool:
    """Read a text file by absolute path。

    安全:
      - 必須絕對路徑(避免 cwd 漂移)
      - 限制 256 KB(再大需要 grep / specific lines)
      - 純讀,is_concurrency_safe=True
    """

    name = "Read"
    description = (
        "Read a text file from the local filesystem. "
        "Path must be absolute. Returns file content with line numbers."
    )
    input_schema = FileReadInput

    async def call(
        self,
        input: FileReadInput,
        ctx: AgentContext,
    ) -> AsyncIterator[ToolEvent]:
        path = Path(input.path)

        if not path.is_absolute():
            yield ErrorEvent(message=f"Path must be absolute: {input.path!r}")
            return

        if not path.exists():
            yield ErrorEvent(message=f"File not found: {input.path}")
            return

        if not path.is_file():
            yield ErrorEvent(message=f"Not a regular file: {input.path}")
            return

        size = path.stat().st_size
        if size > _MAX_BYTES:
            yield ErrorEvent(
                message=(
                    f"File too large: {size} bytes (max {_MAX_BYTES}). "
                    "Use offset/limit or grep for targeted reads."
                )
            )
            return

        try:
            text = path.read_text(encoding="utf-8")
        except UnicodeDecodeError:
            yield ErrorEvent(
                message=f"File is not valid UTF-8: {input.path}",
                is_recoverable=False,
            )
            return

        # 登錄到 file_state_cache(Edit/Write 之後驗證 staleness)
        from orion_sdk.services.file_state import FileStateCache

        if isinstance(ctx.file_state_cache, FileStateCache):
            ctx.file_state_cache.record_read(path)

        lines = text.splitlines()
        end = min(input.offset + input.limit, len(lines))
        selected = lines[input.offset : end]

        # cat -n 風格(行號 1-indexed)
        numbered = "\n".join(
            f"{i + 1 + input.offset}\t{line}" for i, line in enumerate(selected)
        )
        yield TextEvent(text=numbered or "(empty file)")

    def is_concurrency_safe(self, input: FileReadInput) -> bool: # noqa: ARG002
        return True

    def is_read_only(self, input: FileReadInput) -> bool: # noqa: ARG002
        return True

    def max_result_size_chars(self) -> int | float:
        return 100_000

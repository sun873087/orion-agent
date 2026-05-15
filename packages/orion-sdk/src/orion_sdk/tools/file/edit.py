"""FileEditTool — string replace。

對應 TS Claude Code `src/tools/FileEditTool/`(簡化版)。

模式:
- 預設:old_string 必須在檔內唯一,只取代一次
- replace_all=True:取代全部出現

「必須先讀過該檔」的隱性約束:模型若沒讀過檔案,不會知道 old_string 的精確內容
(包括 indentation / 行尾空白等),所以這條規則由「old_string 必須完全 match」自然
強制,不需另外追蹤 read state。

安全:
- 路徑必須絕對 + 必須是現存檔
- non-concurrency-safe(寫入)
"""

from __future__ import annotations

from collections.abc import AsyncIterator
from pathlib import Path

from pydantic import Field

from orion_sdk.core.state import AgentContext
from orion_sdk.core.tool import ErrorEvent, TextEvent, ToolEvent, ToolInput
from orion_sdk.storage.file_history import make_snapshot

_MAX_BYTES = 1024 * 1024  # 1 MB


class FileEditInput(ToolInput):
    """FileEditTool 的 input schema。"""

    path: str = Field(..., description="Absolute path to the file to edit.")
    old_string: str = Field(
        ..., description="The exact string to find and replace (must match including whitespace)."
    )
    new_string: str = Field(..., description="The replacement string.")
    replace_all: bool = Field(
        default=False,
        description="If True, replace all occurrences. If False (default), old_string must be unique.",
    )


class FileEditTool:
    name = "Edit"
    description = (
        "Replace text in a file. By default, old_string must be unique in the file; "
        "set replace_all=True to replace every occurrence. "
        "Path must be absolute and the file must exist."
    )
    input_schema = FileEditInput

    async def call(
        self,
        input: FileEditInput,
        ctx: AgentContext,
    ) -> AsyncIterator[ToolEvent]:
        path = Path(input.path)

        if not path.is_absolute():
            yield ErrorEvent(message=f"Path must be absolute: {input.path!r}")
            return

        if not path.exists():
            yield ErrorEvent(message=f"File does not exist: {path}")
            return

        if not path.is_file():
            yield ErrorEvent(message=f"Not a regular file: {path}")
            return

        if path.stat().st_size > _MAX_BYTES:
            yield ErrorEvent(
                message=f"File too large to edit ({path.stat().st_size} bytes, max {_MAX_BYTES})"
            )
            return

        # Phase 12:必須先 Read 過該檔且讀後沒被外部改過
        from orion_sdk.services.file_state import FileStateCache, require_fresh_read

        cache = (
            ctx.file_state_cache
            if isinstance(ctx.file_state_cache, FileStateCache)
            else None
        )
        if cache is not None:
            err = require_fresh_read(cache, path)
            if err is not None:
                yield ErrorEvent(message=err)
                return

        try:
            text = path.read_text(encoding="utf-8")
        except UnicodeDecodeError:
            yield ErrorEvent(message=f"File is not valid UTF-8: {path}")
            return

        if input.old_string == input.new_string:
            yield ErrorEvent(message="old_string and new_string are identical — no change.")
            return

        if input.old_string not in text:
            yield ErrorEvent(
                message=(
                    f"old_string not found in {path}. "
                    "It must match exactly including whitespace and line endings. "
                    "Read the file first to see its current content."
                )
            )
            return

        count = text.count(input.old_string)
        if not input.replace_all and count > 1:
            yield ErrorEvent(
                message=(
                    f"old_string appears {count} times in {path}. "
                    "Provide more surrounding context to make it unique, "
                    "or set replace_all=True."
                )
            )
            return

        new_text = (
            text.replace(input.old_string, input.new_string)
            if input.replace_all
            else text.replace(input.old_string, input.new_string, 1)
        )

        # Phase 2:寫前快照
        snap = make_snapshot(ctx.session_id, path)
        snap_note = (
            f"  [snapshot: {snap.snapshot_path}]"
            if snap.snapshot_path is not None
            else ""
        )

        try:
            path.write_text(new_text, encoding="utf-8")
        except OSError as e:
            yield ErrorEvent(message=f"Failed to write {path}: {e}")
            return

        # Phase 12:Edit 完成後更新 snapshot — 否則下次 Edit 會被當作 stale
        if cache is not None:
            cache.record_read(path)

        replaced = count if input.replace_all else 1
        yield TextEvent(
            text=(
                f"edited {path} — {replaced} occurrence(s) replaced "
                f"({len(text)} → {len(new_text)} chars){snap_note}"
            )
        )

    def is_concurrency_safe(self, input: FileEditInput) -> bool:  # noqa: ARG002
        return False

    def is_read_only(self, input: FileEditInput) -> bool:  # noqa: ARG002
        return False

    def max_result_size_chars(self) -> int | float:
        return 1_000

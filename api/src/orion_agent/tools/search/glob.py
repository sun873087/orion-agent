"""GlobTool — pathlib glob,類 fast file finder。

對應 TS Claude Code `src/tools/GlobTool/`。Phase 1 簡化版,只支援基本 glob pattern。

語意:`**/*.py` 遞迴所有 .py 檔。`*.txt` 只看 cwd 一層。
"""

from __future__ import annotations

import contextlib
from collections.abc import AsyncIterator
from pathlib import Path

from pydantic import Field

from orion_agent.core.state import AgentContext
from orion_agent.core.tool import ErrorEvent, TextEvent, ToolEvent, ToolInput

_MAX_RESULTS = 500


class GlobInput(ToolInput):
    """GlobTool 的 input schema。"""

    pattern: str = Field(
        ...,
        description="Glob pattern, e.g. '**/*.py' for recursive, '*.txt' for current dir only.",
    )
    base_path: str | None = Field(
        default=None,
        description="Absolute base directory to search from. Defaults to current process cwd.",
    )


class GlobTool:
    name = "Glob"
    description = (
        "Find files matching a glob pattern. Use '**/*.ext' for recursive search, "
        "'*.ext' for current directory only. Returns up to 500 paths sorted by mtime (newest first)."
    )
    input_schema = GlobInput

    async def call(
        self,
        input: GlobInput,
        ctx: AgentContext,
    ) -> AsyncIterator[ToolEvent]:
        base_str = input.base_path or str(ctx.cwd)
        base = Path(base_str)

        if not base.is_absolute():
            yield ErrorEvent(message=f"base_path must be absolute: {base_str!r}")
            return

        if not base.exists() or not base.is_dir():
            yield ErrorEvent(message=f"base_path does not exist or is not a directory: {base}")
            return

        try:
            matches = list(base.glob(input.pattern))
        except (OSError, ValueError) as e:
            yield ErrorEvent(message=f"glob failed: {e}")
            return

        # 過濾 dirs(只回 file)
        files = [p for p in matches if p.is_file()]

        # 按 mtime 降序
        with contextlib.suppress(OSError):
            files.sort(key=lambda p: p.stat().st_mtime, reverse=True)

        truncated = len(files) > _MAX_RESULTS
        files = files[:_MAX_RESULTS]

        if not files:
            yield TextEvent(text=f"(no files matched {input.pattern!r} under {base})")
            return

        lines = [str(p) for p in files]
        out = f"# {len(files)} match(es) for {input.pattern!r} under {base}\n" + "\n".join(lines)
        if truncated:
            out += f"\n... (truncated at {_MAX_RESULTS})"
        yield TextEvent(text=out)

    def is_concurrency_safe(self, input: GlobInput) -> bool:  # noqa: ARG002
        return True  # 純讀

    def is_read_only(self, input: GlobInput) -> bool:  # noqa: ARG002
        return True

    def max_result_size_chars(self) -> int | float:
        return 50_000

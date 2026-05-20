"""GlobTool — pathlib glob,類 fast file finder。

對應 TS Claude Code `src/tools/GlobTool/`。簡化版,只支援基本 glob pattern。

語意:`**/*.py` 遞迴所有 .py 檔。`*.txt` 只看 cwd 一層。

記憶體控制:用 heapq.heap of size _MAX_RESULTS,iter base.glob() 不一次性 list 所有路徑。
若 base 是 1M 檔的目錄,記憶體用量保持 O(_MAX_RESULTS) 而非 O(總檔數)。
"""

from __future__ import annotations

import heapq
from collections.abc import AsyncIterator
from pathlib import Path

from pydantic import Field

from orion_sdk.core.state import AgentContext
from orion_sdk.core.tool import ErrorEvent, TextEvent, ToolEvent, ToolInput

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

        # Min-heap of size _MAX_RESULTS,key 為 (mtime, str(path)) 確保 tie-break 穩定。
        # iterate base.glob 是 generator,不一次性載入所有 Path。
        heap: list[tuple[float, str, Path]] = []
        truncated = False
        try:
            for p in base.glob(input.pattern):
                if not p.is_file():
                    continue
                try:
                    mtime = p.stat().st_mtime
                except OSError:
                    continue # broken symlink / permission denied
                if len(heap) < _MAX_RESULTS:
                    heapq.heappush(heap, (mtime, str(p), p))
                else:
                    truncated = True
                    # 只在 mtime 比 heap 最舊還新時替換 → 維持 top-N newest
                    if mtime > heap[0][0]:
                        heapq.heapreplace(heap, (mtime, str(p), p))
        except (OSError, ValueError) as e:
            yield ErrorEvent(message=f"glob failed: {e}")
            return

        # 從 heap 抽出 → 按 mtime 降序排
        files = [p for _, _, p in sorted(heap, key=lambda x: x[0], reverse=True)]

        if not files:
            yield TextEvent(text=f"(no files matched {input.pattern!r} under {base})")
            return

        lines = [str(p) for p in files]
        out = f"# {len(files)} match(es) for {input.pattern!r} under {base}\n" + "\n".join(lines)
        if truncated:
            out += (
                f"\n... (showing newest {_MAX_RESULTS}; "
                "more matches exist — narrow the pattern)"
            )
        yield TextEvent(text=out)

    def is_concurrency_safe(self, input: GlobInput) -> bool: # noqa: ARG002
        return True # 純讀

    def is_read_only(self, input: GlobInput) -> bool: # noqa: ARG002
        return True

    def max_result_size_chars(self) -> int | float:
        return 50_000

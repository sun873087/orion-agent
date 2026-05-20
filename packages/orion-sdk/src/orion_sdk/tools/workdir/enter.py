"""EnterWorkdirTool — 切換 ctx.cwd 並把舊值 push 進 stack。

對應 TS EnterWorktreeTool 但不依賴 git。sandbox 啟用時,cwd 是 sandbox 內視角。
sandbox 不啟時,cwd 是 host fs 視角(下游 tools 用此 cwd 解析 relative path)。

Behaviour:
- 必須絕對路徑(reject relative)
- sandbox 不啟 → 檢查 host fs 存在 + is_dir
- sandbox 啟用 → 用 backend.exec("test -d <path>") 確認(避免 host check)
"""

from __future__ import annotations

from collections.abc import AsyncIterator
from pathlib import Path

from pydantic import Field

from orion_sdk.core.state import AgentContext
from orion_sdk.core.tool import ErrorEvent, TextEvent, ToolEvent, ToolInput
from orion_sdk.sandbox.protocol import SandboxBackend, SandboxError


class EnterWorkdirInput(ToolInput):
    path: str = Field(
        ...,
        description="Absolute path to switch into. Pushes the previous cwd onto the stack.",
    )


class EnterWorkdirTool:
    name = "EnterWorkdir"
    description = (
        "Switch the agent's working directory. Equivalent to `cd <path>`. "
        "Subsequent tools (Read/Write/Bash) treat their relative paths as relative to "
        "this cwd. Use ExitWorkdir to return to the previous cwd."
    )
    input_schema = EnterWorkdirInput

    async def call(
        self,
        input: EnterWorkdirInput,
        ctx: AgentContext,
    ) -> AsyncIterator[ToolEvent]:
        target = Path(input.path)
        if not target.is_absolute():
            yield ErrorEvent(message=f"path must be absolute: {input.path!r}")
            return

        # 驗證目標目錄存在
        sb = ctx.sandbox_backend
        if isinstance(sb, SandboxBackend):
            try:
                res = await sb.exec(["test", "-d", str(target)], timeout=5.0)
            except SandboxError as e:
                yield ErrorEvent(message=f"failed to verify path in sandbox: {e}")
                return
            if res.exit_code != 0:
                yield ErrorEvent(message=f"directory does not exist in sandbox: {target}")
                return
        else:
            if not target.exists():
                yield ErrorEvent(message=f"directory does not exist: {target}")
                return
            if not target.is_dir():
                yield ErrorEvent(message=f"not a directory: {target}")
                return

        # push 舊 cwd 進 stack,改 ctx.cwd
        ctx.cwd_stack.append(ctx.cwd)
        ctx.cwd = target

        yield TextEvent(
            text=(
                f"entered {target} "
                f"(stack depth: {len(ctx.cwd_stack)})"
            ),
        )

    def is_concurrency_safe(self, input: EnterWorkdirInput) -> bool: # noqa: ARG002
        return False # 改 ctx 共享狀態,不能並行

    def is_read_only(self, input: EnterWorkdirInput) -> bool: # noqa: ARG002
        return False

    def max_result_size_chars(self) -> int | float:
        return 1_000

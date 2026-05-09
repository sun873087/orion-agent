"""BashTool — 跑任意 shell command。對應 TS Claude Code `src/tools/BashTool/`。

Phase 1 範圍:
- asyncio subprocess + 預設 30s timeout(5min 上限)
- 捕捉合併 stdout + stderr
- 檢查 ctx.abort_event,被觸發就 kill
- non-concurrency-safe(side effects)、non-read-only

Phase 1 故意不做的:
- 真正的 streaming output(整個跑完才回)
- Sandbox 隔離(Phase 7 / Phase 12)
- Sibling abort(StreamingToolExecutor 來處理)
"""

from __future__ import annotations

import contextlib
import os
import shlex
from collections.abc import AsyncIterator

import anyio
from pydantic import Field

from orion_agent.core.state import AgentContext
from orion_agent.core.tool import ErrorEvent, TextEvent, ToolEvent, ToolInput

_DEFAULT_TIMEOUT_S = 30
_MAX_TIMEOUT_S = 300  # 5 min hard cap
_MAX_OUTPUT_BYTES = 30_000  # 大輸出截斷


class BashInput(ToolInput):
    """BashTool 的 input schema。"""

    command: str = Field(
        ...,
        description="The shell command to run. Use absolute paths. Quote arguments containing spaces.",
    )
    description: str = Field(
        default="",
        max_length=200,
        description=(
            "Short imperative-mood label of what this command does (5-10 words). "
            "Shown to the user in the activity feed. "
            'Examples: "Build the docker image", "List session files", '
            '"Find TODO comments in src/".'
        ),
    )
    timeout_seconds: int = Field(
        default=_DEFAULT_TIMEOUT_S,
        ge=1,
        le=_MAX_TIMEOUT_S,
        description=f"Timeout in seconds (default {_DEFAULT_TIMEOUT_S}, max {_MAX_TIMEOUT_S}).",
    )
    cwd: str | None = Field(
        default=None,
        description="Working directory (absolute path). Defaults to current process cwd.",
    )


class BashTool:
    name = "Bash"
    description = (
        "Run a shell command via /bin/bash and return combined stdout+stderr. "
        f"Default timeout {_DEFAULT_TIMEOUT_S}s, max {_MAX_TIMEOUT_S}s. "
        "Output is truncated past 30KB. "
        "NOT concurrency-safe — runs sequentially, never in parallel with other tools."
    )
    input_schema = BashInput

    async def call(
        self,
        input: BashInput,
        ctx: AgentContext,
    ) -> AsyncIterator[ToolEvent]:
        cwd = input.cwd
        if cwd is not None:
            if not os.path.isabs(cwd):
                yield ErrorEvent(message=f"cwd must be absolute path: {cwd!r}")
                return
            if not os.path.isdir(cwd):
                yield ErrorEvent(message=f"cwd does not exist or is not a directory: {cwd}")
                return
        else:
            # 沒指定 → fallback 到 ctx.cwd(per-session workspace,避免污染 server cwd)
            cwd = str(ctx.cwd)

        # 用 /bin/bash -c 跑,語意與 user 在 terminal 鍵入相同
        argv = ["/bin/bash", "-c", input.command]

        try:
            with anyio.move_on_after(input.timeout_seconds) as scope:
                process = await anyio.open_process(
                    argv,
                    stdout=-1,  # asyncio.subprocess.PIPE
                    stderr=-2,  # asyncio.subprocess.STDOUT — 合併
                    cwd=cwd,
                )
                # 一邊讀 output 一邊監看 abort_event
                output_chunks: list[bytes] = []
                bytes_total = 0
                truncated = False

                async def read_output() -> None:
                    nonlocal bytes_total, truncated
                    if process.stdout is None:
                        return
                    async for chunk in process.stdout:
                        if bytes_total + len(chunk) > _MAX_OUTPUT_BYTES:
                            keep = _MAX_OUTPUT_BYTES - bytes_total
                            if keep > 0:
                                output_chunks.append(chunk[:keep])
                                bytes_total += keep
                            truncated = True
                            break
                        output_chunks.append(chunk)
                        bytes_total += len(chunk)

                async def watch_abort() -> None:
                    while process.returncode is None:
                        if ctx.abort_event.is_set():
                            with contextlib.suppress(ProcessLookupError):
                                process.terminate()
                            return
                        await anyio.sleep(0.1)

                async with anyio.create_task_group() as tg:
                    tg.start_soon(read_output)
                    tg.start_soon(watch_abort)
                    await process.wait()
                    # process 結束後,read_output 自然完成,watch_abort 被取消
                    tg.cancel_scope.cancel()
        except Exception as e:  # noqa: BLE001
            yield ErrorEvent(message=f"Failed to run bash: {type(e).__name__}: {e}")
            return

        if scope.cancel_called:
            # timeout
            with contextlib.suppress(ProcessLookupError):
                if process.returncode is None:
                    process.terminate()
                    with anyio.move_on_after(2):
                        await process.wait()
                    if process.returncode is None:
                        process.kill()
            yield ErrorEvent(
                message=f"command timed out after {input.timeout_seconds}s: {input.command}",
            )
            return

        try:
            output_text = b"".join(output_chunks).decode("utf-8", errors="replace")
        except Exception as e:  # noqa: BLE001
            yield ErrorEvent(message=f"Could not decode output: {e}")
            return

        if truncated:
            output_text += f"\n... [output truncated at {_MAX_OUTPUT_BYTES} bytes]"

        rc = process.returncode
        header = f"$ {input.command}\n[exit {rc}]\n"
        body = output_text if output_text else "(no output)"
        full = header + body

        if rc != 0:
            yield ErrorEvent(message=full)
        else:
            yield TextEvent(text=full)

    def is_concurrency_safe(self, input: BashInput) -> bool:  # noqa: ARG002
        return False

    def is_read_only(self, input: BashInput) -> bool:  # noqa: ARG002
        # 動態判斷太複雜(`ls` vs `rm`),Phase 1 保守 False
        return False

    def max_result_size_chars(self) -> int | float:
        return _MAX_OUTPUT_BYTES

    def __init__(self) -> None:
        # 占位(避免 lint 抱怨 unused arg 之類)
        # 用來確保未來 _Shlex.quote 之類的 helper 可加進來
        self._shlex = shlex

"""Sub-agent isolation — Phase 9。對應 TS forkSubagent + EnterWorktreeTool。

每個子 agent 拿:
- 新 session_id(獨立)
- 新 abort_event(父 abort 不影響子,反之亦然)
- 新 sandbox backend(父子並行操作 fs 不互相干擾)
- 父 cwd / feature_flags 複製
- sub_agent_depth + 1(>=2 拒 spawn)

`fork_context_for_subagent(parent, *, sandbox_factory)` 回新 ctx + 對應 sandbox。
caller 在 child agent 結束時 call `release_subagent(ctx)` 釋放 sandbox。
"""

from __future__ import annotations

import contextlib
from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from typing import Any
from uuid import uuid4

import anyio

from orion_sdk.core.state import AgentContext
from orion_sdk.sandbox.protocol import SandboxBackend

SandboxFactory = Callable[[], SandboxBackend]
"""同步 factory:每次 call 回新的 SandboxBackend instance(已 init)。"""


AsyncSandboxFactory = Callable[[], Awaitable[SandboxBackend]]
"""async factory(若需要 await 才能建)。"""


@dataclass
class SubagentHandle:
    """fork 結果 — caller 拿 ctx 跑子 agent,結束 call release。"""

    ctx: AgentContext
    sandbox: SandboxBackend | None
    """新建的 sandbox(若 factory 提供);若 None 表示子 agent 共用父 sandbox。"""
    parent_session_id: str
    """父的 session_id(供日誌 / event 標記)。"""


async def fork_context_for_subagent(
    parent: AgentContext,
    *,
    sandbox_factory: SandboxFactory | AsyncSandboxFactory | None = None,
    inherit_sandbox: bool = False,
) -> SubagentHandle:
    """為子 agent 建獨立 ctx。

    Args:
        parent: 父 ctx。
        sandbox_factory: 給子 agent 一個新 sandbox 的 factory(同步或 async)。
            None → 不建新 sandbox。
        inherit_sandbox: True → 子共用父的 sandbox(忽略 factory)。

    Returns:
        SubagentHandle —— 子 ctx + (可選)新 sandbox。
    """
    new_session_id = uuid4()

    new_sandbox: SandboxBackend | None = None
    if inherit_sandbox:
        # 共用父的;這裡型別是 object | None,做 isinstance check 確保是 SandboxBackend
        psb = parent.sandbox_backend
        if isinstance(psb, SandboxBackend):
            new_sandbox = psb
    elif sandbox_factory is not None:
        result = sandbox_factory()
        if hasattr(result, "__await__"):
            new_sandbox = await result  # type: ignore[misc]
        else:
            new_sandbox = result

    child = AgentContext(
        session_id=new_session_id,
        cwd=parent.cwd,
        abort_event=anyio.Event(),
        feature_flags=dict(parent.feature_flags),
        sub_agent_depth=parent.sub_agent_depth + 1,
        user_id=parent.user_id,
        replacement_state=None,  # 子 agent 不繼承 parent 的 replacement_state
        sandbox_backend=new_sandbox,
    )
    return SubagentHandle(
        ctx=child,
        sandbox=new_sandbox if not inherit_sandbox else None,
        parent_session_id=str(parent.session_id),
    )


async def release_subagent(handle: SubagentHandle) -> None:
    """釋放子 agent 拿的 sandbox(若是新建的)。

    handle.sandbox is None(共用父)→ no-op。
    """
    sb = handle.sandbox
    if sb is None:
        return
    with contextlib.suppress(Exception):
        await sb.cleanup()


__all__ = [
    "AsyncSandboxFactory",
    "SandboxFactory",
    "SubagentHandle",
    "fork_context_for_subagent",
    "release_subagent",
]


# 輔助:給型別檢查者(避免 unused import)
_: Any = anyio

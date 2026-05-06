"""批次模式工具編排。對應 TS Claude Code `src/services/tools/toolOrchestration.ts`。

partition_tool_calls + run_tools。連續 concurrency-safe 的工具打成同 batch 並發,
non-safe 自成 batch 序列執行。

vs StreamingToolExecutor(streaming_executor.py):
- 本檔(批次模式)— 等模型整輪 yield 完所有 tool_use 才開始
- StreamingToolExecutor — 模型 yield 一個 tool_use 立刻開始

main loop 用 streaming executor;此處保留批次模式給測試 / fallback。
"""

from __future__ import annotations

import os
from collections.abc import AsyncIterator
from dataclasses import dataclass
from typing import Any

import anyio

from orion_agent.core.state import AgentContext
from orion_agent.core.tool import Tool
from orion_agent.core.tool_execution import (
    ToolUpdate,
    run_one_tool,
)
from orion_agent.hooks.registry import HookRegistry
from orion_agent.llm.types import ToolUseBlock
from orion_agent.permissions.decisions import CanUseToolFn


def get_max_concurrency() -> int:
    """從環境變數讀,預設 10。對應 TS getMaxToolUseConcurrency。"""
    raw = os.environ.get("ORION_MAX_TOOL_CONCURRENCY", "10")
    try:
        n = int(raw)
        return max(1, n)
    except ValueError:
        return 10


@dataclass
class Batch:
    """同 partition 的一群 tool_use。"""

    is_concurrency_safe: bool
    blocks: list[ToolUseBlock]


def partition_tool_calls(
    tool_uses: list[ToolUseBlock],
    tools: list[Tool[Any]],
) -> list[Batch]:
    """連續的 concurrency-safe 工具打成同一 batch,non-safe 自成 batch。

    對應 TS toolOrchestration.ts:partitionToolCalls。

    保守原則:
    - 找不到 tool name → 視為 non-safe(讓 run_one_tool 統一回 synthetic error)
    - input parse 失敗 → 視為 non-safe
    """
    tool_by_name = {t.name: t for t in tools}
    batches: list[Batch] = []

    for tu in tool_uses:
        tool = tool_by_name.get(tu.name)
        is_safe = False
        if tool is not None:
            try:
                parsed = tool.input_schema.model_validate(tu.input)
                is_safe = tool.is_concurrency_safe(parsed)
            except Exception:  # noqa: BLE001 — 任何 parse 錯都保守
                is_safe = False

        if is_safe and batches and batches[-1].is_concurrency_safe:
            batches[-1].blocks.append(tu)
        else:
            batches.append(Batch(is_concurrency_safe=is_safe, blocks=[tu]))

    return batches


async def run_tools(
    tool_uses: list[ToolUseBlock],
    *,
    tools: list[Tool[Any]],
    can_use_tool: CanUseToolFn,
    hooks: HookRegistry,
    ctx: AgentContext,
) -> AsyncIterator[ToolUpdate]:
    """批次模式主入口。yield ToolUpdate(progress + result)。

    對應 TS toolOrchestration.ts:runTools。
    """
    tools_by_name = {t.name: t for t in tools}

    for batch in partition_tool_calls(tool_uses, tools):
        if batch.is_concurrency_safe and len(batch.blocks) > 1:
            async for upd in run_tools_concurrently(
                batch.blocks,
                tools_by_name=tools_by_name,
                can_use_tool=can_use_tool,
                hooks=hooks,
                ctx=ctx,
            ):
                yield upd
        else:
            for tu in batch.blocks:
                async for upd in run_one_tool(
                    tu.id,
                    tu.name,
                    tu.input,
                    tools_by_name=tools_by_name,
                    can_use_tool=can_use_tool,
                    hooks=hooks,
                    ctx=ctx,
                ):
                    yield upd


async def run_tools_concurrently(
    tool_uses: list[ToolUseBlock],
    *,
    tools_by_name: dict[str, Tool[Any]],
    can_use_tool: CanUseToolFn,
    hooks: HookRegistry,
    ctx: AgentContext,
) -> AsyncIterator[ToolUpdate]:
    """並發跑多個工具,結果按 tool_uses 原順序 yield。

    用 anyio TaskGroup + CapacityLimiter。Order preservation:結果暫存到 dict,
    最後依 index 順序 yield 出來(spec 要求,維持 message 順序對齊)。

    對應 TS runToolsConcurrently 的 all(generators, concurrency)。
    """
    max_conc = get_max_concurrency()
    limiter = anyio.CapacityLimiter(max_conc)
    results_by_index: dict[int, list[ToolUpdate]] = {}

    async def run_indexed(i: int, tu: ToolUseBlock) -> None:
        async with limiter:
            chunks: list[ToolUpdate] = []
            async for upd in run_one_tool(
                tu.id,
                tu.name,
                tu.input,
                tools_by_name=tools_by_name,
                can_use_tool=can_use_tool,
                hooks=hooks,
                ctx=ctx,
            ):
                chunks.append(upd)
            results_by_index[i] = chunks

    async with anyio.create_task_group() as tg:
        for i, tu in enumerate(tool_uses):
            tg.start_soon(run_indexed, i, tu)

    for i in range(len(tool_uses)):
        for upd in results_by_index.get(i, []):
            yield upd

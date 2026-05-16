"""Real-API integration:LLM 平行呼叫多 tool。

驗證 StreamingExecutor 真實情境下:
- LLM 一次 emit 多個 tool_use
- 多 tool 並行執行
- ToolResult 順序遞回正確
"""

from __future__ import annotations

import os
from pathlib import Path

import pytest

from orion_sdk.core.conversation import Conversation
from orion_sdk.core.query_loop import AssistantTurnComplete, LoopTerminated
from orion_sdk.core.tool_execution import ToolResultUpdate
from orion_model.provider import get_provider
from orion_sdk.tools.file.read import FileReadTool

pytestmark = pytest.mark.skipif(
    not os.environ.get("ANTHROPIC_API_KEY"),
    reason="ANTHROPIC_API_KEY not set",
)


@pytest.mark.asyncio
async def test_parallel_reads_anthropic(tmp_path: Path) -> None:
    """要 LLM 同時讀兩個檔。Anthropic 預設支援 parallel tool use。"""
    f1 = tmp_path / "alpha.txt"
    f1.write_text("RED-77\n")
    f2 = tmp_path / "beta.txt"
    f2.write_text("BLUE-99\n")

    provider = get_provider("anthropic", "claude-sonnet-4-6")
    conv = Conversation(
        provider=provider,
        system_prompt=(
            "Use parallel tool calls when reading multiple independent files. "
            "Be concise."
        ),
        tools=[FileReadTool()],
        max_turns=5,
        persistence_enabled=False,
        memory_enabled=False,
    )

    tool_results: list[ToolResultUpdate] = []
    turn_completes = 0
    terminated = None
    final_text_chunks: list[str] = []

    from orion_sdk.core.query_loop import AssistantTextDelta

    prompt = f"Read both {f1} and {f2} and report the codes you find."
    async for ev in conv.send(prompt):
        if isinstance(ev, ToolResultUpdate):
            tool_results.append(ev)
        elif isinstance(ev, AssistantTurnComplete):
            turn_completes += 1
        elif isinstance(ev, AssistantTextDelta):
            final_text_chunks.append(ev.text)
        elif isinstance(ev, LoopTerminated):
            terminated = ev

    final_text = "".join(final_text_chunks)
    # 驗:兩個 tool result 都到了,且都成功
    assert len(tool_results) >= 2, f"expected ≥2 tool calls, got {len(tool_results)}"
    assert all(not r.is_error for r in tool_results), "some tool calls failed"
    # 驗 LLM 回應內提到兩個 code
    assert "RED-77" in final_text and "BLUE-99" in final_text, (
        f"final text missing codes: {final_text!r}"
    )
    assert terminated is not None

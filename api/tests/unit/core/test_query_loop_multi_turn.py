"""query_loop multi-turn:tool result 回填模型,再請求,直到 natural_stop。"""

from __future__ import annotations

import pytest

from orion_agent.core.query_loop import (
    AssistantTurnComplete,
    LoopTerminated,
    QueryParams,
    query_loop,
)
from orion_agent.core.state import AgentContext
from orion_agent.core.tool_execution import ToolResultUpdate
from orion_agent.hooks.registry import HookRegistry
from orion_model.types import ToolResultBlock, ToolUseBlock
from orion_agent.permissions.decisions import always_allow
from orion_agent.tools.file.read import FileReadTool
from tests.conftest import MockProvider, MockTurn


@pytest.mark.asyncio
async def test_tool_result_fed_back_to_model(
    tmp_path: object,
    sample_text_file: object,
) -> None:
    """Turn 1 模型 call Read,turn 2 模型看到結果後 natural_stop。"""
    file_path = str(sample_text_file)

    provider = MockProvider(turns=[
        MockTurn(text="reading", tool_uses=[("t1", "Read", {"path": file_path})]),
        MockTurn(text="contains alpha through epsilon"),
    ])

    params = QueryParams(
        provider=provider,  # type: ignore[arg-type]
        system_prompt="x",
        tools=[FileReadTool()],
        can_use_tool=always_allow,
        hooks=HookRegistry(),
        initial_messages=[],
    )

    events = [ev async for ev in query_loop(params, AgentContext())]

    # turn 1 + turn 2 各一次 AssistantTurnComplete
    turn_completes = [ev for ev in events if isinstance(ev, AssistantTurnComplete)]
    assert len(turn_completes) == 2

    # 工具有跑且成功
    tool_results = [ev for ev in events if isinstance(ev, ToolResultUpdate)]
    assert len(tool_results) == 1
    assert tool_results[0].is_error is False
    assert tool_results[0].tool_name == "Read"

    # 第二次 provider.stream 收到的 messages 應該含 tool_result
    second_call_messages = provider.captured_calls[1]["messages"]
    has_tool_result = any(
        isinstance(m.content, list) and any(isinstance(b, ToolResultBlock) for b in m.content)
        for m in second_call_messages
    )
    assert has_tool_result

    # 終止理由
    term = next(ev for ev in events if isinstance(ev, LoopTerminated))
    assert term.transition.reason == "natural_stop"
    assert term.total_turns == 2


@pytest.mark.asyncio
async def test_assistant_message_contains_tool_use_block(sample_text_file: object) -> None:
    """assistant turn 結束後,message.content 應含 ToolUseBlock(供下輪 API 帶上下文)。"""
    file_path = str(sample_text_file)
    provider = MockProvider(turns=[
        MockTurn(tool_uses=[("t1", "Read", {"path": file_path})]),
        MockTurn(text="ok"),
    ])
    params = QueryParams(
        provider=provider,  # type: ignore[arg-type]
        system_prompt="x",
        tools=[FileReadTool()],
        can_use_tool=always_allow,
        hooks=HookRegistry(),
        initial_messages=[],
    )

    events = [ev async for ev in query_loop(params, AgentContext())]
    first_turn = next(ev for ev in events if isinstance(ev, AssistantTurnComplete))
    blocks = first_turn.message.content
    assert isinstance(blocks, list)
    tool_use_blocks = [b for b in blocks if isinstance(b, ToolUseBlock)]
    assert len(tool_use_blocks) == 1
    assert tool_use_blocks[0].name == "Read"
    assert tool_use_blocks[0].input == {"path": file_path}

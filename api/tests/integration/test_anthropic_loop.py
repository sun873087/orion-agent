"""Anthropic 真實 multi-turn agent loop。

需 ANTHROPIC_API_KEY 環境變數,沒設就 skip。
"""

from __future__ import annotations

import os

import pytest

from orion_agent.core.conversation import Conversation
from orion_agent.core.query_loop import LoopTerminated
from orion_agent.llm.provider import get_provider
from orion_agent.tools.file.read import FileReadTool

pytestmark = pytest.mark.skipif(
    not os.environ.get("ANTHROPIC_API_KEY"),
    reason="ANTHROPIC_API_KEY not set — integration test skipped",
)


@pytest.mark.asyncio
async def test_multi_turn_with_file_read(tmp_path: object) -> None:
    """模型應 call Read,看內容,再回覆。"""
    # 建測試檔
    from pathlib import Path
    p = Path(tmp_path) / "secret.txt"  # type: ignore[arg-type]
    p.write_text("MAGIC-NUMBER-7421\n", encoding="utf-8")

    provider = get_provider("anthropic", "claude-sonnet-4-6")
    conv = Conversation(
        provider=provider,
        system_prompt="Use tools when needed. Be concise.",
        tools=[FileReadTool()],
        max_turns=5,
    )

    final_text = ""
    terminated = None
    async for ev in conv.send(
        f"Read {p} and tell me only the magic number, nothing else."
    ):
        from orion_agent.core.query_loop import AssistantTextDelta
        if isinstance(ev, AssistantTextDelta):
            final_text += ev.text
        elif isinstance(ev, LoopTerminated):
            terminated = ev

    assert terminated is not None
    assert terminated.transition.reason == "natural_stop"
    assert "7421" in final_text
    assert conv.stats.turns >= 2  # 至少一輪 read,一輪回覆
    assert conv.stats.tool_calls >= 1

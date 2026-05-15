"""OpenAI 真實 multi-turn agent loop。

需 OPENAI_API_KEY 環境變數,沒設就 skip。
"""

from __future__ import annotations

import os

import pytest

from orion_agent.core.conversation import Conversation
from orion_agent.core.query_loop import AssistantTextDelta, LoopTerminated
from orion_model.provider import get_provider
from orion_agent.tools.file.read import FileReadTool

pytestmark = pytest.mark.skipif(
    not os.environ.get("OPENAI_API_KEY"),
    reason="OPENAI_API_KEY not set — integration test skipped",
)


@pytest.mark.asyncio
async def test_multi_turn_with_file_read(tmp_path: object) -> None:
    """同 anthropic 版本 — 模型 call Read 看內容,回覆 magic number。"""
    from pathlib import Path
    p = Path(tmp_path) / "secret.txt"  # type: ignore[arg-type]
    p.write_text("MAGIC-NUMBER-9988\n", encoding="utf-8")

    provider = get_provider("openai", "gpt-4o-mini")
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
        if isinstance(ev, AssistantTextDelta):
            final_text += ev.text
        elif isinstance(ev, LoopTerminated):
            terminated = ev

    assert terminated is not None
    assert terminated.transition.reason == "natural_stop"
    assert "9988" in final_text
    assert conv.stats.turns >= 2
    assert conv.stats.tool_calls >= 1

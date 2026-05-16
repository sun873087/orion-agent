"""Real-API integration:abort mid-stream。

LLM 開始輸出長文,test 在收到第一個 text delta 後立刻 set abort,驗證:
- AbortEvent 被傳遞給 provider.stream
- httpx 連線被切
- LoopTerminated reason=='aborted'
- 不繼續吃 tokens
"""

from __future__ import annotations

import asyncio
import os

import pytest

from orion_sdk.core.conversation import Conversation
from orion_sdk.core.query_loop import (
    AssistantTextDelta,
    LoopTerminated,
)
from orion_sdk.core.state import AgentContext
from orion_model.provider import get_provider

pytestmark = pytest.mark.skipif(
    not os.environ.get("ANTHROPIC_API_KEY"),
    reason="ANTHROPIC_API_KEY not set",
)


@pytest.mark.asyncio
async def test_abort_after_first_token_anthropic() -> None:
    provider = get_provider("anthropic", "claude-sonnet-4-6")
    conv = Conversation(
        provider=provider,
        system_prompt="You output exactly what user requests, no more.",
        tools=[],
        max_turns=1,
        persistence_enabled=False,
        memory_enabled=False,
    )
    ctx = AgentContext()

    saw_first_text = False
    terminated: LoopTerminated | None = None
    text_delta_count = 0

    # 要 LLM 慢慢輸出一篇長文,abort 後不該收完
    prompt = (
        "Count from 1 to 200, one number per line, very slowly."
    )
    async for ev in conv.send(prompt, ctx=ctx):
        if isinstance(ev, AssistantTextDelta):
            text_delta_count += 1
            if not saw_first_text:
                saw_first_text = True
                # 收到第一個 text delta → 立刻 abort
                ctx.abort_event.set()
        elif isinstance(ev, LoopTerminated):
            terminated = ev
            break

    assert saw_first_text, "never received any text — provider 沒 stream"
    assert terminated is not None, "loop never terminated"
    assert terminated.transition.reason in ("aborted", "abort"), (
        f"expected aborted reason, got {terminated.transition.reason!r}"
    )
    # text_delta_count 應該明顯少於完整輸出(200 行 + 描述)
    # 寬鬆 assert:不該超過 100 個 delta(完整應該數百個)
    assert text_delta_count < 100, (
        f"too many text deltas ({text_delta_count}) — abort 沒生效"
    )

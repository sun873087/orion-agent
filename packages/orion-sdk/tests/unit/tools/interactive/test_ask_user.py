"""AskUserQuestionTool — fake asker round-trip + ws asker queue 整合。"""

from __future__ import annotations

import asyncio
from collections.abc import AsyncIterator
from typing import Any

import pytest

from orion_sdk.core.state import AgentContext
from orion_sdk.core.tool import ErrorEvent, TextEvent, ToolEvent
from orion_sdk.tools.interactive.ask_user import (
    AskOption,
    AskQuestion,
    AskUserQuestionInput,
    AskUserQuestionTool,
    PendingQuestions,
    make_ws_asker,
)


async def _collect(it: AsyncIterator[ToolEvent]) -> list[ToolEvent]:
    return [ev async for ev in it]


@pytest.mark.asyncio
async def test_no_asker_yields_error() -> None:
    tool = AskUserQuestionTool(asker=None)
    events = await _collect(
        tool.call(
            AskUserQuestionInput(
                questions=[AskQuestion(question="hi?")],
            ),
            AgentContext(),
        ),
    )
    assert any(isinstance(e, ErrorEvent) for e in events)


@pytest.mark.asyncio
async def test_asker_returns_answers() -> None:
    async def fake_asker(qs: list[dict[str, Any]]) -> dict[str, str]:
        return {q["question"]: "yes" for q in qs}

    tool = AskUserQuestionTool(asker=fake_asker)
    events = await _collect(
        tool.call(
            AskUserQuestionInput(
                questions=[
                    AskQuestion(question="continue?", options=[AskOption(label="yes")]),
                ],
            ),
            AgentContext(),
        ),
    )
    text = next(e.text for e in events if isinstance(e, TextEvent))
    assert "continue?" in text
    assert "yes" in text


@pytest.mark.asyncio
async def test_asker_returns_empty_means_no_response() -> None:
    async def fake_asker(qs: list[dict[str, Any]]) -> dict[str, str]:  # noqa: ARG001
        return {}

    tool = AskUserQuestionTool(asker=fake_asker)
    events = await _collect(
        tool.call(
            AskUserQuestionInput(questions=[AskQuestion(question="?")]),
            AgentContext(),
        ),
    )
    text = next(e.text for e in events if isinstance(e, TextEvent))
    assert "did not respond" in text or "timed out" in text


@pytest.mark.asyncio
async def test_ws_asker_resolved_via_pending() -> None:
    pending = PendingQuestions()
    queue: asyncio.Queue[Any] = asyncio.Queue()

    asker = make_ws_asker(outbound_queue=queue, pending=pending, timeout_s=5.0)

    # 模擬:asker spawn → ws reader 拿到 event → resolve
    async def reader_simulator() -> dict[str, str]:
        ev = await queue.get()
        rid = ev["request_id"]
        # 假設 user 答了
        await asyncio.sleep(0.05)
        pending.resolve(rid, {"continue?": "yes"})
        return {}

    async with asyncio.TaskGroup() as tg:
        tg.create_task(reader_simulator())
        result = await asker([{"question": "continue?", "options": []}])
    assert result == {"continue?": "yes"}


@pytest.mark.asyncio
async def test_ws_asker_timeout() -> None:
    pending = PendingQuestions()
    queue: asyncio.Queue[Any] = asyncio.Queue()

    asker = make_ws_asker(outbound_queue=queue, pending=pending, timeout_s=0.2)

    # 不 resolve;預期 timeout 後回 {}
    result = await asker([{"question": "x", "options": []}])
    assert result == {}

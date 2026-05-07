"""process_user_input 主協調器 — slash / text / image / upload。"""

from __future__ import annotations

from collections.abc import AsyncIterator
from typing import Any

import pytest

from orion_agent.commands.registry import clear_registry, register_command
from orion_agent.commands.types import CommandResult
from orion_agent.input.process_input import (
    CommandInjectEvent,
    CommandResultEvent,
    FileUploadRef,
    ImageAttachment,
    InputErrorEvent,
    RawInput,
    UserMessageEvent,
    process_user_input,
)


@pytest.fixture(autouse=True)
def _clean() -> None:
    clear_registry()


class _Echo:
    name = "echo"
    description = "echo args"

    async def execute(
        self, args: str, ctx: Any, conversation: Any,  # noqa: ARG002
    ) -> CommandResult:
        return CommandResult(text=f"echo: {args}", side_effect="echoed")


class _Crash:
    name = "crash"
    description = "raises"

    async def execute(
        self, args: str, ctx: Any, conversation: Any,  # noqa: ARG002
    ) -> CommandResult:
        raise RuntimeError("boom")


class _Inject:
    name = "inject"
    description = "inject"

    async def execute(
        self, args: str, ctx: Any, conversation: Any,  # noqa: ARG002
    ) -> CommandResult:
        return CommandResult(inject_into_prompt="extra prompt context")


class _Forward:
    name = "forward"
    description = "forward"

    async def execute(
        self, args: str, ctx: Any, conversation: Any,  # noqa: ARG002
    ) -> CommandResult:
        return CommandResult(new_user_message=f"converted: {args}")


async def _collect(it: AsyncIterator[Any]) -> list[Any]:
    return [ev async for ev in it]


@pytest.mark.asyncio
async def test_plain_text_yields_user_message() -> None:
    events = await _collect(process_user_input("hello", None, None))
    assert len(events) == 1
    assert isinstance(events[0], UserMessageEvent)
    assert events[0].content == "hello"


@pytest.mark.asyncio
async def test_empty_input_yields_error() -> None:
    events = await _collect(process_user_input("", None, None))
    assert any(isinstance(e, InputErrorEvent) for e in events)


@pytest.mark.asyncio
async def test_unknown_slash_yields_error() -> None:
    events = await _collect(process_user_input("/nonexistent", None, None))
    assert any(isinstance(e, InputErrorEvent) for e in events)
    msg = next(e for e in events if isinstance(e, InputErrorEvent)).message
    assert "nonexistent" in msg


@pytest.mark.asyncio
async def test_slash_executes_and_yields_command_result() -> None:
    register_command(_Echo())
    events = await _collect(process_user_input("/echo hello world", None, None))
    crs = [e for e in events if isinstance(e, CommandResultEvent)]
    assert len(crs) == 1
    assert "hello world" in crs[0].text
    assert crs[0].side_effect == "echoed"


@pytest.mark.asyncio
async def test_slash_command_crash_yields_error() -> None:
    register_command(_Crash())
    events = await _collect(process_user_input("/crash", None, None))
    assert any(isinstance(e, InputErrorEvent) for e in events)


@pytest.mark.asyncio
async def test_slash_inject_yields_inject_event() -> None:
    register_command(_Inject())
    events = await _collect(process_user_input("/inject", None, None))
    assert any(isinstance(e, CommandInjectEvent) for e in events)


@pytest.mark.asyncio
async def test_slash_new_user_message_yields_user_message() -> None:
    register_command(_Forward())
    events = await _collect(process_user_input("/forward task body", None, None))
    ums = [e for e in events if isinstance(e, UserMessageEvent)]
    assert len(ums) == 1
    assert "converted" in ums[0].content  # type: ignore[operator]


@pytest.mark.asyncio
async def test_image_attachment_yields_blocks() -> None:
    img = ImageAttachment(media_type="image/png", data="ZmFrZS1iYXNlNjQ=")
    raw = RawInput(text="describe this", images=[img])
    events = await _collect(process_user_input(raw, None, None))
    msg = next(e for e in events if isinstance(e, UserMessageEvent))
    assert isinstance(msg.content, list)
    types = [b.get("type") for b in msg.content]
    assert "text" in types
    assert "image" in types


@pytest.mark.asyncio
async def test_upload_ref_in_text_block() -> None:
    raw = RawInput(
        text="please review",
        uploads=[FileUploadRef(upload_id="abc123", filename="x.py")],
    )
    events = await _collect(process_user_input(raw, None, None))
    msg = next(e for e in events if isinstance(e, UserMessageEvent))
    assert isinstance(msg.content, list)
    text_block = next(b for b in msg.content if b["type"] == "text")
    assert "abc123" in text_block["text"]
    assert "x.py" in text_block["text"]


@pytest.mark.asyncio
async def test_text_only_no_blocks() -> None:
    raw = RawInput(text="hi")
    events = await _collect(process_user_input(raw, None, None))
    msg = next(e for e in events if isinstance(e, UserMessageEvent))
    # 純文字、無 attachment → content 是 str
    assert msg.content == "hi"

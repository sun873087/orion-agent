"""api/ws_permissions.py — make_can_use_tool_for_websocket 行為。"""

from __future__ import annotations

import asyncio
from typing import Any

import anyio
import pytest

from orion_chat_api.event_schema import PermissionAskEvent
from orion_chat_api.ws_permissions import (
    PendingPermissions,
    make_can_use_tool_for_websocket,
)
from orion_sdk.core.state import AgentContext
from orion_sdk.core.tool import ToolInput
from orion_sdk.permissions.decisions import PermissionDecision


class _FakeTool:
    name = "fake"
    description = "x"

    class Input(ToolInput):
        text: str = ""

    input_schema = Input

    def is_read_only(self, _: Any) -> bool:
        return False

    def is_concurrency_safe(self, _: Any) -> bool:
        return False


class _ReadOnlyTool(_FakeTool):
    name = "fake_ro"

    def is_read_only(self, _: Any) -> bool:
        return True


@pytest.mark.asyncio
async def test_read_only_tool_auto_allow() -> None:
    """is_read_only=True 工具直接 allow,不送 PermissionAskEvent。"""
    send, recv = anyio.create_memory_object_stream[Any](max_buffer_size=8)
    pending = PendingPermissions()
    can_use = make_can_use_tool_for_websocket(
        outbound_queue=send, pending=pending,  # type: ignore[arg-type]
    )

    result = await can_use(_ReadOnlyTool(), {"text": "x"}, AgentContext())  # type: ignore[arg-type]
    assert result.decision == PermissionDecision.ALLOW
    # 沒推任何 ask event(queue 應空)
    with pytest.raises(anyio.WouldBlock):
        recv.receive_nowait()


@pytest.mark.asyncio
async def test_non_read_only_asks_user() -> None:
    """non-read-only 應推 PermissionAskEvent + 等 future。"""
    send, recv = anyio.create_memory_object_stream[Any](max_buffer_size=8)
    pending = PendingPermissions()
    can_use = make_can_use_tool_for_websocket(
        outbound_queue=send, pending=pending,  # type: ignore[arg-type]
    )

    async def auto_responder() -> None:
        # 等 ask event 後,模擬 client 回 allow
        ask = await recv.receive()
        assert isinstance(ask, PermissionAskEvent)
        # 短暫延遲確保 future 已 set up
        await anyio.sleep(0.01)
        pending.resolve(ask.request_id, "allow")

    async with anyio.create_task_group() as tg:
        tg.start_soon(auto_responder)
        result = await can_use(_FakeTool(), {"text": "x"}, AgentContext())  # type: ignore[arg-type]

    assert result.decision == PermissionDecision.ALLOW


@pytest.mark.asyncio
async def test_user_denies() -> None:
    send, recv = anyio.create_memory_object_stream[Any](max_buffer_size=8)
    pending = PendingPermissions()
    can_use = make_can_use_tool_for_websocket(
        outbound_queue=send, pending=pending,  # type: ignore[arg-type]
    )

    async def auto_responder() -> None:
        ask = await recv.receive()
        assert isinstance(ask, PermissionAskEvent)
        await anyio.sleep(0.01)
        pending.resolve(ask.request_id, "deny")

    async with anyio.create_task_group() as tg:
        tg.start_soon(auto_responder)
        result = await can_use(_FakeTool(), {"text": "x"}, AgentContext())  # type: ignore[arg-type]

    assert result.decision == PermissionDecision.DENY


@pytest.mark.asyncio
async def test_timeout_auto_denies() -> None:
    send, _recv = anyio.create_memory_object_stream[Any](max_buffer_size=8)
    pending = PendingPermissions()
    # timeout 短一點測試
    can_use = make_can_use_tool_for_websocket(
        outbound_queue=send, pending=pending, timeout_s=1,  # type: ignore[arg-type]
    )

    result = await can_use(_FakeTool(), {"text": "x"}, AgentContext())  # type: ignore[arg-type]
    assert result.decision == PermissionDecision.DENY
    assert "did not respond" in result.reason


@pytest.mark.asyncio
async def test_resolve_unknown_request_id_silent() -> None:
    """timeout 後到達的 decision / 重複 / unknown id 不該炸。"""
    pending = PendingPermissions()
    pending.resolve("nonexistent", "allow")  # 不 raise
    # 已 done 的 future 也是 silent
    loop = asyncio.get_running_loop()
    fut: asyncio.Future[str] = loop.create_future()
    fut.set_result("already")
    pending.pending["x"] = fut
    pending.resolve("x", "deny")  # 不 raise(future 已 done)

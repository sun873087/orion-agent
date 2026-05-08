"""MessageBus — pub/sub。Phase 15。"""

from __future__ import annotations

import pytest

from orion_agent.multi_agent.message_bus import MessageBus
from orion_agent.multi_agent.types import PeerMessage


@pytest.mark.asyncio
async def test_send_unicast() -> None:
    bus = MessageBus()
    sub_b = bus.subscribe("b")
    sent = bus.send(PeerMessage(from_agent="a", to_agent="b", content="hi"))
    assert sent is True
    msg = await sub_b.receive()
    assert msg.content == "hi"
    assert msg.from_agent == "a"
    await bus.close()


@pytest.mark.asyncio
async def test_send_to_unknown_returns_false() -> None:
    bus = MessageBus()
    bus.subscribe("b")
    sent = bus.send(PeerMessage(from_agent="a", to_agent="ghost", content="?"))
    assert sent is False
    await bus.close()


@pytest.mark.asyncio
async def test_send_without_to_agent_returns_false() -> None:
    bus = MessageBus()
    sent = bus.send(PeerMessage(from_agent="a", content="?"))  # no to_agent
    assert sent is False
    await bus.close()


@pytest.mark.asyncio
async def test_broadcast_excludes_sender() -> None:
    bus = MessageBus()
    sub_a = bus.subscribe("a")
    sub_b = bus.subscribe("b")
    sub_c = bus.subscribe("c")
    delivered = bus.broadcast(PeerMessage(from_agent="a", content="hello"))
    assert delivered == 2
    msg_b = await sub_b.receive()
    msg_c = await sub_c.receive()
    assert msg_b.content == "hello"
    assert msg_c.content == "hello"
    # sender 不收
    sub_a_done = False
    try:
        async with __import__("anyio").move_on_after(0.05):
            await sub_a.receive()
            sub_a_done = True
    except Exception:  # noqa: BLE001
        sub_a_done = False
    assert not sub_a_done
    await bus.close()


@pytest.mark.asyncio
async def test_duplicate_subscribe_raises() -> None:
    bus = MessageBus()
    bus.subscribe("a")
    with pytest.raises(ValueError, match="already subscribed"):
        bus.subscribe("a")
    await bus.close()


@pytest.mark.asyncio
async def test_subscribe_after_close_raises() -> None:
    bus = MessageBus()
    await bus.close()
    with pytest.raises(RuntimeError, match="closed"):
        bus.subscribe("a")


@pytest.mark.asyncio
async def test_close_terminates_subscribers() -> None:
    bus = MessageBus()
    sub = bus.subscribe("a")
    await bus.close()
    # async for 應該結束
    received: list[PeerMessage] = []
    async for m in sub:
        received.append(m)
    assert received == []


@pytest.mark.asyncio
async def test_full_queue_drops_message() -> None:
    bus = MessageBus(buffer_size=2)
    bus.subscribe("a")
    # 不消費,塞滿 + 多 1 → 第 3 個被丟
    ok1 = bus.send(PeerMessage(from_agent="x", to_agent="a", content="1"))
    ok2 = bus.send(PeerMessage(from_agent="x", to_agent="a", content="2"))
    ok3 = bus.send(PeerMessage(from_agent="x", to_agent="a", content="3"))
    assert ok1 and ok2
    assert ok3 is False
    await bus.close()


@pytest.mark.asyncio
async def test_agents_property_lists_subscribers() -> None:
    bus = MessageBus()
    bus.subscribe("alice")
    bus.subscribe("bob")
    assert bus.agents == ["alice", "bob"]
    await bus.close()

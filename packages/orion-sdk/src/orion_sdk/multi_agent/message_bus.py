"""In-process MessageBus。

對應 TS Claude Code `src/utils/swarm/inProcessRunner.ts` 的訊息傳遞層。

設計:
- 純 in-process(`anyio.create_memory_object_stream`),延遲 < 1ms
- `subscribe(name)` 回 `MemoryObjectReceiveStream`(支援 `async for` 與
  `await stream.receive()` + `move_on_after` idle timeout)
- `send(msg)` 單播到 `msg.to_agent`
- `broadcast(msg)` 廣播給所有 agent(排除 sender)
- queue 滿(預設 buffer 100)→ 丟新訊息(spec § 9 踩雷 #2)
- `close()` 關所有 stream,subscribers 的 async for / receive() 退出

跨 process(K8s 多 pod swarm)需要 Redis pub/sub backend — 留新 phase plan。
"""

from __future__ import annotations

import logging

import anyio
from anyio.streams.memory import (
    MemoryObjectReceiveStream,
    MemoryObjectSendStream,
)

from orion_sdk.multi_agent.types import PeerMessage

logger = logging.getLogger(__name__)

_DEFAULT_BUFFER = 100


class MessageBus:
    """單 process 內 agent 間訊息匯流排。"""

    def __init__(self, buffer_size: int = _DEFAULT_BUFFER) -> None:
        self._buffer_size = buffer_size
        self._send: dict[str, MemoryObjectSendStream[PeerMessage]] = {}
        self._recv: dict[str, MemoryObjectReceiveStream[PeerMessage]] = {}
        self._closed = False

    @property
    def agents(self) -> list[str]:
        return sorted(self._send.keys())

    def subscribe(
        self, agent_name: str,
    ) -> MemoryObjectReceiveStream[PeerMessage]:
        """註冊 agent 為訊息收件者。

        Returns:
            `MemoryObjectReceiveStream` — caller 可以:
            - `async for msg in stream:` (bus.close() 時自動結束)
            - `await stream.receive()`(可配 anyio.move_on_after 做 idle timeout)
        """
        if self._closed:
            raise RuntimeError("MessageBus is closed")
        if agent_name in self._send:
            raise ValueError(f"agent {agent_name!r} already subscribed")
        send, recv = anyio.create_memory_object_stream[PeerMessage](
            max_buffer_size=self._buffer_size,
        )
        self._send[agent_name] = send
        self._recv[agent_name] = recv
        return recv

    def send(self, message: PeerMessage) -> bool:
        """單播到 `message.to_agent`。queue 滿 / 對方不存在 → 丟訊息回 False。"""
        if self._closed:
            return False
        target = message.to_agent
        if target is None:
            logger.warning("send() called with to_agent=None — use broadcast()")
            return False
        send = self._send.get(target)
        if send is None:
            logger.debug("send to %s: no subscriber", target)
            return False
        try:
            send.send_nowait(message)
            return True
        except anyio.WouldBlock:
            logger.warning("queue full for %s — dropping message", target)
            return False

    def broadcast(self, message: PeerMessage) -> int:
        """廣播給所有 agent(**排除 sender**)。回投遞成功的 agent 數。"""
        if self._closed:
            return 0
        delivered = 0
        for name, send in self._send.items():
            if name == message.from_agent:
                continue
            try:
                send.send_nowait(message)
                delivered += 1
            except anyio.WouldBlock:
                logger.warning(
                    "queue full for %s during broadcast — dropping", name,
                )
        return delivered

    async def close(self) -> None:
        """關所有 stream,所有 subscribers 的 async for 退出。"""
        if self._closed:
            return
        self._closed = True
        for send in self._send.values():
            await send.aclose()
        # recv 由 _iter 的 async with 自己關
        self._send.clear()


__all__ = ["MessageBus"]

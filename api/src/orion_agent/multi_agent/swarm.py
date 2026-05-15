"""SwarmRunner(peer-to-peer)pattern。Phase 15。

對應 TS Claude Code `src/utils/swarm/`。

語意:
  N 個對等 SwarmAgent 並行跑;每 agent 透過 LLMProvider.stream 跑單輪推理,
  在文字回應中用 `@<agent_name>: <message>` 格式 mention 其他 agent → MessageBus
  路由 → 對方下一輪收到。沒 leader 模式 default 跑 max_rounds 後結束;若指定
  `leader`,leader 在自己回應中寫 `STOP_SWARM` 即立即結束整個 swarm。

不用 forked_agent:每 agent 有獨立 system_prompt,prompt cache 無法共享;改直接
用 provider.stream + 累積 NormalizedMessage history(每 agent 自己的 mini
conversation)。
"""

from __future__ import annotations

import logging
import re
from dataclasses import dataclass, field
from datetime import UTC, datetime

import anyio
from anyio.streams.memory import MemoryObjectReceiveStream

from orion_model.events import (
    MessageStopEvent,
    TextDeltaEvent,
)
from orion_model.provider import LLMProvider
from orion_model.types import NormalizedMessage
from orion_agent.multi_agent.message_bus import MessageBus
from orion_agent.multi_agent.types import PeerMessage

logger = logging.getLogger(__name__)

_MENTION_RE = re.compile(r"@(\w[\w\-]*)\s*:\s*(.+?)(?=(?:\s*@\w[\w\-]*\s*:)|\Z)", re.DOTALL)
"""`@name: msg` parser — 支援 hyphen,內容延伸到下個 @mention 或結尾。"""

_STOP_TOKEN = "STOP_SWARM"


@dataclass(frozen=True)
class SwarmAgent:
    """單一 swarm peer 的 spec。"""

    name: str
    """agent 名稱(`@<name>` mention 用,要可作 word \\w+ 的識別子)。"""

    role: str
    """e.g. "security-reviewer" / "perf-analyzer" / "ux-critic"。"""

    system_prompt: str
    """整段 system prompt(本 phase 不繼承父 prompt)。"""

    initial_prompt: str
    """第一輪要說的話。空字串 → 該 agent 等別人 mention 才動作。"""


@dataclass
class SwarmConfig:
    agents: list[SwarmAgent]
    max_rounds: int = 5
    """每 agent 最多跑 N 輪後強制結束(全 agent 共用上限)。"""

    leader: str | None = None
    """指定 leader 名稱(若有),leader 寫 STOP_SWARM 立即結束整 swarm。"""

    max_tokens_per_turn: int = 1024
    buffer_size: int = 100

    idle_timeout_s: float = 1.0
    """單一 agent 連續 N 秒沒收新訊息 → 該 agent 收工(spec § 9 踩雷 #3)。
    避免兩 agent 互相等對方先講而死鎖。"""


@dataclass
class SwarmAgentLog:
    """單一 agent 的回合紀錄。"""

    name: str
    messages: list[NormalizedMessage] = field(default_factory=list)
    """完整對話歷史(含 system / 收到的 / 自己回的)。"""

    sent_messages: list[PeerMessage] = field(default_factory=list)
    """主動丟到 bus 的訊息(送出歷史)。"""


@dataclass
class SwarmResult:
    logs: dict[str, SwarmAgentLog]
    """agent_name → SwarmAgentLog。"""

    rounds_run: dict[str, int] = field(default_factory=dict)
    """agent_name → 實際跑的 round 數。"""

    stopped_by_leader: bool = False


class SwarmRunner:
    """跑 N 對等 agent 的 swarm。

    用法:
        runner = SwarmRunner(config=SwarmConfig(agents=[...]), provider=p)
        result = await runner.run()
    """

    def __init__(
        self,
        *,
        config: SwarmConfig,
        provider: LLMProvider,
    ) -> None:
        if not config.agents:
            raise ValueError("SwarmConfig.agents must not be empty")
        names = [a.name for a in config.agents]
        if len(set(names)) != len(names):
            raise ValueError("SwarmConfig.agents have duplicate names")
        if config.leader is not None and config.leader not in names:
            raise ValueError(
                f"leader {config.leader!r} not in agents {names}"
            )
        self.config = config
        self.provider = provider
        self.bus = MessageBus(buffer_size=config.buffer_size)
        self._stop_event = anyio.Event()
        self._logs: dict[str, SwarmAgentLog] = {
            a.name: SwarmAgentLog(name=a.name) for a in config.agents
        }
        self._rounds: dict[str, int] = {a.name: 0 for a in config.agents}
        self._stopped_by_leader = False
        # 進 _run_one 一次 +1,離開 -1;歸 0 → close bus 讓其他人 async for 退出
        self._active = len(config.agents)
        self._active_lock = anyio.Lock()
        # 預先 subscribe 全部 agent(避免 leader 先 close bus 導致 worker 沒得 subscribe)
        self._subscriptions: dict[
            str, MemoryObjectReceiveStream[PeerMessage]
        ] = {}

    async def run(self) -> SwarmResult:
        # 預先 subscribe 全部 agent — 避免 task scheduling 不確定性導致
        # leader 先跑完 close bus,其他 worker 才嘗試 subscribe
        for agent in self.config.agents:
            self._subscriptions[agent.name] = self.bus.subscribe(agent.name)
        try:
            async with anyio.create_task_group() as tg:
                for agent in self.config.agents:
                    tg.start_soon(self._run_one, agent)
        finally:
            await self.bus.close()
        return SwarmResult(
            logs=self._logs,
            rounds_run=dict(self._rounds),
            stopped_by_leader=self._stopped_by_leader,
        )

    async def _run_one(self, agent: SwarmAgent) -> None:
        subscription = self._subscriptions[agent.name]
        log = self._logs[agent.name]
        try:
            # 第一輪:initial_prompt(若非空)
            if agent.initial_prompt.strip():
                await self._do_turn(
                    agent, incoming_text=agent.initial_prompt, sender=None,
                )
                if self._rounds[agent.name] >= self.config.max_rounds:
                    return
                if self._stop_event.is_set():
                    return

            # 後續輪:用 idle timeout 防死鎖(spec § 9 踩雷 #3)
            while True:
                if self._stop_event.is_set():
                    break
                if self._rounds[agent.name] >= self.config.max_rounds:
                    break

                peer_msg: PeerMessage | None = None
                with anyio.move_on_after(
                    self.config.idle_timeout_s,
                ) as scope:
                    try:
                        peer_msg = await subscription.receive()
                    except (anyio.EndOfStream, anyio.ClosedResourceError):
                        # bus.close() 已關 stream → 該 agent 退出
                        return
                if scope.cancelled_caught or peer_msg is None:
                    # idle timeout → 該 agent 沒事可做了,收工
                    return

                await self._do_turn(
                    agent,
                    incoming_text=peer_msg.content,
                    sender=peer_msg.from_agent,
                )
        finally:
            # 一個 agent 退出 → 遞減 active counter;最後一個離開時 close bus
            await self._finish_agent()
            _ = log  # for typing

    async def _finish_agent(self) -> None:
        """每個 _run_one 結束都呼一次。歸 0 時 close bus(讓其他 agent 的
        async for subscription 退出)。"""
        async with self._active_lock:
            self._active -= 1
            should_close = self._active == 0
        if should_close:
            await self.bus.close()

    async def _do_turn(
        self,
        agent: SwarmAgent,
        *,
        incoming_text: str,
        sender: str | None,
    ) -> None:
        """跑 agent 一輪推理:送 LLM、累積 history、parse @mention 派發。"""
        log = self._logs[agent.name]

        if sender is not None:
            user_text = f"[message from @{sender}] {incoming_text}"
        else:
            user_text = incoming_text

        user_msg = NormalizedMessage(role="user", content=user_text)
        log.messages.append(user_msg)

        # 跑 LLM(用 provider.stream + agent.system_prompt + 累積 history)
        chunks: list[str] = []
        try:
            async for ev in self.provider.stream(
                system=agent.system_prompt,
                messages=log.messages,
                tools=None,
                max_tokens=self.config.max_tokens_per_turn,
            ):
                if isinstance(ev, TextDeltaEvent):
                    chunks.append(ev.text)
                elif isinstance(ev, MessageStopEvent):
                    break
        except Exception as e:  # noqa: BLE001 — 單 agent 失敗不該拖垮整個 swarm
            logger.warning(
                "swarm agent %s turn failed: %s", agent.name, e,
            )
            return

        text = "".join(chunks).strip()
        if not text:
            return

        log.messages.append(
            NormalizedMessage(role="assistant", content=text),
        )
        self._rounds[agent.name] += 1

        # leader 寫 STOP_SWARM → 立即結束
        if (
            self.config.leader == agent.name
            and _STOP_TOKEN in text
        ):
            self._stopped_by_leader = True
            self._stop_event.set()
            await self.bus.close()
            return

        # parse @mention 派發
        self._dispatch_mentions(agent.name, text, log)

    def _dispatch_mentions(
        self, sender: str, text: str, log: SwarmAgentLog,
    ) -> None:
        """把 `@name: msg` 碎片轉 PeerMessage 投遞 bus。"""
        agent_names = {a.name for a in self.config.agents}
        for match in _MENTION_RE.finditer(text):
            target = match.group(1)
            content = match.group(2).strip()
            if not content:
                continue
            if target not in agent_names:
                continue
            if target == sender:
                continue  # 不對自己 @

            msg = PeerMessage(
                from_agent=sender,
                to_agent=target,
                content=content,
                timestamp=datetime.now(UTC),
            )
            ok = self.bus.send(msg)
            if ok:
                log.sent_messages.append(msg)


__all__ = ["SwarmAgent", "SwarmConfig", "SwarmResult", "SwarmRunner"]

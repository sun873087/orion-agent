# Phase 15:Multi-Agent Patterns(多 agent 進階模式)

## 速覽

- **預計時程**:1-2 週
- **前置 Phase**:Phase 1(AgentTool)、Phase 9(sub-agent isolation)、Phase 12(forkedAgent)
- **本文件目的**:從「父子 agent」進階到「多 agent 協作」三種 pattern
- **主要交付物**:
  - **Coordinator mode**(Leader-Worker:1 個父 agent 編排 N 個子 worker)
  - **Swarm mode**(Peer:N 個對等 agent 互相通訊解任務)
  - **AgentSummary**(Agent 完成後給人類看的摘要)

## 1. 為何需要本 phase?

Phase 1 / 9 / 12 已經有「父 agent spawn 子 agent」(`AgentTool` + forkedAgent),但只是**單一父子關係**:

```
Phase 1-12 的 sub-agent:
   Parent ─▶ Spawn child ─▶ child 跑完 ─▶ Parent 拿結果

對複雜任務不夠:
   - 需要多個專家並行(security review + perf review + UX review)
   - 需要 leader-worker 動態分派任務
   - 需要 peer 之間溝通(swarm)
```

**對應 TS 源碼**:
- `src/coordinator/coordinatorMode.ts`(369 行)
- `src/utils/swarm/`(目錄,含 backends/、inProcessRunner、leaderPermissionBridge 等)
- `src/services/AgentSummary/agentSummary.ts`(179 行)

## 2. 三種多 agent pattern 對照

```
┌─────────────────────────────────────────────────────────────┐
│  Pattern 1:Sub-agent(Phase 1 / 9 已有)                     │
├─────────────────────────────────────────────────────────────┤
│  Parent ──fork──▶ Child                                     │
│  Parent 等 child 完成,拿結果繼續                            │
│  特性:同步、單向、父子                                      │
│  適合:Explore / Code Review / Plan 等線性任務              │
└─────────────────────────────────────────────────────────────┘

┌─────────────────────────────────────────────────────────────┐
│  Pattern 2:Coordinator(Phase 15 新)                        │
├─────────────────────────────────────────────────────────────┤
│  Coordinator ──分派──▶ Worker A                             │
│       │      ──分派──▶ Worker B                             │
│       │      ──分派──▶ Worker C                             │
│       │←──結果──┴──結果──┴──結果──                          │
│       ↓                                                     │
│  Coordinator 整合 + 決定下一步                              │
│  特性:1 對 N、動態、coordinator 是 brain                   │
│  適合:多面向 review、跨領域分析、N 個並行 sub-task         │
└─────────────────────────────────────────────────────────────┘

┌─────────────────────────────────────────────────────────────┐
│  Pattern 3:Swarm(Phase 15 新)                             │
├─────────────────────────────────────────────────────────────┤
│  Agent A ◀──訊息──▶ Agent B                                │
│      ▲              ▲                                       │
│      │              │                                       │
│      ▼              ▼                                       │
│  Agent C ◀──訊息──▶ Agent D                                │
│  特性:N 對 N、peer、可能有 leader 但平等                  │
│  適合:辯論 / 模擬 / 大規模任務分散                         │
└─────────────────────────────────────────────────────────────┘
```

## 3. TS 源檔映射

| Python 模組 | 對應 TS 源檔 | 行數 | 注意 |
|---|---|---|---|
| `src/multi_agent/coordinator.py` | `src/coordinator/coordinatorMode.ts` | 369 | leader-worker |
| `src/multi_agent/swarm.py` | `src/utils/swarm/inProcessRunner.ts` 等 | — | peer-to-peer |
| `src/multi_agent/permission_bridge.py` | `src/utils/swarm/leaderPermissionBridge.ts` | — | swarm 共用權限 |
| `src/multi_agent/agent_summary.py` | `src/services/AgentSummary/agentSummary.ts` | 179 | 完成後摘要 |
| `src/tools/team/*` | `src/tools/TeamCreateTool/`、`TeamDeleteTool/` | — | Phase 10 已列,本 phase 補實作 |

## 3. 任務拆解

### Week 1:Coordinator + AgentSummary

- [ ] 1.1 `multi_agent/coordinator.py`:`Coordinator` class
- [ ] 1.2 訊息協議:`TaskAssignment` / `WorkerReport` / `WorkerStatus` Pydantic
- [ ] 1.3 並行 spawn workers + 結果聚合
- [ ] 1.4 `multi_agent/agent_summary.py`:`generate_agent_summary`(用 sideQuery 摘要 worker 完成的工作)
- [ ] 1.5 整合到 Phase 1 AgentTool:`subagent_type == "coordinator"` 走 coordinator
- [ ] 1.6 測試:1 coordinator + 3 workers、worker 失敗、coordinator 重新分派

### Week 2:Swarm + permission bridge

- [ ] 2.1 `multi_agent/swarm.py`:`SwarmRunner` class
- [ ] 2.2 訊息匯流排(in-process queue 開始,跨 process 用 Redis pub/sub)
- [ ] 2.3 `permission_bridge.py`:swarm 內 agent 共用權限決策(避免每個 agent 重複問)
- [ ] 2.4 整合 SendMessageTool / TeamCreateTool / TeamDeleteTool
- [ ] 2.5 測試 + 心得

## 4. 模組架構

```
src/claude_agent_py/
├── multi_agent/
│   ├── __init__.py
│   ├── types.py                       # ◀ NEW 訊息協議
│   ├── coordinator.py                 # ◀ NEW Leader-worker
│   ├── swarm.py                       # ◀ NEW Peer-to-peer
│   ├── permission_bridge.py           # ◀ NEW 共用權限決策
│   ├── agent_summary.py               # ◀ NEW 完成摘要
│   └── message_bus.py                 # ◀ NEW agent 間訊息
│
└── tools/
    ├── team/                          # 改造 Phase 10 stub
    │   ├── team_create.py             # 改用 multi_agent 機制
    │   └── team_delete.py
    └── messaging/
        └── send_message.py            # 改造為 multi-agent 互通
```

## 5. Python Skeleton

### 5.1 `multi_agent/types.py`

```python
"""多 agent 訊息協議。"""
from __future__ import annotations
from datetime import datetime
from typing import Any, Literal
from uuid import UUID, uuid4
from pydantic import BaseModel, Field


AgentRole = Literal["coordinator", "worker", "peer"]
"""coordinator = leader,分派任務;worker = 跑單一 task;peer = 對等"""


class TaskAssignment(BaseModel):
    """Coordinator → Worker 的任務分派。"""
    task_id: UUID = Field(default_factory=uuid4)
    description: str
    """task 描述(自然語言,worker 直接 work on it)。"""
    context: dict = Field(default_factory=dict)
    """額外脈絡(parent 任務、相關檔案 ref 等)。"""
    deadline_seconds: int | None = None
    expected_format: str | None = None
    """期望結果格式(如 "JSON" / "markdown report")。"""


class WorkerReport(BaseModel):
    """Worker → Coordinator 的進度 / 結果。"""
    task_id: UUID
    worker_id: str
    status: Literal["in_progress", "completed", "failed"]
    progress: float = 0.0  # 0.0 ~ 1.0
    result: Any | None = None
    error: str | None = None
    summary: str | None = None
    """工作摘要(由 AgentSummary 產生)。"""


class PeerMessage(BaseModel):
    """Swarm peer 間訊息。"""
    message_id: UUID = Field(default_factory=uuid4)
    from_agent: str
    to_agent: str | None = None  # None = broadcast
    timestamp: datetime = Field(default_factory=datetime.utcnow)
    content: str
    metadata: dict = Field(default_factory=dict)
```

### 5.2 `multi_agent/coordinator.py`

```python
"""Coordinator(Leader-Worker)mode。對應 TS coordinator/coordinatorMode.ts。"""
from __future__ import annotations
import anyio
from typing import AsyncIterator
from uuid import UUID

from claude_agent_py.core.state import AgentContext
from claude_agent_py.multi_agent.types import TaskAssignment, WorkerReport
from claude_agent_py.utils.forked_agent import (
    CacheSafeParams, run_forked_agent,
)


class Coordinator:
    """Leader agent。一個 coordinator,N 個 worker。

    流程:
      1. Coordinator 接到使用者請求
      2. 拆解成 N 個 TaskAssignment
      3. 並行 spawn N workers(用 forkedAgent)
      4. 收集 WorkerReport
      5. 整合 / 決定下一步(再分派 / 結束)
    """

    def __init__(
        self,
        ctx: AgentContext,
        cache_safe_params: CacheSafeParams,
        max_workers: int = 5,
    ):
        self.ctx = ctx
        self.cache_safe_params = cache_safe_params
        self.max_workers = max_workers
        self.reports: list[WorkerReport] = []

    async def dispatch(
        self,
        assignments: list[TaskAssignment],
    ) -> list[WorkerReport]:
        """並行跑 assignments,等所有 worker 完成。"""
        if len(assignments) > self.max_workers:
            raise ValueError(f"Too many assignments: {len(assignments)} > {self.max_workers}")

        results: list[WorkerReport] = []
        limiter = anyio.CapacityLimiter(self.max_workers)

        async def run_worker(assignment: TaskAssignment) -> WorkerReport:
            async with limiter:
                try:
                    # 用 forkedAgent 跑 worker(共享父 prompt cache)
                    fork_result = await run_forked_agent(
                        parent=self.cache_safe_params,
                        user_prompt=self._format_worker_prompt(assignment),
                        can_use_tool=self._make_worker_can_use_tool(),
                        fork_label=f"worker-{assignment.task_id}",
                        max_turns=10,
                        skip_transcript=True,
                        parent_ctx=self.ctx,
                    )
                    summary = self._extract_summary(fork_result.messages)
                    result = self._extract_result(fork_result.messages)
                    return WorkerReport(
                        task_id=assignment.task_id,
                        worker_id=f"worker-{assignment.task_id}",
                        status="completed",
                        progress=1.0,
                        result=result,
                        summary=summary,
                    )
                except Exception as e:
                    return WorkerReport(
                        task_id=assignment.task_id,
                        worker_id=f"worker-{assignment.task_id}",
                        status="failed",
                        error=str(e),
                    )

        # 並行
        async with anyio.create_task_group() as tg:
            results_holder = [None] * len(assignments)
            async def store(i, assignment):
                results_holder[i] = await run_worker(assignment)
            for i, a in enumerate(assignments):
                tg.start_soon(store, i, a)

        return [r for r in results_holder if r is not None]

    def _format_worker_prompt(self, assignment: TaskAssignment) -> str:
        return (
            f"You are a worker agent assigned a sub-task by a coordinator.\n\n"
            f"Task: {assignment.description}\n\n"
            f"Context: {assignment.context}\n\n"
            f"Expected output format: {assignment.expected_format or 'free-form'}\n\n"
            f"Complete the task and provide a concise summary."
        )

    def _make_worker_can_use_tool(self):
        """Worker 用 read-only + 限定工具(避免 worker 互踩)。"""
        from claude_agent_py.permissions.decisions import always_allow
        # 細節:可定義 worker 專用 policy
        return always_allow()

    def _extract_summary(self, messages) -> str:
        """從 worker yield 的訊息抽 summary(最後 assistant 訊息)。"""
        for m in reversed(messages):
            if m.role == "assistant" and isinstance(m.content, str):
                return m.content[:500]
        return ""

    def _extract_result(self, messages) -> dict:
        """從 worker 訊息抽結構化結果(若 worker 用 SyntheticOutputTool)。"""
        for m in reversed(messages):
            if not isinstance(m.content, list):
                continue
            for block in m.content:
                if block.get("type") == "tool_use" and block.get("name") == "StructuredOutput":
                    return block.get("input", {})
        return {}


# 整合到 AgentTool:
# 當 subagent_type == "coordinator" 時走 Coordinator.dispatch
```

### 5.3 `multi_agent/swarm.py`

```python
"""Swarm(peer-to-peer)mode。對應 TS utils/swarm/。

N 個對等 agent,可互相通訊。簡化版:in-process message bus。
"""
from __future__ import annotations
import anyio
from dataclasses import dataclass, field
from typing import AsyncIterator
from uuid import UUID, uuid4

from claude_agent_py.core.state import AgentContext
from claude_agent_py.multi_agent.types import PeerMessage
from claude_agent_py.multi_agent.message_bus import MessageBus


@dataclass
class SwarmAgent:
    name: str
    role: str
    """e.g. "security-reviewer" / "perf-analyzer" / "ux-critic"。"""
    system_prompt: str
    initial_prompt: str


@dataclass
class SwarmConfig:
    agents: list[SwarmAgent]
    max_rounds: int = 10
    """所有 agent 各跑 N 輪後強制結束。"""

    leader: str | None = None
    """指定 leader 名稱(若有),leader 決定何時結束。"""


class SwarmRunner:
    def __init__(self, config: SwarmConfig, parent_ctx: AgentContext):
        self.config = config
        self.parent_ctx = parent_ctx
        self.bus = MessageBus()
        self.results: dict[str, list[str]] = {}  # agent_name → messages
        self._agent_tasks: dict[str, anyio.abc.TaskStatus] = {}

    async def run(self) -> dict[str, list[str]]:
        """跑 swarm,return 每個 agent 的訊息列表。"""
        async with anyio.create_task_group() as tg:
            for agent in self.config.agents:
                tg.start_soon(self._run_one_agent, agent)

        return self.results

    async def _run_one_agent(self, agent: SwarmAgent) -> None:
        """跑單一 agent 的 loop(讀 bus / 推理 / 送 bus)。"""
        # 訂閱訊息
        subscription = self.bus.subscribe(agent.name)
        self.results[agent.name] = []

        # 初始 prompt
        await self._agent_turn(agent, agent.initial_prompt)

        rounds = 0
        async for msg in subscription:
            if rounds >= self.config.max_rounds:
                break
            await self._agent_turn(agent, msg.content, sender=msg.from_agent)
            rounds += 1

            # leader 決定結束
            if self.config.leader == agent.name:
                if "STOP_SWARM" in self.results[agent.name][-1]:
                    self.bus.broadcast(PeerMessage(
                        from_agent=agent.name,
                        content="__swarm_stop__",
                    ))
                    break

    async def _agent_turn(
        self,
        agent: SwarmAgent,
        prompt: str,
        sender: str | None = None,
    ) -> None:
        """跑 agent 一輪推理。可呼叫工具 / 送訊息給其他 agent。"""
        # 簡化版:直接呼叫 anthropic API,不走完整 query_loop
        # 完整版要走 forkedAgent 或專用 conversation
        from claude_agent_py.utils.side_query import side_query, SideQueryParams

        full_prompt = (
            f"[Message from {sender}]: {prompt}\n\n"
            f"You are {agent.name} ({agent.role}). Respond concisely.\n"
            f"To send to another agent, use format: @<agent_name>: <message>"
        ) if sender else prompt

        result = await side_query(SideQueryParams(
            model="claude-sonnet-4-6",
            system=agent.system_prompt,
            messages=[{"role": "user", "content": full_prompt}],
            max_tokens=1024,
        ))

        # 解析回應 + 送訊息
        for block in result.content:
            if block.type == "text":
                self.results[agent.name].append(block.text)
                # parse @<agent>: 訊息
                self._parse_and_send(agent.name, block.text)

    def _parse_and_send(self, from_agent: str, text: str) -> None:
        """從文字抽 @<agent>: 訊息,丟到 bus。"""
        import re
        for match in re.finditer(r"@(\w+):\s*(.+)", text):
            target = match.group(1)
            content = match.group(2).strip()
            if target in {a.name for a in self.config.agents}:
                self.bus.send(PeerMessage(
                    from_agent=from_agent,
                    to_agent=target,
                    content=content,
                ))
```

### 5.4 `multi_agent/message_bus.py`

```python
"""Agent 間訊息匯流排。"""
from __future__ import annotations
import anyio
from typing import AsyncIterator
from collections import defaultdict

from claude_agent_py.multi_agent.types import PeerMessage


class MessageBus:
    """In-process queue。production 跨 process 用 Redis pub/sub。"""

    def __init__(self):
        self._queues: dict[str, anyio.streams.memory.MemoryObjectSendStream] = {}
        self._receive_streams: dict[str, anyio.streams.memory.MemoryObjectReceiveStream] = {}

    def subscribe(self, agent_name: str) -> AsyncIterator[PeerMessage]:
        send, recv = anyio.create_memory_object_stream(max_buffer_size=100)
        self._queues[agent_name] = send
        self._receive_streams[agent_name] = recv
        return self._iter_messages(recv)

    async def _iter_messages(self, recv) -> AsyncIterator[PeerMessage]:
        async with recv:
            async for msg in recv:
                yield msg

    def send(self, message: PeerMessage) -> None:
        """單播。"""
        if message.to_agent and message.to_agent in self._queues:
            try:
                self._queues[message.to_agent].send_nowait(message)
            except anyio.WouldBlock:
                pass  # queue 滿,丟掉

    def broadcast(self, message: PeerMessage) -> None:
        """廣播。"""
        for name, q in self._queues.items():
            if name == message.from_agent:
                continue
            try:
                q.send_nowait(message)
            except anyio.WouldBlock:
                pass
```

### 5.5 `multi_agent/agent_summary.py`

```python
"""AgentSummary — 完成後給人類看的摘要。對應 TS services/AgentSummary/agentSummary.ts。"""
from __future__ import annotations

from claude_agent_py.utils.side_query import side_query, SideQueryParams


SUMMARY_SYSTEM_PROMPT = """You are summarizing the work an agent just completed.

Your summary should be:
- 2-4 sentences
- Focus on what was DONE (not what was tried)
- Mention key files modified or findings discovered
- Suitable for showing to a human user who wasn't present

Format: just the summary text, no preamble."""


async def generate_agent_summary(
    agent_messages: list,
    *,
    agent_name: str = "agent",
) -> str:
    """從 agent 對話訊息產生 2-4 句人類友善摘要。"""
    # 抽 last 10 messages 餵 sideQuery
    last_msgs = agent_messages[-10:]
    transcript = "\n\n".join(
        f"[{m.role}]: {m.content if isinstance(m.content, str) else _format_content(m.content)}"
        for m in last_msgs
    )

    result = await side_query(SideQueryParams(
        model="claude-haiku-4-5",  # 摘要用 Haiku 即可,便宜快
        system=SUMMARY_SYSTEM_PROMPT,
        messages=[{
            "role": "user",
            "content": f"Agent {agent_name} just completed work. Summarize:\n\n{transcript}",
        }],
        max_tokens=256,
        query_source="agent_summary",
    ))

    for block in result.content:
        if block.type == "text":
            return block.text.strip()
    return f"[{agent_name} completed work without summary]"


def _format_content(content) -> str:
    if not isinstance(content, list):
        return str(content)
    parts = []
    for block in content:
        if block.get("type") == "text":
            parts.append(block.get("text", ""))
        elif block.get("type") == "tool_use":
            parts.append(f"[tool: {block.get('name')}({block.get('input')})]")
        elif block.get("type") == "tool_result":
            parts.append(f"[result: {block.get('content', '')[:200]}]")
    return "\n".join(parts)
```

### 5.6 整合到 AgentTool

```python
# tools/agent/agent_tool.py 改造

class AgentToolInput(ToolInput):
    subagent_type: Literal["general", "explore", "plan", "coordinator", "swarm"]
    description: str
    prompt: str
    # 新增:
    sub_tasks: list[dict] | None = None  # coordinator 用
    swarm_agents: list[dict] | None = None  # swarm 用


class AgentTool:
    async def call(self, input, ctx):
        if input.subagent_type == "coordinator":
            yield from self._run_coordinator(input, ctx)
        elif input.subagent_type == "swarm":
            yield from self._run_swarm(input, ctx)
        else:
            # 原 sub-agent 邏輯(Phase 1)
            yield from self._run_subagent(input, ctx)

    async def _run_coordinator(self, input, ctx):
        from claude_agent_py.multi_agent.coordinator import Coordinator
        from claude_agent_py.multi_agent.types import TaskAssignment
        from claude_agent_py.utils.forked_agent import CacheSafeParams

        assignments = [
            TaskAssignment(**t) for t in (input.sub_tasks or [])
        ]
        coordinator = Coordinator(
            ctx=ctx,
            cache_safe_params=CacheSafeParams.from_parent(...),
        )
        reports = await coordinator.dispatch(assignments)

        # 整合 worker 結果
        summary = "\n\n".join(
            f"### {r.worker_id}\n{r.summary}\nResult: {r.result}"
            for r in reports
        )
        yield TextEvent(text=f"Coordinator complete:\n\n{summary}")
```

## 6. 設計決策

### 為何 Coordinator 用 forkedAgent 而非新 Conversation?

forkedAgent 共享父 prompt cache → 大幅省 token。N 個 workers 各自全新 Conversation 會 N 倍 token 成本。

對應 TS coordinator 的設計也是這樣。

### 為何 Swarm message bus 用 in-process queue?

Phase 15 簡化:
- 同 process 內訊息傳遞,延遲 < 1ms
- 不需要 Redis(若 swarm 都在同 worker)

production 跨 process(load balancer 把 swarm agent 分到不同 K8s pod)需要 Redis pub/sub:

```python
class RedisMessageBus(MessageBus):
    """跨 process 訊息。用 Redis pub/sub。"""
    ...
```

留給後續(若需要)。

### 為何 swarm 訊息協議用 `@<agent>: msg`?

對應 TS swarm 設計。模型熟悉 Twitter/Slack mention 格式,prompt 寫起來容易:

```
You can mention other agents like @security-reviewer: please check this for SQL injection.
```

替代:用結構化 tool(SendMessageTool)。但每次發訊息都要 tool_use → 笨拙。`@mention` 是寫在自然語言內,模型寫完一段話自然 mention 即可。

### 為何 AgentSummary 用 Haiku?

摘要是固定 pattern 任務(2-4 句、focus DONE、提及關鍵檔)。Haiku 處理足夠,Sonnet 過度殺雞。**省成本 5x**。

對應 TS AgentSummary 也是用 Haiku。

### Phase 15 故意不做的

| 項目 | 理由 |
|---|---|
| 完整 Actor model 框架 | scope 外,Python 有 [Pykka](https://pykka.readthedocs.io/) 可用 |
| 跨 K8s pod swarm | 需要 Redis 後,Phase 15 簡化版只 in-process |
| 動態 agent spawn(swarm 中途加 agent)| 預先 declare 即可,動態增加複雜度高 |
| Voting / consensus 機制 | 應用層 logic,不在框架內 |

## 7. 驗收標準

```bash
pytest tests/multi_agent/ -v
```

關鍵測試:

- `test_coordinator_parallel.py`:3 workers 並行跑,結果按 task_id 對應
- `test_coordinator_failure.py`:1 worker 失敗 → reports 含 status=failed,coordinator 仍能整合其他成功 workers
- `test_swarm_two_agents.py`:agent A 發訊息 → agent B 收到 → B 回 → A 收到
- `test_swarm_max_rounds.py`:超過 max_rounds 自動結束
- `test_agent_summary.py`:從訊息列表產生 2-4 句摘要

### 手動驗證

#### Coordinator

```bash
> "Use coordinator to review this PR from 3 angles: security, perf, UX"

# 模型 yield AgentTool({
#   subagent_type: "coordinator",
#   sub_tasks: [
#     {description: "Security review", expected_format: "checklist"},
#     {description: "Perf review", ...},
#     {description: "UX review", ...},
#   ]
# })
# 並行 spawn 3 workers,各自 review,結果聚合
```

#### Swarm

```bash
> "Run a swarm to debate the architecture decision: REST vs GraphQL"

# spawn 3 peer agents:
#   - rest-advocate
#   - graphql-advocate
#   - neutral-moderator
# 互相辯論幾輪後 moderator 總結
```

## 8. 常見踩雷

### 踩雷 1:Coordinator 太多 workers cost 爆

`max_workers=5` 但每 worker 跑 10 turn → 50 turn 同步推理。token 與時間成本高。要:

- 強制設 `max_workers <= 5`
- 預估成本前先給 user 看 N workers × M tokens 估值

### 踩雷 2:Swarm 訊息洪流

agent 寫太多 `@mention` → 訊息爆炸。要:

- per-agent 訊息 queue 滿 → 丟舊訊息
- max_rounds 強制結束(防止永動機)
- log warning 給 dev

### 踩雷 3:Swarm 死鎖

Agent A 等 Agent B 回應,B 等 A → 永遠 block。要:

- per-agent timeout(N 秒沒新訊息 → 強制收尾)
- leader-detect deadlock(若有 leader)

### 踩雷 4:Worker 無限 fork(層級遞迴)

Worker 自己又呼叫 AgentTool spawn 子 worker → 無限 fork。要:

- ctx 紀錄 `agent_depth`(層級數)
- 超過 max_depth(預設 3)拒絕 spawn

### 踩雷 5:Swarm 的 prompt cache miss

每個 swarm agent 有自己 system_prompt → 各自 cache。N agents = N cache。**沒有共享優勢**。

如果是 LLM-heavy swarm(辯論 / 模擬),這是接受的成本。對 review-style 用 coordinator(共享父 cache)更省。

### 踩雷 6:Worker token 預算共用 vs 獨立

3 workers 各 10K tokens vs 共用 30K → 設計決策。建議:

- **共用**(從父 token_budget 扣):成本可控,單一 worker 用太多會餓死別人
- **獨立**:fairness,但總成本可能爆

對應 TS 是共用模式。Python port 跟進。

### 踩雷 7:Worker 工具污染父環境

Worker 寫檔 → 影響父 sandbox(Phase 7 同 sandbox)?Phase 9 sub-agent isolation 已解(每個 worker 自己 sandbox)。**confirm 整合進 coordinator**:

```python
async def _run_coordinator(self, input, ctx):
    from claude_agent_py.sandbox.sub_agent_isolation import fork_context_for_subagent

    for assignment in assignments:
        worker_ctx = await fork_context_for_subagent(ctx, pool=...)
        # 每 worker 自己 sandbox
```

## 9. 完成清單

- [ ] `Coordinator` class + 並行 dispatch
- [ ] `SwarmRunner` + MessageBus
- [ ] `AgentSummary`(Haiku 摘要)
- [ ] AgentTool 整合 coordinator / swarm subagent_type
- [ ] Worker isolation(子 sandbox)
- [ ] Token budget 共用機制
- [ ] 寫 Phase 15 心得

完成後可看 [Optional Features 附錄](./OPTIONAL.md)。

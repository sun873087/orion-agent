# Multi-agent

兩種多 agent 模式:Coordinator(leader-worker)跟 Swarm(peer-to-peer)。

**實作位置**:`packages/orion-sdk/src/orion_sdk/multi_agent/`

## Coordinator(leader-worker)

一個主 agent(leader)分派任務給多個 worker,蒐集 result 回傳。

```python
from orion_sdk.multi_agent.coordinator import Coordinator
from orion_sdk.multi_agent.types import TaskAssignment

coord = Coordinator(provider=llm, tools=builtin_tools)
results = await coord.dispatch([
    TaskAssignment(id="t1", agent_role="researcher", prompt="research X"),
    TaskAssignment(id="t2", agent_role="writer",     prompt="draft Y based on t1"),
])
```

Worker 透過 `services/forked_agent.py` spawn — 獨立 `Conversation` instance,共用 `AgentContext.cwd` 但不同 state_messages,結束時 yield `AgentSummary`(`multi_agent/agent_summary.py`)給 coordinator。

## Swarm(peer-to-peer)

無中心,多個 agent 透過 `message_bus.py`(in-memory pub/sub)互送 `PeerMessage`,各自決定回應誰。

```python
from orion_sdk.multi_agent.swarm import Swarm

swarm = Swarm(agents=[agent1, agent2, agent3])
await swarm.run(seed_message="solve task X")
```

Swarm 適合「沒有明確分工」的腦力激盪場景。

## AgentSummary

`agent_summary.py` 用獨立 LLM call 把 sub-agent 整段對話濃縮成 ≤500 字摘要,讓 coordinator / next agent 看得到關鍵結論不用讀完整 transcript。

## Tool: `Agent`

LLM 也能主動 spawn sub-agent:`tools/agent/agent_tool.py` 提供 `Agent(description, prompt, subagent_type)` 工具,內部用 `Coordinator` 模式。

## 限制

- Worker tools 受 main agent permission 限制(no escalation)
- 沒有 cross-machine — 全部 in-process asyncio task
- Cost / token 線性疊加 — N 個 sub-agent = N 倍成本
- Swarm 沒有自動 termination 條件 — 要 caller 設 max_messages / timeout

## 相關

- [tools.md](./tools.md) §Agent — 工具入口
- [`../roadmap/plans/24-multiagent-tools.md`](../roadmap/plans/24-multiagent-tools.md) — 未來 multi-agent 工具規劃

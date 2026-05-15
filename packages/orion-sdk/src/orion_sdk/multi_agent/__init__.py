"""Multi-agent 進階模式 — Phase 15。

對應 TS Claude Code:
- `src/coordinator/coordinatorMode.ts` → `coordinator.py`
- `src/utils/swarm/`(目錄)→ `swarm.py` + `message_bus.py`
- `src/services/AgentSummary/agentSummary.ts` → `agent_summary.py`

三 pattern:
1. **Sub-agent**(Phase 1 / 9 已有):父 → 1 子,線性
2. **Coordinator**(Phase 15):1 父 → N 並行 worker,聚合
3. **Swarm**(Phase 15):N 對等 peer 互傳訊息

本套 API 是 **Python 函式 / class 介面**;Phase 15 沒改 AgentTool input(避免破
壞既有 model contract)。把 multi-agent 暴露給模型(`subagent_type=coordinator/swarm`
+ `CoordinatorTool` / `SwarmTool`)留新 phase plan
`docs/phases/plan/24-multiagent-tools.md`。
"""

from orion_sdk.multi_agent.agent_summary import generate_agent_summary
from orion_sdk.multi_agent.coordinator import (
    Coordinator,
    CoordinatorResult,
)
from orion_sdk.multi_agent.message_bus import MessageBus
from orion_sdk.multi_agent.swarm import (
    SwarmAgent,
    SwarmConfig,
    SwarmResult,
    SwarmRunner,
)
from orion_sdk.multi_agent.types import (
    PeerMessage,
    TaskAssignment,
    WorkerReport,
)

__all__ = [
    "Coordinator",
    "CoordinatorResult",
    "MessageBus",
    "PeerMessage",
    "SwarmAgent",
    "SwarmConfig",
    "SwarmResult",
    "SwarmRunner",
    "TaskAssignment",
    "WorkerReport",
    "generate_agent_summary",
]

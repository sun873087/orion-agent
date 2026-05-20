# Agent loop

對話狀態機 + LLM 事件流 → 工具執行 → 回 LLM。**心臟**。

**實作位置**:`packages/orion-sdk/src/orion_sdk/core/`

```
core/
├── conversation.py        Conversation:對外 send() API + state machine + persist
├── query_loop.py          QueryLoop:provider stream → 高層 NormalizedEvent
├── streaming.py           StreamingExecutor:tool-call 平行執行 + ExecutorPolicy
└── state.py               AgentContext:turn-level mutable state(權限 / plan mode / ...)
```

## 流程

```
user prompt
    │
    ▼
Conversation.send(prompt, ctx=ctx)
    ├─ append user message → state_messages
    ├─ trigger compact if 接近 context 上限
    ├─ inject system prompt(layered:static + session + dynamic)
    ├─ build provider request
    │
    ▼
QueryLoop.run(provider, messages, tools, ctx)
    ├─ provider.stream(messages, tools) → AsyncIterator[ProviderEvent]
    ├─ 累加 text_delta / thinking_delta / tool_use_start
    ├─ message_stop → 拿到完整 assistant message
    │
    ▼
StreamingExecutor.execute(tool_calls)
    ├─ ExecutorPolicy:concurrent vs sequential(per-tool 設定)
    ├─ permission policy:always_allow / ask / DSL match
    ├─ 平行跑 tools(asyncio.gather)
    ├─ append tool_result → state_messages
    │
    ▼
回到 QueryLoop(下一輪 provider stream)— 直到沒 tool_use 或 max_turns
    │
    ▼
emit LoopTerminated → caller(host)收尾持久化
```

## 外部 API

```python
from orion_sdk.core.conversation import Conversation
from orion_model.provider import get_provider

provider = get_provider("anthropic", "claude-sonnet-4-6")
conv = Conversation(
    provider=provider,
    system_prompt="You are a helpful assistant.",
    tools=[ReadTool(), WriteTool(), ...],
    max_turns=20,
    persistence_enabled=True,
    memory_enabled=True,
    db_engine=engine,
)

async for ev in conv.send("Refactor query_loop.py"):
    if isinstance(ev, AssistantTextDelta):
        print(ev.text, end="")
    elif isinstance(ev, ToolUseStart):
        print(f"\n[tool {ev.tool_name}]")
    elif isinstance(ev, LoopTerminated):
        print(f"\n[done — {ev.reason}, {ev.total_turns} turns]")
```

`Conversation` 是 **stateful** — 同一個 instance 多次 `.send()` 累積對話。

## AgentContext(`state.py`)

Turn-level mutable state — 跨工具共享 + 跨輪 reset 機制:

```python
@dataclass
class AgentContext:
    session_id: str
    user_id: str
    workspace_dir: Path | None
    permission_policy: PermissionPolicy
    plan_mode_state: PlanModeState | None
    tool_use_id_counter: int
    # 等等
```

每次 `conv.send()` 內部建一個新 `AgentContext`,工具 callback 拿這個 ctx 做 per-turn 判斷
(權限 / plan mode 限制 / ...)。

## 設計取捨

- **State machine 不暴露**:`Conversation.state_messages` 是 internal,caller 不該直接改;要 inspect 走 `conv.snapshot()`(immutable copy)。
- **Turn 不是 round-trip 同義**:1 turn = 1 次 provider.stream 完整收到 + 後續 tool 執行。一個對話可能 N turns 才終止。
- **平行 tool 預設 on**:`ExecutorPolicy.CONCURRENT`(asyncio.gather)— 但 stateful tool(`TodoWrite`)會宣告自己要 `SEQUENTIAL`。
- **Provider abstraction 在 orion-model**:`Conversation` 只認 `Provider` 介面,不認 anthropic/openai 具體 class。`get_provider("anthropic", model)` 回對應實例。

## 限制 / 已知問題

- **max_turns hard cap**:預設 100。超過直接 `LoopTerminated(reason="max_turns")`,不能無限。要長 task 要 caller 主動續(`conv.send("continue")`)。
- **Mid-turn pause 還沒做**:Ask user / approval 等 user 反應 OK,但「pause 後 N 小時再 resume」沒設計,中間 cache miss。
- **多 turn workspace 切換**:`AgentContext.workspace_dir` 一旦設定,該對話內不變;切 dir 要另開 session。

## 看完繼續

- [tools.md](./tools.md) — 30+ 內建工具
- [streaming.md](./streaming.md) — event 流的細節
- [permissions.md](./permissions.md) — 權限決策怎麼介入
- [compaction.md](./compaction.md) — 對話過長自動壓縮

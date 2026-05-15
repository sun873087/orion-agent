# Agent loop

orion-agent 的心臟。`Conversation.send(prompt)` 跑一輪「LLM → 工具呼叫 → LLM 看 result → ...」多 turn loop,串流 yield events 給 caller。

**實作位置**:`packages/orion-sdk/src/orion_sdk/core/`
- `conversation.py` — `Conversation` dataclass(跨 send 共用的狀態)
- `query_loop.py` — `query_loop()` async generator(單次 send 的 turn 迴圈)
- `streaming_executor.py` — `StreamingExecutor`(平行 tool 執行 + 順序 yield results)
- `tool_orchestration.py` — tool selection + permission check
- `tool_execution.py` — 單一 tool 的 progress / error / result 流

## Caller API

```python
from orion_sdk.core.conversation import Conversation
from orion_sdk.core.state import AgentContext
from orion_sdk.tools.builtin_set import build_default_tool_set
from orion_model.provider import get_provider

llm = get_provider("anthropic", "claude-sonnet-4-6")
conv = Conversation(provider=llm, tools=build_default_tool_set(asker=None))
ctx = AgentContext()

async for event in conv.send("讀 /etc/hosts 並摘要", ctx=ctx):
    handle(event)
```

## Event 型別

`conv.send()` yield 的事件 union(`query_loop.LoopEvent | ToolUpdate`):

| Event | 意義 | data |
|---|---|---|
| `AssistantTextDelta` | LLM 文字增量 | `text: str` |
| `AssistantThinkingDelta` | LLM reasoning 增量(僅 reasoning provider) | `text: str` |
| `AssistantTurnComplete` | 單 turn 結束,assistant message 已 append 進 state_messages | (no data) |
| `ToolProgressUpdate` | 工具執行中事件(start / progress / error) | `tool_name, tool_use_id, event: ToolEvent` |
| `ToolResultUpdate` | 工具 final result(成功或錯誤) | `tool_name, tool_use_id, is_error, message` |
| `LoopTerminated` | 整個 loop 結束 | `transition.reason, total_turns` |

事件流範例(假設 LLM 呼叫 Bash 工具):

```
AssistantTextDelta(text="我來看一下")
AssistantTextDelta(text="...")
AssistantTurnComplete()
ToolProgressUpdate(tool_name="Bash", event=ProgressEvent(data={"stage": "starting"}))
ToolResultUpdate(tool_name="Bash", is_error=False, message=ToolResultMessage(...))
AssistantTextDelta(text="檔案內容是 ...")
AssistantTurnComplete()
LoopTerminated(transition.reason="end_turn", total_turns=2)
```

## 內部流程(單 turn)

```
1. Conversation.send 收 user prompt → append to state_messages
2. system prompt 組裝(prompt/assembler.py 跑 7 層 + 動態段)
3. provider.stream(system, messages, tools) → 開始收 NormalizedEvent
4. 逐事件處理:
   - TextDeltaEvent → yield AssistantTextDelta
   - ToolUseStartEvent + ToolUseStopEvent → 累積 tool_calls
   - MessageStopEvent → assistant message 完整,append state_messages
5. yield AssistantTurnComplete
6. 若有 tool_calls:
   a. StreamingExecutor 平行 spawn 所有 tool tasks
   b. 邊執行邊 yield ToolProgressUpdate
   c. 結束時 yield ToolResultUpdate(按 add 順序)
   d. 全部 tool result 包成 user message append state_messages
7. 若 max_turns 未到 + 有 tool result → goto 2(下一輪)
8. 否則 yield LoopTerminated
```

## 平行 tool 執行

`StreamingExecutor` 的設計目標:**LLM 一次給多個 tool call,並行跑,但結果按原順序 yield 給 caller**。

- 每個 tool 一個 asyncio task
- task 跑時把 events push 到自己的 queue
- 主迴圈按 tool_use_id 添加順序,from 對應 queue 拉事件 yield
- 一個 tool 還在跑時,順序在前的若已完成,先 yield;順序在後的等

這讓「3 個獨立檔案讀取」可以平行,但 caller 看到的事件順序仍是 deterministic。

## 終止條件(LoopTerminated)

`transition.reason` 可能值:

- `end_turn` — LLM 回應沒包含 tool_use,正常結束
- `max_turns` — 達到 `Conversation.max_turns`,強制終止
- `aborted` — `ctx.abort_event.set()` 被觸發(Ctrl-C / UI cancel)
- `max_tokens` — 單 turn 達 `max_tokens_per_turn`,終止
- `provider_error` — LLM API 出錯且 retry 用盡

## 設計取捨

- **Conversation 是 dataclass(state)**,`query_loop` 是純函式 — 易測試(MockProvider 餵 events 就能跑)
- **Tool 用 Protocol 而非繼承** — 工具不必繼承 base class,符合 duck typing
- **Streaming 用 async generator** — caller 可隨時 break 中止,符合 Python 慣例
- **不 batch tool results** — 每個 tool 一完成立即 yield ToolResultUpdate,UI 不會卡住等最慢的

詳見 [`../architecture/design-decisions.md`](../architecture/design-decisions.md) §1(不用 agent framework)。

## 限制

- 單 thread asyncio,工具內阻塞操作要記得用 `asyncio.to_thread`
- `Conversation` 不是 thread-safe — 多 thread 用法請各自一個 instance
- `query_loop` 沒有內建 retry — provider 層 retry(`anthropic` / `openai` SDK 自帶),loop 不重試
- LLM 給的 tool call 數量沒 cap — 理論上單 turn 可能 spawn 100+ tool tasks(實務 max ~10)

## 相關 features

- [tools.md](./tools.md) — Tool 介面、內建工具集
- [streaming.md](./streaming.md) — Provider 事件 → user-facing event 細節
- [compaction.md](./compaction.md) — 對話太長時自動壓縮
- [permissions.md](./permissions.md) — Tool 執行前的 permission 流程

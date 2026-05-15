# Streaming events

LLM 回應一個字一個字 yield 出來,經過兩層轉換到 caller 手上:

```
LLM SDK wire format      →    NormalizedEvent      →    LoopEvent / ToolUpdate
(anthropic.MessageStream  ↑   (orion_model.events,  ↑   (orion_sdk.core.query_loop,
 openai.ChatCompletion)   ↑    provider-agnostic)    ↑    caller-facing)
                          │                         │
                  provider translation        agent loop
                  (orion_model/translation/)  (core/query_loop.py)
```

**實作位置**:
- `packages/orion-model/translation/{anthropic,openai}.py` — wire ↔ normalized
- `packages/orion-sdk/src/orion_sdk/core/query_loop.py` — normalized → user-facing

## NormalizedEvent(provider-agnostic)

```python
from orion_model.events import (
    MessageStartEvent,
    TextDeltaEvent,
    ThinkingDeltaEvent,     # 僅 reasoning provider(o1 / Claude reasoning)
    ToolUseStartEvent,
    ToolUseStopEvent,
    MessageStopEvent,       # 內含 stop_reason + usage
)
```

兩個 provider 行為差異(prompt caching、reasoning blocks、tool 並行)都在 translation 層吸收。

## LoopEvent(user-facing)

詳見 [agent-loop.md](./agent-loop.md) — `AssistantTextDelta` / `AssistantTurnComplete` / `ToolProgressUpdate` / `ToolResultUpdate` / `LoopTerminated`。

## Provider 差異吸收

| Anthropic | OpenAI | orion 統一 |
|---|---|---|
| `content_block_delta` thinking type | `o1` reasoning_summary in choices | `ThinkingDeltaEvent` |
| `tool_use` content block | `tool_calls` array with id | `ToolUseStartEvent` + `ToolUseStopEvent`(成對) |
| `usage.cache_read_input_tokens` | `prompt_tokens_details.cached_tokens` | `NormalizedUsage.cache_read_tokens` |
| `stop_reason="end_turn"` | `finish_reason="stop"` | `stop_reason="end_turn"` |

## 為何不直接用 SDK 原生 events

- LLM provider 換 / 升級時 SDK schema 會變,集中在 translation 層改一處就好
- agent loop 邏輯不需要知道 wire format
- 測試:用 MockProvider 灌 NormalizedEvent,不需 mock 整個 anthropic SDK

## 設計取捨

詳見 [`../architecture/design-decisions.md`](../architecture/design-decisions.md) §1(不用 framework)、§2(orion-model 獨立)。

## 相關

- [agent-loop.md](./agent-loop.md) — 事件流如何驅動 turn loop
- [prompt-caching.md](./prompt-caching.md) — usage 內 cache 統計

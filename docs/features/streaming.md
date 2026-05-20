# Streaming events

LLM 一個 token 一個 token 出 → 經兩層轉換到 caller。Caller(host)只看 NormalizedEvent /
LoopEvent,不必懂各 provider 的 wire format。

**實作位置**:`packages/orion-model/src/orion_model/events.py` +
`packages/orion-sdk/src/orion_sdk/core/query_loop.py`

## 兩層

```
provider wire(各家不同)
    │  Anthropic SSE event_stream / OpenAI Chat SSE chunks
    ▼
orion_model.Provider.stream() → AsyncIterator[NormalizedEvent]
    │  跨 provider 統一:MessageStart / TextDelta / ThinkingDelta / ToolUse* / ...
    ▼
orion_sdk.QueryLoop → AsyncIterator[LoopEvent]
    │  agent-level 抽象:AssistantTextDelta / ToolUseStart / ToolResult /
    │                    AssistantTurnComplete / LoopTerminated
    ▼
Caller(host)— 用 isinstance 分派
```

## NormalizedEvent(`orion_model/events.py`)

```python
NormalizedEvent = (
    MessageStartEvent          # 開始新 message
    | TextDeltaEvent           # 文字 chunk
    | ThinkingDeltaEvent       # 思考鏈 chunk(Anthropic / OpenAI o-series)
    | ToolUseStartEvent        # 開始 tool call
    | ToolUseInputDeltaEvent   # tool input JSON 邊解邊吐
    | ToolUseStopEvent         # tool call 完整 input 拿到
    | MessageStopEvent         # message 結束,attach final usage
)

@dataclass
class NormalizedUsage:
    input_tokens: int
    output_tokens: int
    cache_read_tokens: int
    cache_creation_tokens: int   # Anthropic-only
```

## LoopEvent(`orion_sdk/core/query_loop.py`)

```python
LoopEvent = (
    AssistantTextDelta        # 累加給 UI 顯字
    | AssistantThinkingDelta  # 思考鏈(Cowork 預設不渲染)
    | AssistantTurnComplete   # 一輪 LLM 結束,可拿完整 message
    | ToolUseStart            # 對應 NormalizedEvent.ToolUseStart
    | ToolProgress            # tool 跑到一半的 partial output(e.g. Bash long-running)
    | ToolResult              # tool 結果(include is_error / text)
    | ToolError               # tool 內部 error(非 LLM 看到的 error,is_error=True 給 LLM 看)
    | AskUserQuestion         # tool 要 user 回應(暫停)
    | ToolApprovalRequest     # permission policy ask mode 要 user 批
    | CompactStarted          # auto-compact 開始
    | CompactComplete         # auto-compact 完成
    | LoopTerminated          # 整 loop 結束,帶 reason + total_turns
)
```

## 行為細節

- **SSE 不 buffer**:`provider.stream()` 用 `aiter_bytes()` 邊收邊 yield,UX 即時。
- **Usage 在 MessageStopEvent 才齊**:streaming 中累加,結束時 emit final。
- **Tool input JSON 分段到**:LLM 的 tool_use.input 是 JSON,SSE 逐 chunk 吐 partial JSON,UI 可即時 preview。
- **ToolProgress 是 host 推**:Bash long-running 之類,host 透過 `progress_callback` 推進度給 UI,不是 LLM 給的。

## 設計取捨

- **兩層抽象不偷懶**:NormalizedEvent 是「跟 LLM 對話的事實」,LoopEvent 是「agent loop 跑的事實」。混在一起 caller 會看到 6 種 tool_use_* 細節變數,難用。
- **AskUserQuestion 是 event 不是 exception**:LLM call 工具問 user → 走 event 流(host 收到後彈 UI 等 reply)→ reply 寫回 ctx 內 future。比 raise 然後 catch 流暢。

## 限制 / 已知問題

- **Thinking event provider 行為不同**:Anthropic 永遠有 thinking;OpenAI o-series 設 `reasoning_effort` 才有;Ollama 沒。Host 要 fallback。
- **Tool input JSON malformed**:Provider 偶爾吐不完整 JSON(發 timeout),query_loop 內 try/except 寫死回空 dict — 那一 tool call fail。

## 未來方向

- **Cancellation token**:caller 中斷 send loop 時更乾淨地 cleanup pending tool task
- **Backpressure**:UI 慢時 producer 暫緩,避免 OOM(目前 unbounded queue)

## 看完繼續

- [agent-loop.md](./agent-loop.md) — Loop event 在 loop 哪邊產生
- [models.md](./models.md) — provider stream 行為
- [tools.md](./tools.md) — Tool 跟 streaming 互動

# Conversation compaction

對話訊息累積到一定 size 時,把舊內容濃縮(summarize / drop)以維持 context window 內。三種策略並存。

**實作位置**:`packages/orion-sdk/src/orion_sdk/compact/`

## 三種策略

| 策略 | 觸發 | 行為 |
|---|---|---|
| `auto` | 訊息累積到 `Conversation.auto_compact_threshold`(預設 80% context window) | 用獨立 LLM call 把舊訊息 summarize 成濃縮版,替換掉原訊息 |
| `reactive` | 收到 provider error `max_tokens` / `context_length_exceeded` | 反應式重試:壓縮後 retry 同 turn |
| `tombstone` | 工具結果 > 100KB | 把巨大 tool result 替換成 placeholder("(omitted X bytes — see tool_results/...)"),保留 metadata |

三者**可並存**。Auto compact 觸發時不會壞 reactive,反之亦然。

## Strategies(實際壓縮方法)

`strategies.py` 定義:

- `TruncateStrategy` — 純截斷舊訊息(快但失真大)
- `SummaryStrategy` — LLM call 摘要(慢但保留語意)

預設 `SummaryStrategy`,可在 `Conversation` 建構時換。

## 行為控制

```python
conv = Conversation(
    provider=llm,
    tools=tools,
    auto_compact_enabled=True,
    auto_compact_threshold=0.8,  # 80% context window
)
```

關閉:`auto_compact_enabled=False`。Reactive 跟 tombstone 跟 SDK 內部錯誤處理綁,無 flag 控制。

## Tombstone 細節

工具結果 > `STORE_INLINE_LIMIT`(預設 100KB)→ 寫 `~/.orion/sessions/<sid>/tool-results/<id>.json`,訊息只留 metadata 跟 path。resume 時 caller 可從檔還原。

詳見 `storage/replacement_state.py` 跟 `compact/tombstone.py`。

## 限制

- Auto compact 是 lossy — 連續多次後品質會降。建議:長對話開新 session
- Reactive compact 失敗會 propagate error → caller 應 catch + 開新 session
- Summary strategy 用同一個 provider,可能撞 rate limit

## 相關

- [memory.md](./memory.md) — 跨 session 的長期記憶(不同於對話內 compaction)
- [storage.md](./storage.md) — 大結果三層 budget
- [agent-loop.md](./agent-loop.md) — compact 何時被觸發

# Compaction

對話訊息累積到 context window 上限附近時,把舊內容濃縮,避免 truncate / OOM。

**實作位置**:`packages/orion-sdk/src/orion_sdk/compact/`

## 3 種觸發

| 觸發 | 時機 | 用 model |
|---|---|---|
| **Auto(token-based)** | 對話 token 達 max_context × `auto_compact_threshold`(預設 0.8) | `compact_summary_provider`(預設便宜 — Haiku / gpt-5-mini)|
| **Reactive** | LLM call 失敗 `context_length_exceeded` → 自動 compact 後重試 | 同上 |
| **Manual** | host 主動呼 `Conversation.compact()`(Cowork `/compact` slash) | 同上 |

## 流程

```
trigger compact
    ▼
取最舊 N% messages(預設 50%)
    ▼
build summary prompt:
    "Summarize this conversation in 200 words, keeping critical decisions / file paths / tool results."
    ▼
compact_summary_provider.stream(...) → summary text
    ▼
replace 最舊 N% messages 為 1 條 system message:"Previous discussion summary: <summary>"
    ▼
emit CompactComplete event(before / after token count + summary text)
```

## 控制 env / params

```python
conv = Conversation(
    provider=primary,
    compact_summary_provider=cheap_provider,  # None = 用 same primary
    auto_compact_enabled=True,
    auto_compact_threshold=0.8,               # 0..1
    ...
)
```

env:`ORION_AUTO_COMPACT_THRESHOLD=0.85`

## 設計取捨

- **Summary 不刪 tool_result**:重要的 file content / 搜尋結果留著,只 summarize 對話 text。Workaround:user 在 summary prompt 內 hint「list file paths verbatim」。
- **Cheap model 預設**:壓縮是輕任務,Haiku 4.5 / gpt-5-mini 夠用,省主對話模型成本。
- **保留最近 N 輪**:summarize 最舊 50%,最近 50% 不動 — 對話 continuity 重要。

## 限制 / 已知問題

- **Summarize 可能漏關鍵**:LLM summary 不一定精準,丟訊息後 model 可能再問 user 重複資訊
- **不 reversible**:compact 後原 message dropped(只有 summary text),要回看走 transcript 持久化
- **Project chat 的 file context**:project-bound message 內常有 `@<file>` reference,summarize 可能漏

## 未來方向

- **Selective compact**:保留所有 tool_result(只 summarize 對話)+ 給 user toggle
- **Tiered compact**:三層 — 最近 30 條 verbatim / 中 50 條 short summary / 最舊全 full summary
- **Compact reversal**:把 dropped messages 存進 cold storage(blob),user 可以 retrieve

## 看完繼續

- [agent-loop.md](./agent-loop.md) — compact 在 loop 開頭 trigger
- [memory.md](./memory.md) — compact 跟 memory 是兩件事(memory 是跨 session 的長期事實)
- [prompt-caching.md](./prompt-caching.md) — compact 後 cache breakpoint 重設

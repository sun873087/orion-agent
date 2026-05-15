# Prompt caching

利用 Anthropic / OpenAI 的 prompt cache 降低重複 prompt 的 token 成本。

**實作位置**:
- 決策邏輯:`packages/orion-sdk/src/orion_sdk/prompt/`(system prompt assembly + cache breakpoint)
- Provider-side 設定:`packages/orion-model/src/orion_model/cache_config.py`

## 兩種 provider 的 cache 機制

| Provider | 機制 | 上限 |
|---|---|---|
| Anthropic | 顯式 cache breakpoint(`cache_control: ephemeral`)在 system / tools / messages 上 | 5 分鐘 TTL,4 個 breakpoint max |
| OpenAI | 自動,>1024 token prefix 命中即用 | server 控制,no API surface |

orion 統一用 `cache_breakpoints: list[int]` 傳給 provider,Anthropic translation 把 index 轉成 `cache_control` 標記,OpenAI translation 忽略(因為自動)。

## Breakpoint 策略

`prompt/assembler.py` 組 system prompt 7 層 + 動態段,將 breakpoint 放在:

1. 靜態 prompt(7 層,不變)結束處 — TTL 久,命中率高
2. Memory + skills + MCP tools 區塊結束處
3. 對話訊息中 — 每 N turn 一個(平衡 cache hit 跟 break 成本)
4. 最後幾條訊息前(讓 reactive compaction 後仍能命中)

具體決策 in `prompt/cache_breakpoints.py`(暫未獨立文件,看 code)。

## Cache hit 監測

每個 turn `NormalizedUsage`:

- `cache_read_input_tokens` — 命中
- `cache_creation_input_tokens` — 寫入新 cache
- `input_tokens` — 真正算錢的 input
- `output_tokens` — 模型輸出

cost 公式(`telemetry/pricing.py`):

```
cost = read_tokens * read_rate
     + creation_tokens * creation_rate    # 通常比 input_rate 高 25%
     + input_tokens * input_rate          # not cached
     + output_tokens * output_rate
```

## 設計取捨

- **單 conversation 內最佳化**:不跨 session 共用 cache(provider 限制)
- **靜態 + 半動態混合**:純動態(memory)放 cache 區意義不大 — 已調整為 memory 進 breakpoint 之後
- **不主動破壞 cache**:即使 system prompt 改了(skill 啟用),只更新動態段,7 層靜態保持

## 限制

- Anthropic 4 breakpoint cap — 不夠分時策略 fallback 到只放最重要的
- 5 分鐘 TTL — long-idle 對話可能要重 warm
- OpenAI 沒 metric:cache hit 看不到(只能算總 token 變化推測)

## 相關

- [agent-loop.md](./agent-loop.md) — 系統 prompt 何時組裝
- [streaming.md](./streaming.md) — `NormalizedUsage` schema

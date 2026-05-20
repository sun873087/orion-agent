# Prompt caching

利用 Anthropic / OpenAI 的 prompt cache 降低重複 prompt 的 token 成本。orion 內建
兩家不同的 cache 策略。

**實作位置**:
- `packages/orion-model/src/orion_model/cache_config.py`
- `packages/orion-sdk/src/orion_sdk/prompt/`(system prompt builder + cache breakpoint)

## Anthropic — explicit cache control

Anthropic 計費:
- 5m TTL write:input × 1.25×
- 1h TTL write:input × 2×
- read:input × 0.1×(永遠這價,無論 TTL)

system prompt 拆 7 段,每段獨立 cache_control:

```
1. orion-agent fingerprint(永遠不變)     ─┐
2. Model identity                          │  static + 1h cache
3. Tool registry definition                │
4. Workspace rules                        ─┘
5. Skills(load when needed)               ─┐
6. Memory(top-N from ranker)              │  session-stable + 1h cache
7. Dynamic instructions(user prefs)       ─┘

8. Messages history(rolling 5m)
```

最近 message 5m cache(每 turn 寫最新 breakpoint),session-stable / static 用 1h(跨多輪 idle gap 也有效)。

`ORION_CACHE_TTL_STATIC=1h` / `ORION_CACHE_TTL_SESSION=1h` / `ORION_CACHE_TTL_MESSAGES=5m`
env 可改。

## OpenAI — implicit cache

OpenAI cache 是隱式的:`prompt_tokens_details.cached_tokens` 自動回報,不必我們標
cache_control。Orion 對 OpenAI 的 system prompt 不額外處理。

## 觀察

Cache 命中比例:

```
Turn 1:0% cache(全新)
Turn 2:80%+ cache(system + 上輪 messages 都 hit)
Turn 3+:90%+(只 last user msg 是 fresh)
```

Anthropic 5m TTL 限制:idle 超過 5m,messages cache 失效;但 1h cache 的 system 還在。

## 限制 / 已知問題

- **Anthropic cache breakpoint 上限 4 個**:7 段壓進 4 個 breakpoint 需要精算 — `apply_cache_breakpoints()` 處理。
- **Compact 後 cache reset**:summary 取代舊 messages → cache breakpoint 重新 anchor,下一輪會多寫一次。
- **OpenAI 不能 selective cache**:全部或全部不,不能像 Anthropic 精準到段。

## 未來方向

- **Cross-session prompt cache**:proxy 端 hash-based cache(`prompt_cache` 表已存在,還沒 wire)
- **Smart cache 預熱**:idle 即將過期前主動發 short request 續命

## 看完繼續

- [`../architecture/design-decisions.md`](../architecture/design-decisions.md) §8 — 為何 TTL 這樣設
- [agent-loop.md](./agent-loop.md) — system prompt 在哪建
- [model-proxy.md](./model-proxy.md) — proxy 層的 prompt cache(Phase 33 已建表,還沒接 reverse_proxy)

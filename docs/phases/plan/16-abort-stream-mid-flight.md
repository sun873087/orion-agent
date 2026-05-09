# Phase 16:Stream 中途即時 abort

## 速覽

- **預計時程**:1-2 天
- **前置 Phase**:Phase 0(`abort_event` 已備)+ Phase 1(query_loop 已 turn 邊界檢查)
- **觸發來源**:`phase-00-completion.md` Abort 機制部分完成。本 phase 補完中途即時中止
- **主要交付物**:
  - `provider.stream()` 中途可被 `ctx.abort_event.set()` 立即終止(httpx connection close)
  - CLI / FastAPI(Phase 6)的 Ctrl-C / disconnect 信號正確轉成 `abort_event.set()`
  - `BashTool` 已有的 watch_abort 模式擴展到所有 long-running 工具

## 1. 目標與動機

目前 abort 行為:

| 情境 | 是否能立即停 | 為何 |
|---|---|---|
| Turn 邊界(model 結束 / tool 結束)| ✅ | query_loop 在每輪檢查 `ctx.abort_event` |
| BashTool 跑 subprocess 中 | ✅ | watch_abort task 監看 |
| **provider.stream() 進行中** | ❌ | httpx response 沒被 cancel scope 包,要等 stream 自然結束 |
| **WebFetchTool / GrepTool ripgrep 進行中** | ❌ | 同上 |

最差情境:user 按 Ctrl-C,模型還在 stream 一篇 30 秒 reasoning,要等 30 秒才停。

## 2. 任務拆解

### 2.1 provider.stream() 接 cancel scope

- [ ] `anthropic_provider.py:AnthropicProvider.stream` 用 `anyio.move_on_after` 或外圍 cancel scope 包 `client.messages.stream` context
- [ ] `openai_provider.py:OpenAIProvider.stream` 同上
- [ ] `query_loop._run_one_turn` 在 `provider.stream(...)` 外加一層 `async with anyio.CancelScope` 監看 `ctx.abort_event`,set 時 `scope.cancel()`

### 2.2 CLI 的 KeyboardInterrupt 轉 abort_event

- [ ] `main.py:_run_async` 用 `signal.signal(SIGINT, ...)` 或 anyio signal handling
- [ ] 第一次 Ctrl-C → `ctx.abort_event.set()`(graceful)
- [ ] 第二次 Ctrl-C(若 5 秒內仍卡)→ 整個 process 強制終止

### 2.3 long-running 工具的 watch_abort 模式

把 `BashTool` 的 watch_abort 抽為共用 helper,套用到:
- [ ] `WebFetchTool`(httpx 內部已 timeout,但要明確檢查 abort_event)
- [ ] `GrepTool`(ripgrep subprocess 模式 — Python fallback 已是同步,需 chunk-yield)
- [ ] `AgentTool` 子 query_loop(已天然有 turn 邊界檢查)

## 3. 設計決策

### 為何不直接用 `anyio.fail_after(timeout)`?

`fail_after` 是時限性中斷;abort_event 是 user-driven。模型可能合法跑 60 秒 reasoning,
我們不該硬定時限。改用 `anyio.CancelScope` + watcher task 監看 abort_event,
條件成立才 cancel scope。

### 為何兩次 Ctrl-C?

第一次 Ctrl-C 給 graceful chance(讓正在跑的 tool 寫完 transcript、釋放 lock 等);
第二次強制終止防 user 卡死(若某 task 沒處理 cancel)。對應 TS Claude Code 的同樣模式。

## 4. 驗收標準

```python
# tests/unit/core/test_abort_mid_stream.py
async def test_abort_during_stream_terminates_immediately():
    """模擬 provider.stream 跑到一半 set abort_event → query_loop <100ms 內終止。"""
    slow_provider = SlowMockProvider(delay_per_chunk=0.5, total_chunks=20)
    ctx = AgentContext()

    async def trigger_abort():
        await anyio.sleep(0.1)  # 等 stream 開始
        ctx.abort_event.set()

    start = time.monotonic()
    async with anyio.create_task_group() as tg:
        tg.start_soon(trigger_abort)
        events = [e async for e in query_loop(params, ctx)]
    elapsed = time.monotonic() - start

    assert elapsed < 0.5  # 該在 100-300ms 內結束(不是 10 秒等 stream 完)
    assert events[-1].transition.reason == "aborted"
```

手動驗證:
- `make run-anthropic ARGS="..."` 跑長 task
- 中途按 Ctrl-C
- 應 1 秒內回 prompt(不是 30 秒)

## 5. 相關 code

- `orion_agent/core/state.py` — AgentContext.abort_event(已備)
- `orion_agent/core/query_loop.py:_run_one_turn` — 加外圍 cancel scope
- `orion_agent/llm/anthropic_provider.py:stream` / `openai_provider.py:stream`
- `orion_agent/main.py:_run_async` — signal handler
- `orion_agent/tools/shell/bash.py:watch_abort` — 已有的監看模式參考

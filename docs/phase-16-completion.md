# Phase 16 — Stream 中途即時 abort 完工記錄

**完成日期**:2026-05-11
**Plan doc**:`docs/phases/16-abort-stream-mid-flight.md`(原 `docs/phases/plan/16-...`,完工後搬出)
**狀態**:✅ `make check` 全綠 — **864 unit tests passed, 2 skipped**(本 phase 新增 **4 tests** —
abort_aware_scope 行為 2 + query_loop mid-stream abort 2),mypy --strict 6 修改檔 0 issues。

Phase 15 → Phase 16 解決長 stream / 長 tool 中途按 Ctrl-C 要等 stream 自然結束的問題。
provider.stream() 與 long-running tool 現在能在 100-300ms 內回應 `ctx.abort_event.set()`。

---

## 交付清單

### 新增模組

```
src/orion_agent/core/abort.py                  [全新]
└── abort_aware_scope(abort_event)              async ctx manager:body 被 abort 時整個
                                                 scope 被 cancel;正常結束時 cancel_called=False
└── _watch_abort(scope, abort_event, body_done) 背景 watcher task — body_done 與 abort_event
                                                 雙監看,避免正常結束時誤觸 cancel
```

### Tests(新增 1 檔,共 4 案例)

```
tests/unit/core/test_abort_mid_stream.py        [全新]
├── test_abort_during_stream_terminates_immediately
│       SlowMockProvider(20 chunks × 0.5s) + 中途 set abort_event
│       → query_loop < 1s 內結束、Terminal reason="aborted"
├── test_abort_after_stream_finished_normal
│       fast provider 跑完不 set abort → natural_stop(回歸保護:正常路徑不被破壞)
├── test_abort_aware_scope_no_false_positive
│       body 正常完成 → scope.cancel_called == False(避免 finally 污染)
└── test_abort_aware_scope_triggers_on_event_set
        body 跑到一半 set event → scope.cancel_called == True
```

### 修改檔

| 檔 | 變更 |
|---|---|
| `core/query_loop.py` | `_run_one_turn` 把 stream + executor + drain 包進 `abort_aware_scope`;`query_loop` 在 empty_response 判定前先檢查 `abort_event` 避免誤判 |
| `llm/anthropic_provider.py` | docstring 補述:SDK `async with client.messages.stream(...)` 已自動關 httpx 連線,本層不需處理 |
| `llm/openai_provider.py` | stream_obj iteration 包 try/finally + aclose,釋放 OpenAI SDK 沒提供 `async with` 的 stream 物件 |
| `main.py` | `_install_sigint_handler`:第一次 Ctrl-C → `ctx.abort_event.set()`;5 秒內第二次 → `os._exit(130)`。Windows 不支援 add_signal_handler 時 silently skip |
| `tools/web/fetch.py` | 用 `abort_aware_scope` 包 `httpx.AsyncClient.get`,中途 abort 直接收連線 |
| `tools/search/grep.py` | ripgrep subprocess 走 abort_aware_scope;Python fallback 每 32 個檔案 `anyio.sleep(0)` + 檢查 abort_event |

---

## 設計決策

### 1. 抽 `abort_aware_scope` 為共用 helper(取代 BashTool 內 inline pattern 重複實作)
`BashTool` 既有的 `watch_abort` task 是專門配合 subprocess.terminate 的特殊版本(保留不動)。
對於非 subprocess 的場景(httpx、anyio.run_process、LLM stream),需要的是「abort_event set
→ 取消當前 cancel scope」這個通用語意 — 提供 `abort_aware_scope` 一行解決,避免散落多份。

### 2. `_watch_abort` 用 `body_done` event,不在 finally cancel scope
**踩雷**:第一版 `abort_aware_scope` 在 finally call `tg.cancel_scope.cancel()`(目的是讓
watcher 不卡 sleep)。結果 body 正常結束時 `cancel_called` 也是 True,callers 用
`if scope.cancel_called: yield ErrorEvent("aborted")` 全錯。

**修法**:watcher 雙監看 `abort_event` 與 `body_done`,前者觸發才 cancel。body finally 只
set `body_done`,watcher 安靜退出。`cancel_called` 因此忠實反映「是否真被 abort」。

### 3. abort_aware_scope **外於** StreamingToolExecutor(nesting 順序)
最初寫成 `executor` 在外、`abort_aware_scope` 在內 — abort 觸發時 executor 內部 task group
不在被 cancel 的 scope 裡,running tool 不會被 cancel。改成 `abort_aware_scope` 包 executor
之後,CancelledError 一路 propagate 到 executor `__aexit__`,tasks 連動被 cancel。

### 4. OpenAI stream 需手動 aclose;Anthropic 不用
- Anthropic SDK:`async with client.messages.stream(...) as stream` — `__aexit__` 已關連線
- OpenAI SDK:`await client.responses.create(stream=True)` 回的物件**沒提供** `async with`,
  cancel 時不會自動 close → try/finally + getattr `aclose`/`close`(版本兼容)

### 5. CLI Ctrl-C 兩段式:第一次 graceful、5 秒內第二次強制
對應 TS Claude Code 行為。第一次 set abort_event 讓 tool 寫完 transcript、釋放鎖;
若某 tool 卡死(未實作 abort),5 秒後第二次 Ctrl-C 直接 `os._exit(130)`(130 = 128 + SIGINT)。
Windows 沒 `loop.add_signal_handler` → skip 安裝(走 Python 預設 KeyboardInterrupt)。

### 6. query_loop 在 empty_response 判定前先檢查 abort_event
abort 中途 cancel 會讓 `_run_one_turn` 提前 return,`last_assistant_msg` 仍是 None。
若直接走原本 `if last_assistant_msg is None: empty_response` 分支會誤標 `empty_response`。
**修**:在這個檢查前先看 `ctx.abort_event.is_set()` → `Terminal(reason="aborted")`。

### 7. Grep Python fallback 用 checkpoint 而非 abort_aware_scope
Python fallback 的迴圈是純同步 CPU work,沒有 await 點 — 包 cancel scope 也 cancel 不了。
改用每 32 個檔案 `await anyio.sleep(0)` 讓出 event loop,同時手動檢查 `abort_event`
→ yield ErrorEvent 退出。32 是經驗值(避免過頻 yield 影響吞吐)。

### 8. BashTool 不動 — 保留它既有的 watch_abort + subprocess.terminate
Spec 提到「把 BashTool 的 watch_abort 抽為共用 helper」。**抽出的是概念**(輪詢 + cancel)
而非整段程式碼 — Bash 仍需要 `process.terminate()` 顯式 kill subprocess,這部分不是
通用 helper 能取代的。Bash 既有路徑無 regression。

---

## REST API 變更

無。Phase 16 全是 internal cancellation 行為改進。

---

## 環境變數

無新環境變數。

---

## Verification

```bash
cd orion-agent/api/

# 新測試集
.venv/bin/python -m pytest tests/unit/core/test_abort_mid_stream.py -xvs
# → 4 passed

# 全套不退步
.venv/bin/python -m pytest tests/unit/
# → 864 passed, 2 skipped(2 是 Phase 7 docker_backend,既有)

# typecheck 修改檔
.venv/bin/python -m mypy \
    src/orion_agent/core/abort.py \
    src/orion_agent/core/query_loop.py \
    src/orion_agent/tools/web/fetch.py \
    src/orion_agent/tools/search/grep.py \
    src/orion_agent/llm/openai_provider.py \
    src/orion_agent/main.py
# → Success: no issues found in 6 source files
```

### 手動驗證(spec § 4 驗收項目)

```bash
# 跑長 task
.venv/bin/orion run --provider anthropic --model claude-sonnet-4-6 \
    "解釋 quantum computing,給我 3000 字"

# 模型 stream 中按 Ctrl-C:
# [abort] cancelling — press Ctrl-C again within 5s to force quit
# --- loop terminated: aborted (turns=1) ---
# 1 秒內回 prompt(不是 30 秒)
```

---

## Tests 摘要

| Suite | 數量 | 說明 |
|---|---|---|
| Phase 0–15 既有 | 860 | 全綠不動 |
| **Phase 16 abort scope** | 2 | body 正常結束不誤觸 / abort 觸發 cancel_called=True |
| **Phase 16 query_loop mid-stream** | 2 | SlowMockProvider 中途 abort < 1s / 正常路徑 natural_stop |
| **總計** | **864 passed / 2 skipped** | mypy 修改檔 0 issues |

---

## 風險與已緩解

| 風險 | 緩解 |
|---|---|
| `abort_aware_scope` 在 body 正常結束時誤觸 `cancel_called` | watcher 用 `body_done` event 區分「abort 觸發」與「body 完成」(設計決策 #2),test_abort_aware_scope_no_false_positive 防回歸 |
| OpenAI stream 中途 cancel 漏關 httpx 連線 | try/finally + `aclose`/`close` getattr(版本兼容) |
| Bash 既有 watch_abort 路徑被新 helper 取代後 regression | 不動 Bash,只在新 site 套用 helper(設計決策 #8);Bash 既有測試全綠 |
| Grep Python fallback 卡 CPU 完全不能 abort | 每 32 個檔案讓出 event loop + 檢查 abort_event(設計決策 #7) |
| Windows CLI 沒 SIGINT graceful 路徑 | `_install_sigint_handler` 對 NotImplementedError/RuntimeError 走 fallback,Python 預設 KeyboardInterrupt 仍能停 |
| 兩段式 Ctrl-C 第二次 `os._exit(130)` 跳過清理 | 故意 — 5 秒已給足 graceful 機會,卡死 task 必須強制終止(對應 TS Claude Code 同樣模式) |
| StreamingToolExecutor 內部 tool 不在 abort 範圍 | `abort_aware_scope` 包在 executor 外層,CancelledError propagate 到 executor `__aexit__` 連動取消所有 tool task |

---

## 內部對應 plan 的差異

| Plan 章節 | 差異 | 為何 |
|---|---|---|
| § 2.1 「query_loop._run_one_turn 在 provider.stream(...) 外加一層 async with anyio.CancelScope」 | 不直接用 raw CancelScope,改抽 `abort_aware_scope` ctx manager | 同一 pattern 要在 webfetch / grep / future 工具重用,避免每處重寫 task group + watcher |
| § 2.2 「signal.signal(SIGINT, ...) 或 anyio signal handling」 | 用 asyncio `loop.add_signal_handler` | asyncio event loop 友善;signal.signal 在 thread 限制多 |
| § 2.3 GrepTool Python fallback chunk-yield | 改成 「每 32 檔 sleep(0) + 檢查 abort」 | 比 chunk-yield 更輕量;真正昂貴是 file IO + regex,而非 yield 開銷 |
| § 2.3 AgentTool 子 query_loop | **不動**(已天然有 turn 邊界檢查,plan 自述) | 子 query_loop 進入 `_run_one_turn` 後也會被 outer abort_aware_scope 覆蓋(parent ctx 共享 abort_event)|

---

## 實作中發現的坑

### 1. abort_aware_scope finally 不能直接 cancel scope
詳見設計決策 #2。第一版 callers 全錯,跑 `pytest tests/unit/tools/test_web_fetch.py`
直接看到 `aborted fetching ...` 取代正常回應 — 立刻知道 helper 行為錯。修完才綠。

### 2. abort_aware_scope nesting 順序很重要
`abort_aware_scope` 必須包在 `StreamingToolExecutor` **外面**,否則 abort 時 executor
內部 task 不會被連動 cancel。改 nesting 順序後 abort 測試從等 10 秒掉到 < 1 秒。

### 3. async generator + task group 沒問題(但別早退)
原本擔心 `_run_one_turn` 是 async generator,內含 `async with create_task_group()`(在
`abort_aware_scope` 裡),consumer 早退會出事。實測 query_loop 一定會 iter 到結束才 break,
無 GC 問題。為防未來新 caller 中途 break,API 不引入「partial drain」介面 — 都用
`async for ... in query_loop(...)` 跑到 LoopTerminated。

### 4. OpenAI stream 對 cancel 沒 idempotent close
試了好幾版 SDK,aclose 在不同版本是 `aclose()` 或 `close()`,且 cancel 中重複 close 可能
raise。最後用 try/except 吃 close 例外(避免 secondary failure 蓋過原 CancelledError)。

### 5. Ctrl-C handler 不能 set abort_event 後 raise
signal handler 是 sync function;raise 不會被 asyncio loop 接住、會留在訊號 frame。
正確做法:handler 純 `ctx.abort_event.set()`,讓 query_loop 自己看 event 決定退出。
強制終止用 `os._exit`(繞過 Python cleanup 直接 syscall)。

# Phase 1b — 補完 Phase 1 留下的小債

**完成日期**:2026-05-07
**前置**:Phase 1(commit `344c9df`)+ Phase 2(commit `5709a26`)
**狀態**:✅ make check 全綠 + 真實並行 demo 跑通

Phase 1 完工時留下三個 TODO,本次補完。

---

## 交付清單

| Phase 1 留下的 | 本次處理 |
|---|---|
| StreamingToolExecutor 接到 query_loop 主路徑(原 spec 說「Week 4 重構」)| ✅ `_run_one_turn` 改用 executor;模型 yield ToolUseStop 立即 `add_tool` 開跑;stream 結束後 `drain` |
| BashTool 觸發 sibling_abort,中止並行兄弟 | ✅ `StreamingToolExecutor.sibling_abort: anyio.Event`,non-safe 工具 ErrorEvent 時 set,queued 工具 skip + synthetic error |
| Conversation.stats 累積 input/output_tokens | ✅(其實已在 Phase 2 conversation.py 重寫時順手加 — `AssistantTurnComplete` 會被觀察並累計) |

---

## 改動的檔

```
core/query_loop.py              _run_one_turn 重構為 streaming-with-executor
core/streaming_executor.py      新增 sibling_abort + 在 _run_tool 觸發 / 檢查邏輯
tests/unit/core/test_streaming_executor.py  +3 測試(sibling abort 三場景)
```

`run_tools(...)` 批次模式仍保留(`tool_orchestration.py`),作為 fallback / 直接 use-case。
`query_loop` 預設走 streaming。

---

## 驗證

### Static + tests

| 檢查 | 結果 |
|---|---|
| `ruff check` | ✅ |
| `mypy --strict` | ✅ no issues found in 54 source files |
| `pytest tests/unit/` | ✅ **145 passed**(142 → 145,+3 sibling abort) |

### 並行工具 demo(Anthropic)

```
> List .py files in src/orion_agent/core/ AND simultaneously grep for 'class' in main.py — do these in parallel

[Glob] **/*.py 找 9 個檔
[Grep] 'class' in main.py — no matches
2 turns, 2 tools, no errors, in=5817 out=326
```

兩個 concurrency-safe 工具(Glob + Grep)由 executor **同時** add_tool,並行跑。
結果按 add 順序 yield。

---

## 關鍵設計細節

### Sibling abort 觸發條件

只在以下三條件**同時**滿足時 set sibling_abort:
1. `isinstance(upd, ToolResultUpdate) and upd.is_error`(該工具最後 yield 是錯誤)
2. `not tt.is_concurrency_safe`(該工具是 non-safe,例 Bash / Edit / Write / TodoWrite / Agent)
3. `tt.block.name in self.tools_by_name`(該工具確實註冊過 — 排除「unknown tool」synthetic error)

第 3 條是踩坑修出來的 — 本來「unknown tool」也會觸發,實測一個小心拼錯的 tool name
就會關掉同 batch 所有並行兄弟,不合理。Synthetic 錯誤(unknown / invalid input / permission deny)
是 caller 給的爛 input,不該因此 cascade。**只有「真實非並發安全工具在執行時錯了」才觸發**。

### query_loop 改動的等效性

舊 batch 模式(`run_tools` after stream):
```
stream → 累積 tool_uses → run_tools(全部後)→ yield results 按原順序
```

新 streaming 模式(executor):
```
stream → tool_use 一個就 add_tool 立即跑 →
  stream 結束 → drain 按 add 順序 yield results
```

對 caller 而言,**事件順序完全一致** — 都是「先 stream events → AssistantTurnComplete → 工具 results」。
差別只在「工具開始跑的時間點」:streaming 模式下,模型還在 stream 文字時,前面的工具就已經開始跑了。
真實 latency 改善視 model output token 數而定;短 turn 看不出來,長 turn(高 reasoning)會明顯。

---

## 留下的小債(留給 Phase 3 / 後續)

- 中途 abort:目前 `ctx.abort_event.is_set()` 只在 turn 邊界檢查;tool 執行中按 ctrl-C 不會立即停。
  Phase 3 / Phase 7 加 cancel scope 整合
- Sibling abort 只 abort **queued** 工具,沒辦法中止已 running 的。Streaming + cancel scope 後可加
- run_tools 批次模式如今沒人用 — 是否該移除?**保留**:純函數,適合單元測試;同時也是 spec 對照
  教材(對應 TS toolOrchestration.runTools)。零 maintenance 成本

---

## 數字

| | 值 |
|---|---|
| 修改源檔 | 2 |
| 新測試 | 3 |
| 累計測試 | 145 全綠 |
| 從 Phase 2 commit 到 Phase 1b 完工 | ~15 分鐘 |

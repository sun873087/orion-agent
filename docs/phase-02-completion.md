# Phase 2 — Storage / Resume 完工記錄

**完成日期**:2026-05-07
**Spec doc**:`docs/phases/02-storage-state.md`
**狀態**:✅ make check 全綠 + 真實 demo 寫 transcript + resume 跑通

---

## 交付清單

```
orion-agent/api/src/orion_agent/storage/        [全新]
├── __init__.py
├── paths.py                            per-session 路徑(預設 ~/.orion/sessions/<id>/)
├── tool_result.py                      第 2 層持久化(>100KB 寫檔 + preview)
├── replacement_state.py                第 3 層 budget(三類分流 + select largest)
├── file_history.py                     寫前 SHA256 快照
├── session.py                          JSONL transcript writer + reader(anyio.Lock)
├── resume.py                           load_session + reconstruct ContentReplacementState
└── mcp_output.py                       stub(Phase 5 才實作 binary)

修改的既有檔:
├── core/state.py                       AgentContext 加 replacement_state 欄位
├── core/conversation.py                整支重寫:加 session_id、persistence_enabled、
│                                       replacement_state、SessionStorage 整合、
│                                       Conversation.resume() 類別方法
├── core/query_loop.py                  每 turn 進 API 前 apply_tool_result_budget
├── core/tool_execution.py              tool 完成時 maybe_persist_large_tool_result
├── tools/file/write.py                 寫前 make_snapshot
├── tools/file/edit.py                  寫前 make_snapshot
└── main.py                             CLI 加 --resume <session-id> + --no-persistence
```

### Tests

```
tests/conftest.py                       autouse fixture isolate ORION_SESSIONS_DIR 到 tmp
tests/unit/storage/                     [全新,7 檔 32 測試]
├── test_paths.py                       4 tests
├── test_persist_size_threshold.py      6 tests(threshold boundary、preview truncate)
├── test_replacement_state.py           7 tests(三類分流、select_fresh、apply_budget)
├── test_file_history.py                4 tests(snapshot existing、dedupe by hash)
├── test_session.py                     5 tests(round-trip、並發寫不交錯、損壞行跳過)
├── test_resume.py                      3 tests(restore messages、reconstruct state)
└── test_conversation_persistence.py    4 tests(寫 transcript、resume 接續、disable)
```

---

## 驗證結果

### 靜態檢查全綠

```bash
make check
```

| 檢查 | 結果 |
|---|---|
| `ruff check` | ✅ All checks passed |
| `mypy --strict` | ✅ no issues found in 54 source files |
| `pytest tests/unit/` | ✅ **142 passed**(110 既有 + 32 Phase 2)|

### 真實 demo

#### Turn 1:寫 transcript

```bash
$ uv run orion --provider anthropic --model claude-sonnet-4-6 \
    "Use Bash to run 'echo first'"

=== orion-agent (anthropic / claude-sonnet-4-6) session=22654bc6-... ===
  ✓ Bash (id=toolu_01Q3...): $ echo first  [exit 0]  first
The command ran successfully and output: **first**
--- loop terminated: natural_stop (turns=2) ---
```

`~/.orion/sessions/22654bc6-.../transcript.jsonl` 含 5 行 JSON:
- `session-meta`(provider、model、system_prompt)
- `message`(role=user, "Use Bash to run 'echo first'")
- `message`(role=assistant, tool_use_block)
- `message`(role=user, tool_result_block)
- `message`(role=assistant, "The command ran successfully...")
- `transition`(reason=natural_stop, turns=2)

#### Turn 2:resume 對同 session 繼續

```bash
$ uv run orion --resume 22654bc6-... --provider anthropic \
    --model claude-sonnet-4-6 \
    "What did you just run? One short sentence."

=== resumed session 22654bc6-... (4 prior messages) ===
I ran `echo first`, a shell command that prints the word "first" to standard output.
--- loop terminated: natural_stop (turns=1) ---
```

模型正確回想起前一次 session 跑了什麼。`final_messages` 在第二次跑後含 6 則(原 4 + 新 user + 新 assistant)。

---

## 三層 Tool Result 結構

| 層 | 範圍 | 觸發條件 | 動作 |
|---|---|---|---|
| **1**(in-memory) | 工具個別結果 | 全部 | 工具自己有 `max_result_size_chars` 檢查,超過才考慮持久化 |
| **2**(disk persisted) | 單一工具 ≥ 100KB | tool_execution 完成時 | 寫到 `tool-results/<id>.txt`,回填內容換成 `<persisted-output>` envelope(2KB preview) |
| **3**(budget aggregate) | 所有 tool_result 累積 | 進 API 前(query_loop) | 用 ContentReplacementState 三類分流(must_reapply / frozen / fresh),挑最大的 fresh 替換到回到 200KB budget |

決策不可逆:fresh → frozen / must_reapply 後**永不變動**(維持 prompt cache byte-identical 命中)。

---

## 與 spec doc 的差異

| 項目 | spec | 實作 | 為何 |
|---|---|---|---|
| 模組命名 | `claude_agent_py` | `orion_agent` | 沿用 Phase 0 的命名 |
| `mcp_output.py` | 完整實作 | stub(Phase 5 才用) | 沒人 import,先佔位 |
| Resume 後 prompt cache 命中觀察 | spec 列為驗收條件 | 跑了但沒驗證(要看 anthropic SDK 的 cache_read_input_tokens) | Phase 2 主要目標(寫 transcript / 重建 state)已達成,prompt cache 觀測延後 |
| File history undo CLI 命令 | spec 沒明說 | 沒做 — 只有 snapshot,沒有 undo 命令 | 需要 user-facing UI,延後 |

---

## 實作中發現的細節 / 坑

### 1. `datetime.utcnow()` 在 Python 3.12 已 deprecated

第一次跑出 100+ 個 deprecation warning。
**改用 `datetime.now(UTC)`**,Python 3.11+ 才有 `from datetime import UTC`。

### 2. ContentReplacementState 必須跨 turn 共用,所以放 AgentContext

原本想塞在 query_loop 內部,但 query_loop 是無狀態 generator,每次呼叫都 reset。
改放 **AgentContext.replacement_state**(每 conversation 一個)。Conversation 在 send() 時把
`self.replacement_state` 設到 `ctx.replacement_state`,query_loop 就能讀。

### 3. anyio.Lock + nested async with 會被 ruff SIM117 擋

```python
# 原本(被擋)
async with self._lock:
    async with await anyio.open_file(...) as f:
        await f.write(line)

# 改成
async with (
    self._lock,
    await anyio.open_file(...) as f,
):
    await f.write(line)
```

Python 3.10+ 的 parenthesized context managers 解決得很乾淨。

### 4. ContentReplacementState 序列化進 transcript:不寫整個 state,只寫 decisions

state 內含 set / dict,JSONL 化後 round-trip 麻煩。**改寫 ReplacementDecision(tool_use_id + replacement)**,resume 時掃 records + messages 重建 seen_ids。Decision 是「一次新增」的紀錄,frozen 的 ID 不會重新出現在 records 裡(由 messages 推得)。

### 5. Conversation 的 _session_storage 型別

mypy strict 看到 `_session_storage: object | None` 後,所有 `self._session_storage.record_*` call 都報「object 沒這 method」。**直接 typed 成 `SessionStorage | None`** — 上層 import 不會循環(SessionStorage 沒 import Conversation)。

### 6. Auto-fixture 設 ORION_SESSIONS_DIR 防污染家目錄

如果 test 不小心寫到 `~/.orion/sessions/<random-uuid>/`,就會留下垃圾。
**conftest.py 用 autouse fixture 強制 monkeypatch 到 tmp_path**,所有 test 自動隔離。

### 7. iter_records_sync 跳過損壞行

spec 踩雷 #3 提到 process 可能寫一半死掉,留下損壞 JSON 行。
**`iter_records_sync` try/except json.JSONDecodeError 跳過**,確保 resume 不被半行 kill。

---

## Phase 2 為後續鋪好的基礎(回顧)

| 後續 phase 將用到本 phase 的 | 說明 |
|---|---|
| Phase 3(memory / compaction)| ContentReplacementState 與 compaction 共用 messages 重寫機制;Phase 3 spec 會驗證兩者不踩腳 |
| Phase 5(MCP)| `storage/mcp_output.py` stub 已備,Phase 5 接 binary persistence |
| Phase 6(FastAPI)| transcript JSONL 已穩定,Phase 6 加 `/sessions` 列表 + `/sessions/<id>/transcript` 端點 |

實作中觀察到的延後優化(均升級為獨立 phase plan):

- File history GC → [`docs/phases/plan/19-file-history-gc.md`](phases/plan/19-file-history-gc.md)
- Transcript JSONL gzip → [`docs/phases/plan/20-transcript-compression.md`](phases/plan/20-transcript-compression.md)

---

## 數字總結

| 指標 | 值 |
|---|---|
| 新增源檔 | 8(storage/ 7 + 修改的既有檔) |
| 新增測試檔 | 7 |
| 新增測試案例 | 32 |
| 累計測試總數 | **142**(全綠) |
| Static check | ✅ 全綠 |
| 真實 demo | ✅ transcript 寫對 + resume 接續對話 |
| 從 Phase 1 commit 到 Phase 2 完工 | ~30 分鐘 |

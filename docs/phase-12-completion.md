# Phase 12 — Internal Mechanics 完工記錄

**完成日期**:2026-05-08
**Plan doc**:`docs/phases/12-internal-mechanics.md`
**狀態**:✅ `make check` 全綠 — **624 unit tests passed, 2 skipped**(11.45s),
ruff clean,mypy --strict 179 files clean。

Phase 11 → Phase 12 新增 **66 unit tests**(side_query 8 / forked_agent 7 /
plan_mode state 11 / plan_mode restrictions 7 / plan_mode tools 6 / app_state 9 /
file_state 18)。2 個 skip 是 Phase 7 的 docker_backend(需 docker daemon,既有 skip,
非 Phase 12 引入)。

---

## 交付清單

### 新增模組

```
src/orion_agent/
├── services/
│   ├── side_query.py                [新] 通用小 LLM 呼叫,不汙染主對話
│   ├── forked_agent.py              [新] CacheSafeParams + run_forked_agent
│   └── file_state.py                [新] FileStateCache + require_fresh_read
│
├── plan_mode/                       [全新,3 檔]
│   ├── __init__.py
│   ├── state.py                     PlanModeState/Status + enter/submit/approve/reject
│   └── restrictions.py              PLAN_MODE_ALLOWED_TOOLS + plan_mode_aware wrapper
│
├── state/                           [全新,2 檔]
│   ├── __init__.py
│   └── app_state.py                 ToolPermissionContext + IDEContext + AppState
│
└── tools/special/
    ├── enter_plan_mode.py           [新] EnterPlanModeTool
    └── exit_plan_mode.py            [新] ExitPlanModeTool
```

### 修改既有檔

```
src/orion_agent/
├── core/
│   ├── state.py                     AgentContext 加 plan_mode_state /
│   │                                 file_state_cache / app_state(都 object | None)
│   └── conversation.py              Conversation 加 file_state_cache 欄位 +
│                                     send() 注入到 ctx
├── memory/relevance.py              _llm_rank 改走 services.side_query(JSON Schema)+
│                                     刪掉本地 _provider_complete
├── tools/agent/agent_tool.py        AgentTool.call 改走 services.forked_agent
│                                     run_forked_agent(統一 fork 入口)
├── tools/file/read.py               Read 完成後 record_read 進 ctx.file_state_cache
├── tools/file/edit.py               Edit 前 require_fresh_read,寫完更新 snapshot
├── tools/file/write.py              Write 覆寫既有檔同 Edit;新建檔免 Read
└── tools/special/__init__.py        export EnterPlanModeTool / ExitPlanModeTool
```

### Tests(新增 7 檔,共 66 案例)

```
tests/unit/services/
├── test_side_query.py               8 tests(text mode / schema tool_use / fallback /
│                                            captured_calls / usage / invalid json /
│                                            tools=None / tools=[respond])
├── test_forked_agent.py             7 tests(基本 / byte-identical prefix /
│                                            mutation 隔離 / depth / usage / 
│                                            CacheSafeParams immutable / 父 abort 隔離)
└── test_file_state.py               18 tests(record / stale / unread / nonexistent /
                                              invalidate / `in` / require_fresh_read /
                                              Read+Edit / external mod / re-edit /
                                              Write 新檔 / Write 覆寫 / 無 cache / snapshot frozen)

tests/unit/plan_mode/                [全新]
├── __init__.py
├── test_state.py                    11 tests(三態轉換 / enter/submit/approve/reject 全 happy + sad / frozen)
└── test_restrictions.py             7 tests(白名單 / inactive 全允許 / awaiting 全 deny /
                                              wrapper passthrough / wrapper 拒寫 / 拒所有 / 尊重 inner deny)

tests/unit/state/                    [全新]
├── __init__.py
└── test_app_state.py                9 tests(default / grant / dedup / deny / bypass /
                                              additional cwd / mcp status / IDE 預設 / frozen)

tests/unit/tools/special/test_plan_mode_tools.py
                                     6 tests(enter / 重複 enter / 未 enter exit /
                                              ACTIVE → AWAITING / 空 plan / 二度 exit)
```

---

## 設計決策

### 1. side_query 用 LLMProvider 介面而非直接 anthropic SDK

對應 spec 「不直接呼 anthropic SDK」。透過既有 `LLMProvider.stream` 介面跑,
Anthropic / OpenAI / MockProvider 都可用。JSON Schema 強制輸出走 `tools=[...]` +
模型 emit `ToolUseStopEvent`(等同 TS 的 `tool_choice` 強制路徑);provider 不支援
就 fallback 解 text JSON。

### 2. CacheSafeParams 是 fork 時的 immutable snapshot

`from_parts(...)` 用 `list(...)` 淺拷貝;之後父 `state_messages.append(...)` /
`tools.append(...)` 不會破壞 fork 已 capture 的 prefix。`NormalizedMessage` 是
Pydantic value object,不需 deep copy。

### 3. AgentTool 改走 forked_agent — 子 agent 仍用獨立 system

`AgentTool` 重構成 `run_forked_agent` caller,但傳的 `cache_safe.system_prompt` 是
`_SUB_AGENT_SYSTEM_PROMPT`(獨立),`messages_prefix=[]`。意思:**取 fork 機制**
(獨立 ctx / sandbox / hook),**不取 cache 命中**(子 agent 跟父對話不分享 prefix)。
等 caller 真有「共享 prefix 的 fork」需求(例如 background extract 還需要看父對話),
就傳同 system + parent.state_messages 進 CacheSafeParams 即可。

### 4. Plan mode 三態而非 boolean

- `INACTIVE`:正常,工具不限
- `ACTIVE`:read-only 白名單(Read/Grep/Glob/WebFetch/WebSearch/TodoWrite/ExitPlanMode)
- `AWAITING_APPROVAL`:**所有**工具 deny(包括 read-only)— 等 user 按鈕

對應 TS planModeV2 設計。`AWAITING_APPROVAL` 中即使 Read 也擋,避免模型在「已 submit」
後又繼續做事(語意上 plan 是「我講完了等你」)。

### 5. plan_mode_aware 是 CanUseToolFn decorator

```python
wrapped = plan_mode_aware(my_can_use_tool)
```

放在 policy chain 最外層;plan mode 通過後才丟給 inner。Conversation 不需要硬寫
plan mode 邏輯 —— caller 想接就接。

### 6. file_state cache 用 mtime + size,不算 hash

對應 spec § 6 「為何 file state cache 不直接用 mtime 比?」`mtime + size` 是 80/20 解。
完全準確要 SHA-256,但每次 stat 又要 hash 太貴。Phase 12 範圍接受偶有 false positive
(touch 過但內容沒變 — 模型重 Read 一次而已,代價低)。

### 7. file_state cache 是 ctx-injected,不是 mod-level singleton

`ctx.file_state_cache: object | None`;Conversation.send() lazy 建立並注入。
單元測試可以建 `AgentContext(file_state_cache=cache)` 隔離測,工具直接看 ctx 拿,
不要 import module-level state。

### 8. Edit / Write 完成後**更新 snapshot**(不是 invalidate)

第 2 次 Edit 不該被當作 stale。所以 `path.write_text(...)` 之後立刻
`cache.record_read(path)` 重 stat。不選 invalidate 是因為那會強迫模型
連 read 兩次才能連 edit 兩次,徒增工作量。

### 9. AppState 跟 AgentContext 分層

| 層級 | 生命週期 | 內容 |
|---|---|---|
| `AgentContext` | per-`Conversation.send()`(短) | abort / cwd / sandbox / per-turn 資源 |
| `AppState` | per-Conversation(長) | 權限歷史 / IDE / MCP 健康 / pending attachments |

`AppState` 子欄位(`ToolPermissionContext` / `IDEContext`)是 frozen dataclass —
要更新只能 `replace(...)`。outer `AppState` 是可變容器,直接 mutate 子欄位 ref。

### 10. ToolPermissionContext 用 tuple 而非 list 存 patterns

frozen dataclass + tuple → 整體真的 immutable。改 grant 必經 `with_grant(...)` 回新
context,不會被誤改。

---

## REST API 變更

無。Phase 12 全是內部機制,不動 endpoint。

---

## 環境變數

| Env | 用途 |
|---|---|
| `ORION_HOME` | EnterPlanModeTool 的 plan_dir 預設位置(`$ORION_HOME/plans/`,
  缺時用 `~/.orion/plans/`)。沿用既有 Phase 11 同 env。 |

---

## Verification

```bash
cd orion-agent/api/

make check
# → ruff All checks passed!
# → mypy --strict: 179 files, 0 issues
# → pytest: 624 passed, 2 skipped(11.45s)
#   (2 skipped = docker_backend,既有 Phase 7 skip,需 docker daemon)

# side_query 跑通驗證
.venv/bin/python -c "
import asyncio, sys
sys.path.insert(0, 'tests')
from conftest import MockProvider, MockTurn
from orion_agent.services.side_query import SideQueryParams, side_query
provider = MockProvider(turns=[MockTurn(text='hello world')])
async def main():
    r = await side_query(SideQueryParams(system='s', user_text='u'), provider=provider)
    print('text:', r.text, 'usage:', r.usage)
asyncio.run(main())
"
# 預期:text: hello world  usage: SideQueryUsage(input_tokens=10, ...)

# Plan mode 工具 + 限制驗證
.venv/bin/python -c "
import asyncio
from orion_agent.core.state import AgentContext
from orion_agent.permissions.decisions import always_allow
from orion_agent.plan_mode.restrictions import plan_mode_aware
from orion_agent.plan_mode.state import PlanModeState, PlanModeStatus, enter_plan_mode
from pathlib import Path

class T:
    name = 'Edit'

ctx = AgentContext()
ctx.plan_mode_state = enter_plan_mode(PlanModeState(), plan_dir=Path('/tmp/p'))
wrapped = plan_mode_aware(always_allow)
res = asyncio.run(wrapped(T(), {}, ctx))
print(res.decision, '-', res.reason)
"
# 預期:PermissionDecision.DENY - Plan mode is active — 'Edit' is not in the read-only allow list...

# File staleness 驗證
ORION_FILE=/tmp/orion-fs-test.txt
echo "original" > $ORION_FILE
.venv/bin/python -c "
import asyncio, time, os
from pathlib import Path
from orion_agent.core.state import AgentContext
from orion_agent.services.file_state import FileStateCache
from orion_agent.tools.file.edit import FileEditTool, FileEditInput

cache = FileStateCache()
cache.record_read(Path('$ORION_FILE'))
# 模擬外部修改
time.sleep(0.01)
Path('$ORION_FILE').write_text('changed')
os.utime('$ORION_FILE', (time.time()+1, time.time()+1))

ctx = AgentContext(file_state_cache=cache)
async def main():
    async for ev in FileEditTool().call(FileEditInput(path='$ORION_FILE', old_string='changed', new_string='x'), ctx):
        print(type(ev).__name__, getattr(ev, 'message', getattr(ev, 'text', '')))
asyncio.run(main())
"
# 預期:ErrorEvent <message 含 modified externally / re-read>
rm $ORION_FILE
```

---

## Tests 摘要

| Suite | 數量 | 說明 |
|---|---|---|
| Phase 0–11 既有 | 558 | 全綠不動(含 AgentTool 重構過後 3 案仍 pass) |
| **Phase 12 services** | 33 | side_query 8 + forked_agent 7 + file_state 18 |
| **Phase 12 plan_mode** | 18 | state 11 + restrictions 7 |
| **Phase 12 state** | 9 | app_state |
| **Phase 12 plan_mode tools** | 6 | enter/exit |
| **總計** | **624 passed / 2 skipped** | mypy --strict 179 files / ruff 全綠 |

---

## 風險與已緩解

| 風險 | 緩解 |
|---|---|
| side_query 用 LLM API 共享 rate limit pool | 預留 `query_source` 標籤;production 接 dedicated key by source 即可 |
| forked_agent cache miss(byte-identical 細節) | CacheSafeParams.from_parts 用 list 拷貝鎖住 capture;system_prompt 走 list[str] 模式時 Anthropic provider 自動加 cache_control |
| AgentTool 改 forked_agent 後行為退化 | 既有 3 案 test_agent_tool 全綠(text 結果 / depth limit / self-ref filter) |
| Plan mode 子 agent 繼承問題 | 故意**不**繼承 — `fork_context_for_subagent` 建新 ctx,plan_mode_state=None。子 agent 有自己的 plan mode 生命週期 |
| File staleness false positive(touch 但內容沒變) | mtime + size 抓 80%;誤判時模型只是重 Read 一次,代價極低 |
| Edit 後 cache 未更新導致 staleness | Edit / Write 成功後立刻 `cache.record_read(path)` 重 stat → 第 2 次 Edit 不會被擋 |
| Write 新檔被誤要求 Read | `existed = path.exists()` 在 staleness check 之前判斷;新建檔(existed=False)直接跳過 |
| AppState 並發 mutate 競爭 | 子欄位 frozen + with_xxx 回新 instance;outer dict / list 是單一 Conversation 內,FastAPI 各 session 隔離 |
| `ctx.plan_mode_state` 直接 mutate 在 EnterPlanModeTool 裡(不是 immutable) | 有意:Tool 是寫狀態的 owner,純 immutable 對 caller 太繁;policy wrapper / 讀取者用 isinstance + 不假設 frozen |
| EnterPlanMode 工具被排除在 plan mode 白名單外 | EnterPlanMode 通常只在 INACTIVE 觸發;若已 ACTIVE 則 tool 自己回 ErrorEvent。即使白名單沒它,也不會卡死 |

---

## 內部對應 spec 的差異

| Spec § | 差異 | 為何 |
|---|---|---|
| 5.1 side_query 用 anthropic.AsyncAnthropic | 改用 `LLMProvider.stream` | orion-agent provider-agnostic 約束。換 OpenAI 也能用 |
| 5.2 forked_agent.run_forked_agent 加參數 `parent_conv` | 拆成 `parent_ctx` + `CacheSafeParams` | 顯式分離 fork 機制(ctx)與 cache 內容(params),測試/重用更乾淨 |
| 1.3 整合 Phase 3 select_relevant_memories | ✓ 已改用 side_query + JSON Schema | — |
| 1.5 整合 Phase 3 extract_memories | 維持原本 `_provider_complete` 路徑 | extract_memories 是「對話結束後 single LLM call」,沒跑 query_loop / 工具,改 forked_agent 過度。目前 try/except 隔離已足。**不另外開 phase plan**(刻意決策,非延後) |
| 2.5 AppState 詳細模型 | 簡化為 dataclass + immutable update,不做 Redux | spec § 6「Python backend 不需要 Redux 全套」 |
| 整合 Conversation / can_use_tool 用 plan_mode_aware | 提供 wrapper,不強制 Conversation 套用 | 由 caller 決定何時包;Conversation 預設用原 can_use_tool 維持向後相容 |

---

## 實作中發現的坑

### 1. `ToolUseStopEvent.full_input` 是 dict[str, Any]

side_query JSON Schema 路徑要 narrow 成 dict 才能存進 `structured` 欄位。直接拿
也 OK 但 mypy --strict 不喜歡。`isinstance(ev.full_input, dict)` 顯式檢查通過。

### 2. SIM102 nested if 規則

ruff 的 `SIM102 Use a single if instead of nested if` 兩處需要合併:

```python
# 不行:
if isinstance(plan_state, PlanModeState):
    if not is_tool_allowed_in_plan_mode(...):
        ...

# OK:
if isinstance(plan_state, PlanModeState) and not is_tool_allowed_in_plan_mode(...):
    ...
```

mypy 對 `and` 後 narrow 的型別也認得,`plan_state.status` 在分支內仍可訪問。

### 3. `from_parts(... messages=parent_msgs)` 必須 `list(...)` 拷

否則 caller 之後 `parent_msgs.append(...)` 會破壞 capture。**這個從 forked_agent
test「mutation 隔離」抓出來的**,沒寫測試前一度直接傳 ref。

### 4. EnterPlanModeTool 寫 plan_dir 時可能踩 mkdir 失敗

`OSError` 包起來回 ErrorEvent — 不要 raise 進 query_loop(會中斷整輪)。

### 5. mypy 1.x 要求 `from __future__ import annotations` 才能用 `Path | None`

新建檔記得加(每個檔開頭已加),避免老系統踩 PEP 604 不支援。

### 6. ruff `ARG002` 對 unused tool input

EnterPlanModeInput 是空 schema,call 簽名 `input: EnterPlanModeInput` 故意收但不用 →
`# noqa: ARG002`。原本想用 `Any` 簡化但 Tool Protocol 要型別精確。

### 7. mypy cache 在 reinstall 後可能 corrupt

`uv pip install -e . --reinstall` 後第一次 `mypy --strict` 偶爾 crash with
`sqlite3.DatabaseError: database disk image is malformed`。**`rm -rf .mypy_cache`
後重跑即正常**。Phase 1 手記寫過 iCloud sync 對 .venv 的鬼影,這次是 mypy 的 SQLite 也會。

### 8. AgentTool 重構後 hook 順序

原本 `fork_context_for_subagent` 在 hook fire 之前(用 child session_id);改 forked_agent
之後 fork 內部生 ctx,要 hook 用的 session_id 必須**先生**(`uuid4()` 提前),fire 時帶這個
str id,之後 forked_agent 內部會建另一個 ctx 用自己的 session_id。**hook event 中的
session_id 可能跟最終 child ctx 不同**(目前可接受,hook 主要是 SubagentStart 通知,
不依賴 ID 對應後續訊息)。

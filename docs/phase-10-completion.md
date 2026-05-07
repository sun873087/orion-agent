# Phase 10 — Tools + Performance 完工記錄

**完成日期**:2026-05-07
**Plan doc**:`docs/phases/10-tools-performance.md`(範圍 C:核心 6 工具 + Task/Cron 9
工具 + perf 兩模組;**不含** stress test / capacity planning,留 Phase 10c。)
**狀態**:✅ `make check` 全綠 — **499 unit tests passed, 0 skipped**(17s),
ruff clean,mypy --strict 156 files clean。

---

## 交付清單

### 新增工具(共 17 個,主清單 26 個)

```
src/orion_agent/tools/
├── special/                              [全新,3 工具]
│   ├── tool_search.py                    ToolSearchTool — deferred 機制
│   ├── synthetic_output.py               SyntheticOutputTool — SDK structured output
│   └── sleep.py                          SleepTool — autonomous agent 延遲
├── config/                               [全新,1 工具]
│   └── config_tool.py                    ConfigTool — 讀寫 ~/.orion/settings.json
├── interactive/                          [全新,1 工具]
│   └── ask_user.py                       AskUserQuestionTool + make_stdin_asker / make_ws_asker
├── file/
│   └── notebook_edit.py                  [新] NotebookEditTool — Jupyter cell ops
├── task/                                 [全新,6 工具 + runner]
│   ├── runner.py                         BackgroundTaskRunner(in-memory + asyncio.Task)
│   ├── task_create.py
│   ├── task_get.py
│   ├── task_list.py
│   ├── task_update.py
│   ├── task_stop.py
│   └── task_output.py
└── cron/                                 [全新,3 工具 + scheduler]
    ├── scheduler.py                      CronScheduler(APScheduler AsyncIOScheduler 包裝)
    ├── cron_create.py
    ├── cron_list.py
    └── cron_delete.py
```

### 新增 perf 模組

```
src/orion_agent/perf/                     [全新]
├── __init__.py
├── subprocess_pool.py                    SubprocessPool(async-friendly,size=4 workers,
│                                          fallback fork + stats)
└── profiler.py                           pyinstrument 包裝(profile_sync / profile_async +
                                          render_profile)
```

### 修改既有檔

```
src/orion_agent/main.py                   _build_tools 加 17 個新工具(+ ToolSearch
                                          自我感知全 list,deferred 機制)
pyproject.toml                            apscheduler / pyinstrument / nbformat
                                          mypy override 加 4 個 untyped 套件
```

### Tests(全新,11 檔,共 55 案例)

```
tests/unit/tools/
├── special/
│   ├── test_tool_search.py        6 tests(select / keyword / required / no-match)
│   ├── test_synthetic_output.py   2 tests(record last_output / extra fields)
│   └── test_sleep.py              2 tests(abort interrupt / min seconds clamp)
├── config/
│   └── test_config_tool.py        10 tests(get/set/delete/list + dot-path + invalid JSON)
├── interactive/
│   └── test_ask_user.py           5 tests(no asker error / fake asker / ws round-trip / timeout)
├── file/
│   └── test_notebook_edit.py      6 tests(replace / insert / delete / 缺檔 / 索引超過 / clear outputs)
├── task/
│   ├── test_runner.py             10 tests(create / start command / stop / list filters / metadata)
│   └── test_tools.py              4 tests(6 tools chained happy path + edges)
└── cron/
    └── test_cron_tools.py         3 tests(create→list→delete / 無效 expr / 不存在 id)
tests/unit/perf/
├── test_subprocess_pool.py        4 tests(echo / exit / timeout / stats)
└── test_profiler.py               3 tests(sync / async / color)
```

---

## 設計決策

### 1. ToolSearch:deferred 機制 + self-aware 全 list

```python
# main.py 結尾
base.append(ToolSearchTool(all_tools=base))
```

ToolSearch 拿同一個 list 引用,模型呼 `select:` / keyword search 時當下查最新工具集
(包括 plugin / MCP 動態加進來的)。query 形式:
- `select:Name1,Name2`(精確)
- `keyword`(name + description 模糊)
- `+keyword1 keyword2`(`+` 強制要符合)

**should_defer = True** 屬性目前只是 metadata,Phase 10c 才把 system prompt
真的省掉(對應 docs/08 cache 失效成本最佳化)。

### 2. SyntheticOutputTool:caller 動態 schema

```python
class MyResult(BaseModel):
    findings: list[str]
    verdict: str

tool = SyntheticOutputTool(schema=MyResult)
conversation.tools = [tool]
# ... LLM emit tool_use → tool.last_output = parsed dict
result = tool.last_output  # caller 拿
```

不執行 side effect,純存最後一次 input。caller 加 system prompt 提示模型「以
SyntheticOutput 結束」。

### 3. SleepTool:`anyio.Event.wait()` + `move_on_after` 雙重

模型呼 sleep 時:
- 等 `ctx.abort_event` set(被 user 中止 → 立即繼續)
- OR 等 N 秒(`anyio.move_on_after(seconds)`)

實測 abort 中斷 < 1 秒(unit test 跑 0.1s 可中斷 3600s 預定 sleep)。範圍
clamp 到 `[60, 3600]`(spec 設計;< 60 秒時 spin 沒意義,> 1 hour 應該手動排程)。

### 4. ConfigTool:dot-path + atomic write

```python
{action: "get", key: "hooks.PreToolUse"}     # 巢狀 lookup
{action: "set", key: "theme", value_json: '"dark"'}  # JSON-encoded value
{action: "delete", key: "old_setting"}
{action: "list"}                              # top-level keys
```

寫 settings 用 `tmp.replace(p)` atomic(避免半寫狀態被 reader 看到)。
`ORION_HOME` 環境變數可換 settings 目錄(unit test 隔離用)。

### 5. AskUserQuestionTool:CLI 走 stdin / Web 走 WebSocket

兩個 callback factory:
- `make_stdin_asker()`:print + input() 在 thread 跑(blocking 不擋 event loop)
- `make_ws_asker(outbound_queue, pending)`:同 Phase 6 permission pattern,丟事件 →
  reader resolve future

main.py CLI 模式預設掛 stdin asker。WebSocket 模式由 chat.py 自己掛(Phase 10c
完整整合)。

### 6. NotebookEditTool:replace 自動 clear outputs

source 改了 → 舊 outputs / execution_count 不再對應(對應 Anthropic NotebookEdit
spec)。replace code cell 時:
- `outputs = []`
- `execution_count = None`

insert / delete 不動 outputs。檔案大小 limit 100KB,超過拒絕(避免吃 RAM)。

### 7. BackgroundTaskRunner:in-memory + asyncio.Task

`get_runner()` 拿 process-wide singleton。Task lifecycle:

```
pending → in_progress → (completed | failed | stopped | deleted)
```

start command 用 `asyncio.create_subprocess_shell` + line-by-line stdout 累積。
Task `stop()` cancel asyncio.Task,`cancel` propagation 進 `try/except CancelledError`
標記 stopped。

跨 process / 跨 worker 留 Phase 10c(改 SQLite-backed)。

### 8. CronScheduler:APScheduler AsyncIOScheduler

5-field cron expr → `CronTrigger(minute, hour, day, month, day_of_week)`。
每 job 一個 asyncio coroutine 跑 `create_subprocess_shell`。

testbed 隔離用 `reset_scheduler()`(每 test 起新 scheduler)。teardown 時
event loop 已關 → `scheduler.shutdown` 用 `contextlib.suppress(Exception)` 包(避免炸 fixture)。

### 9. SubprocessPool:框架先建、優化留 Phase 10c

Phase 10 範圍只交付 stat 框架(`hits / misses / spawned`)+ fallback 路徑;
真 sentinel-based long-lived shell worker 留 Phase 10c(理由:正確 sentinel
parsing 比較 tricky,需要設計專門 protocol;先讓 stats 跑,production 真有
hot path 再改)。

### 10. profiler.py:pyinstrument 包裝

```python
async with profile_async() as prof:
    await heavy()
print(render_profile(prof, color=True))
```

`async_mode="enabled"` 讓 pyinstrument 4.6+ 正確處理 asyncio task switch。
sync 版用 `profile_sync()`。

---

## CLI / API 變更

### 內建工具集從 9 → 26

```bash
uv run orion run "..."     # 26 個工具可用,ToolSearch 動態載額外 schema
```

### 新環境變數

| Env | 用途 |
|---|---|
| `ORION_HOME` | settings.json 目錄(預設 `~/.orion`,測試隔離用) |

### 新 deps

| Package | 用途 |
|---|---|
| `apscheduler>=3.10` | cron scheduler |
| `pyinstrument>=4.6` | profiler |
| `nbformat>=5.10` | Jupyter notebook |

---

## Verification

```bash
cd orion-agent/api/

make check
# → ruff All checks passed!
# → mypy --strict: 156 files, 0 issues
# → pytest: 499 passed, 0 skipped(17s)

# 內建工具列表
uv run python -c "from orion_agent.main import _build_tools; \
  print(len(_build_tools()), 'tools')"
# 預期:26 tools

# 試 ConfigTool
ORION_HOME=/tmp/orion-test \
  uv run orion run --no-mcp --no-memory \
  "Use the Config tool to set 'theme' to 'dark'" 2>&1 | tail -10

# 試 TaskCreate / TaskList
uv run orion run --no-mcp --no-memory \
  "Create a background task with subject 'demo' and command 'sleep 2 && echo done'.
   Then list all tasks." 2>&1 | tail -20
```

---

## Phase 10 故意先不做(都已開新 phase plan)

| 項目 | 留給 |
|---|---|
| stress test + capacity planning(production data 後) | Phase 10c(`docs/phases/24-stress-capacity.md`) |
| Sentinel-based long-lived SubprocessPool 工人 | Phase 10c |
| AgentTool 接 sandbox_factory(Phase 9 已有 fork,plug factory)+ Team / SendMessage | 後續 |
| LSP integration(pylsp / pyright) | 後續 |
| ToolSearch deferred:真的從 system prompt 省掉 schema(對應 docs/08 cache) | 後續 |
| TaskRunner / CronScheduler 跨 process(SQLite-backed) | 後續 |
| Cache hit ratio 即時調校(Phase 4 boundary marker) | 後續 |

---

## 風險與已緩解

| 風險 | 緩解 |
|---|---|
| iCloud Drive 干擾(`.pth` hidden / 檔複製) | 跑前 `chflags -R nohidden .venv && find .venv -name "* [2-9]*" -delete` |
| AsyncIOScheduler teardown event loop 已關 | shutdown 用 `contextlib.suppress(Exception)` 包 |
| nbformat 沒 stub → mypy `no-untyped-call` | mypy override `nbformat.*` ignore_missing_imports + per-call type ignore |
| stdin asker 阻塞 event loop | `anyio.to_thread.run_sync` 包 input() |
| 26 工具 system prompt 變太長 | should_defer flag 預備 Phase 10c 用 |
| Test fixture 全域 singleton 污染跨 test | `reset_runner` / `reset_scheduler` 在 fixture autouse |
| WebSocket asker 還沒整合進 chat.py | 暫時 caller (chat.py runner) 自行 wire,Phase 10c 完整 |

---

## Tests 摘要

| Suite | 數量 | 說明 |
|---|---|---|
| Phase 0–9 既有 | 444 | 全綠不動 |
| **Phase 10 special**(tool_search / synthetic / sleep) | 10 | |
| **Phase 10 config** | 10 | |
| **Phase 10 interactive**(ask_user) | 5 | |
| **Phase 10 file**(notebook_edit) | 6 | |
| **Phase 10 task**(runner + tools) | 14 | |
| **Phase 10 cron** | 3 | |
| **Phase 10 perf**(subprocess_pool + profiler) | 7 | |
| **總計** | **499** | mypy --strict 156 files / ruff 全綠 |

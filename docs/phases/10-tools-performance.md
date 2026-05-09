# Phase 10:Tools + Performance(工具補完與性能優化)

## 速覽

- **預計時程**:3-4 週
- **前置 Phase**:Phase 1-9 全部完成
- **後續 Phase**:無(最終 phase),持續迭代
- **主要交付物**:
  - 補完工具(再 20-30 個):NotebookEdit、LSPTool、Task系列、Cron、SendMessage、AskUserQuestion 等
  - Async I/O 優化(避免阻塞 event loop)
  - Concurrent tool execution 性能調校
  - Prompt cache 命中率優化
  - Subprocess pool(ripgrep / shell)
  - Profiler 整合(用 Phase 9 的 OTel 數據定位瓶頸)

## 1. 目標與動機

Phase 1-9 跑通了完整 agent harness,但:

```
工具:只 10 個基礎(對應 docs/11 §15 等級的 ✅ 必備),還有 30+ 沒做
性能:沒 profile 過,可能有 hot path 阻塞 event loop
Cache:命中率沒最佳化,Phase 4 的 boundary marker 可能放錯位置
```

Phase 10 補齊缺角 + 把整體調校到可上線的水準。

**對應 docs**:
- [docs/11](../11-tools-catalog.md) 工具完整目錄(剩餘 30+ 工具的 input schema)
- [docs/02 §10-12](../02-agent-loop.md) Agent loop 性能切點
- [docs/08 §8d](../08-system-prompt.md) cache 失效成本

完成本 phase 後,Python port 達到「對等 Claude Code 核心功能」的里程碑。

## 2. TS 源檔映射

| Python 模組 | 對應 TS 源檔 | 注意事項 |
|---|---|---|
| `src/tools/file/notebook_edit.py` | `src/tools/NotebookEditTool/` | Jupyter notebook |
| `src/tools/lsp/lsp_tool.py` | `src/tools/LSPTool/` | LSP 整合 |
| `src/tools/task/task_*.py` | `src/tools/Task*Tool/` | 6 個 task 工具 |
| `src/tools/cron/cron_*.py` | `src/tools/ScheduleCronTool/` | 3 個 cron 工具 |
| `src/tools/messaging/send_message.py` | `src/tools/SendMessageTool/` | teammate 通訊 |
| `src/tools/interactive/ask_user.py` | `src/tools/AskUserQuestionTool/` | 互動反問 |
| `src/tools/config/config_tool.py` | `src/tools/ConfigTool/` | 讀寫 settings |
| `src/tools/team/team_*.py` | `src/tools/TeamCreateTool/`、`TeamDeleteTool/` | team session |
| `src/tools/special/synthetic_output.py` | `src/tools/SyntheticOutputTool/` | structured output 強制 |
| `src/tools/special/tool_search.py` | `src/tools/ToolSearchTool/` | deferred tool 動態載入 |
| `src/tools/special/sleep.py` | `src/tools/SleepTool/` | autonomous agent |
| `src/perf/subprocess_pool.py` | (無對應)| ripgrep / shell pool 優化 |
| `src/perf/profiler.py` | `src/utils/queryProfiler.ts`、`headlessProfiler.ts` | Profiler 切點 |

## 3. 任務拆解

### Week 1:核心缺角工具

- [ ] 1.1 `tools/file/notebook_edit.py`(Jupyter notebook cell 操作)
- [ ] 1.2 `tools/lsp/lsp_tool.py`(用 `pylsp` / `pyright` 等 LSP server)
- [ ] 1.3 `tools/interactive/ask_user.py`(整合 Phase 6 WebSocket round-trip)
- [ ] 1.4 `tools/config/config_tool.py`(讀寫 settings.json)
- [ ] 1.5 `tools/special/tool_search.py`(deferred tool 動態載入機制 — 注意:Phase 1 已隱含,這裡正式做)
- [ ] 1.6 `tools/special/synthetic_output.py`(SDK structured output)

### Week 2:Task / Cron / Team / Messaging

- [ ] 2.1 `tools/task/task_create.py` + `task_get.py` + `task_list.py` + `task_update.py` + `task_stop.py` + `task_output.py`
- [ ] 2.2 Background task runner(配合 Phase 7 的 sandbox)
- [ ] 2.3 `tools/cron/cron_create.py` + `cron_list.py` + `cron_delete.py`(用 APScheduler)
- [ ] 2.4 `tools/team/team_create.py` + `team_delete.py`(team session 概念)
- [ ] 2.5 `tools/messaging/send_message.py`(team / coordinator 通訊)
- [ ] 2.6 `tools/special/sleep.py`(autonomous agent)

### Week 3:性能優化

- [ ] 3.1 用 Phase 9 OTel 數據找 top 5 hot path
- [ ] 3.2 `perf/subprocess_pool.py`:ripgrep / shell process pool(避免每次 fork)
- [ ] 3.3 `perf/profiler.py`:用 cProfile / pyinstrument 找 CPU hotspot
- [ ] 3.4 異步化阻塞 call(`subprocess.run` → `asyncio.create_subprocess_exec`)
- [ ] 3.5 Concurrent tool execution 調校(觀察並發效率)
- [ ] 3.6 cache 命中率測量 + 調校 boundary 位置(若需要)

### Week 4:Polish + 文件 + 收尾

- [ ] 4.1 補完整 README(對外用)
- [ ] 4.2 docker-compose dev / prod 兩套
- [ ] 4.3 對外 API documentation(OpenAPI / docusaurus)
- [ ] 4.4 stress test + 容量估算(寫一份 capacity planning doc)
- [ ] 4.5 Phase 0-10 全程心得整理(blog / public 版)
- [ ] 4.6 慶祝!

## 4. 模組架構與檔案

```
src/claude_agent_py/
├── tools/
│   ├── file/
│   │   └── notebook_edit.py           # ◀ NEW
│   ├── lsp/
│   │   └── lsp_tool.py                # ◀ NEW
│   ├── interactive/
│   │   └── ask_user.py                # ◀ NEW
│   ├── config/
│   │   └── config_tool.py             # ◀ NEW
│   ├── task/
│   │   ├── task_create.py             # ◀ NEW
│   │   ├── task_get.py
│   │   ├── task_list.py
│   │   ├── task_update.py
│   │   ├── task_stop.py
│   │   └── task_output.py
│   ├── cron/
│   │   ├── cron_create.py
│   │   ├── cron_list.py
│   │   └── cron_delete.py
│   ├── team/
│   │   ├── team_create.py
│   │   └── team_delete.py
│   ├── messaging/
│   │   └── send_message.py
│   └── special/
│       ├── tool_search.py             # ◀ NEW deferred 機制
│       ├── synthetic_output.py        # ◀ NEW SDK structured
│       └── sleep.py
│
├── perf/
│   ├── __init__.py
│   ├── subprocess_pool.py             # ◀ NEW process pool
│   └── profiler.py                    # ◀ NEW pyinstrument 包裝

docs/
└── phases/                            # 不再增,但補完 README
```

## 5. Python Skeleton(關鍵幾個工具)

### 5.1 `tools/special/tool_search.py`

```python
"""ToolSearch — 動態載入 deferred tools。

對應 TS ToolSearchTool。Phase 1 工具列表很短,所有工具直接 load;
Phase 10 的 production 版可能有 100+ tools(MCP + plugin),要 deferred 機制。

機制:
  - Tool 有 `should_defer = True` → 不放 system prompt,只放名稱列表
  - 模型呼叫 ToolSearch({query: "select:NotebookEdit"}) → 載入該 tool 的 schema
"""
from __future__ import annotations
from typing import AsyncIterator
from claude_agent_py.core.tool import Tool, ToolInput, ToolEvent, TextEvent


class ToolSearchInput(ToolInput):
    query: str
    """支援:'select:Name1,Name2' / 'keyword search' / '+name keyword'"""
    max_results: int = 5


class ToolSearchTool:
    name = "ToolSearch"
    description = "Load schema for deferred tools by name or keyword."
    input_schema = ToolSearchInput

    def __init__(self, all_tools: list[Tool]):
        self.all_tools = all_tools

    def is_concurrency_safe(self, input: ToolSearchInput) -> bool:
        return True

    async def call(
        self, input: ToolSearchInput, ctx,
    ) -> AsyncIterator[ToolEvent]:
        if input.query.startswith("select:"):
            names = input.query[7:].split(",")
            matched = [t for t in self.all_tools if t.name in names]
        else:
            # Keyword search(簡單版:name + description 含關鍵字)
            keywords = input.query.lower().split()
            matched = [
                t for t in self.all_tools
                if all(
                    k in t.name.lower() or k in t.description.lower()
                    for k in keywords
                )
            ][:input.max_results]

        # 把 matched tool 的完整 schema 序列化回給模型
        result = "<functions>\n"
        for t in matched:
            schema = t.input_schema.model_json_schema()
            result += (
                f'<function>{{"description": "{t.description}", '
                f'"name": "{t.name}", "parameters": {schema}}}</function>\n'
            )
        result += "</functions>"

        yield TextEvent(text=result)
```

### 5.2 `tools/cron/cron_create.py`

```python
"""排程未來執行 agent。對應 TS CronCreateTool。

用 APScheduler 跑背景排程。
"""
from __future__ import annotations
from typing import AsyncIterator
from datetime import datetime
import uuid

from apscheduler.schedulers.asyncio import AsyncIOScheduler
from apscheduler.triggers.cron import CronTrigger

from claude_agent_py.core.tool import ToolInput, ToolEvent, TextEvent


# 全域 scheduler(per-process)
_scheduler: AsyncIOScheduler | None = None


def get_scheduler() -> AsyncIOScheduler:
    global _scheduler
    if _scheduler is None:
        _scheduler = AsyncIOScheduler()
        _scheduler.start()
    return _scheduler


class CronCreateInput(ToolInput):
    name: str
    cron_expression: str  # "0 9 * * MON" = 每週一 9 點
    prompt: str  # 要執行的 prompt


class CronCreateTool:
    name = "CronCreate"
    description = "Schedule a recurring agent task."
    input_schema = CronCreateInput

    def is_concurrency_safe(self, input: CronCreateInput) -> bool:
        return False

    async def call(
        self, input: CronCreateInput, ctx,
    ) -> AsyncIterator[ToolEvent]:
        scheduler = get_scheduler()
        job_id = str(uuid.uuid4())

        async def run_scheduled_agent():
            # 用 Phase 1 的 Conversation 跑 prompt
            from claude_agent_py.core.conversation import Conversation
            # ... spawn fresh conversation, run prompt, persist result
            pass

        scheduler.add_job(
            run_scheduled_agent,
            CronTrigger.from_crontab(input.cron_expression),
            id=job_id,
            name=input.name,
        )

        yield TextEvent(text=f"Cron created: id={job_id}, expression={input.cron_expression}")
```

### 5.3 `tools/lsp/lsp_tool.py`

```python
"""LSP 工具。對應 TS LSPTool。

用 pyright / pylsp 等 LSP server。
"""
from __future__ import annotations
from typing import AsyncIterator, Literal
from pathlib import Path

from claude_agent_py.core.tool import ToolInput, ToolEvent, TextEvent


class LSPInput(ToolInput):
    operation: Literal["diagnostics", "hover", "definition", "references", "symbols"]
    file_path: str
    line: int | None = None
    character: int | None = None


class LSPTool:
    name = "LSP"
    description = "LSP queries: diagnostics, hover, definition, references, symbols."
    input_schema = LSPInput

    def is_concurrency_safe(self, input: LSPInput) -> bool:
        return True

    async def call(
        self, input: LSPInput, ctx,
    ) -> AsyncIterator[ToolEvent]:
        # 整合 multilspy 或自寫 LSP client
        # 細節:LSP server 啟動時機、client 池化等
        from multilspy import LanguageServer
        from multilspy.multilspy_config import MultilspyConfig

        config = MultilspyConfig.from_dict({"code_language": "python"})
        async with LanguageServer.create(config, str(ctx.cwd)).start_server():
            if input.operation == "diagnostics":
                # ...
                pass
            elif input.operation == "hover":
                # ...
                pass
            # 細節依 multilspy 文件

        yield TextEvent(text="...")
```

### 5.4 `tools/interactive/ask_user.py`

```python
"""AskUserQuestion — 互動反問使用者。

對應 TS AskUserQuestionTool。
Phase 6 已有 ws round-trip 機制,這裡是高層 wrapper。
"""
from __future__ import annotations
from typing import AsyncIterator
from claude_agent_py.core.tool import ToolInput, ToolEvent, TextEvent


class AskUserOption(ToolInput):
    label: str
    description: str


class AskUserQuestion(ToolInput):
    question: str
    header: str  # 短標籤
    options: list[AskUserOption]
    multi_select: bool = False


class AskUserQuestionInput(ToolInput):
    questions: list[AskUserQuestion]


class AskUserQuestionTool:
    name = "AskUserQuestion"
    description = "Ask user multiple-choice questions interactively."
    input_schema = AskUserQuestionInput

    def is_concurrency_safe(self, input: AskUserQuestionInput) -> bool:
        return False  # 鎖 UI

    async def call(
        self, input: AskUserQuestionInput, ctx,
    ) -> AsyncIterator[ToolEvent]:
        # ctx 應該有 ws / interaction channel(由 Phase 6 注入)
        # 細節:推 PermissionAskEvent 變體 → 等 user 回應
        ...
```

### 5.5 `perf/subprocess_pool.py`

```python
"""Subprocess pool — 重用 ripgrep / shell process。"""
from __future__ import annotations
import asyncio
from contextlib import asynccontextmanager
from collections import deque


class SubprocessPool:
    """重用長期運行的 subprocess(例:ripgrep daemon mode)。

    用於替代每次 spawn `rg` 子程序的 GrepTool。
    """

    def __init__(self, command: list[str], pool_size: int = 5):
        self.command = command
        self.pool_size = pool_size
        self._pool: deque[asyncio.subprocess.Process] = deque()
        self._lock = asyncio.Lock()

    async def _spawn(self) -> asyncio.subprocess.Process:
        return await asyncio.create_subprocess_exec(
            *self.command,
            stdin=asyncio.subprocess.PIPE,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
        )

    @asynccontextmanager
    async def acquire(self):
        async with self._lock:
            if self._pool:
                proc = self._pool.popleft()
            else:
                proc = await self._spawn()

        try:
            yield proc
        finally:
            async with self._lock:
                if proc.returncode is None and len(self._pool) < self.pool_size:
                    self._pool.append(proc)
                else:
                    proc.terminate()
```

### 5.6 `perf/profiler.py`

```python
"""Profiler 切點。在 dev 模式下 enable,定位瓶頸。"""
from __future__ import annotations
from contextlib import contextmanager
from pathlib import Path
import os

import pyinstrument


@contextmanager
def profile(name: str, output_dir: Path = Path("./profiles")):
    """用 pyinstrument profile 一段程式碼。"""
    if os.environ.get("CLAUDE_AGENT_PROFILE") != "1":
        yield
        return

    profiler = pyinstrument.Profiler()
    profiler.start()
    try:
        yield profiler
    finally:
        profiler.stop()
        output_dir.mkdir(parents=True, exist_ok=True)
        output_path = output_dir / f"{name}_{int(time.time())}.html"
        with open(output_path, "w") as f:
            f.write(profiler.output_html())
```

使用範例:

```python
async def submit_message(self, prompt):
    with profile("submit_message"):
        async for msg in query_loop(...):
            yield msg
# 跑後檢查 ./profiles/submit_message_*.html
```

## 6. 設計決策與取捨

### 為何 deferred tool 機制留到 Phase 10?

Phase 1 工具少,全載入到 system prompt 沒問題。Phase 5 加 MCP 動態工具後,可能有 100+ tools,system prompt 會很長。

Phase 10 才正式做 deferred 機制 + ToolSearch:
- 簡單 tool 直接載
- 複雜 / 罕用 / MCP tool 標 `should_defer=True`
- 模型用 ToolSearch 載入

對應 TS `Tool.shouldDefer` / `alwaysLoad`(見 docs/11 §13)。

### 為何 LSP 用 multilspy?

[multilspy](https://github.com/microsoft/multilspy) 是 Microsoft Research 的多語言 LSP client wrapper。一個 API 對應 Python(pyright)/ TypeScript(typescript-language-server)/ Java / Go 等 server。

替代:自寫 LSP client(複雜,~2000 行 protocol code)。

### 為何 cron 用 APScheduler?

- 純 Python,不需要 Redis / DB(APScheduler 可跑 in-memory job store)
- 支援 cron expression / interval / one-shot
- 易整合 asyncio

替代:外部 cron + 寫 webhook(更複雜)。

### 為何性能優化放最後?

「Premature optimization is the root of all evil」。Phase 1-9 先求對。Phase 10 才用真實 telemetry 數據(Phase 9 OTel)定位瓶頸,**有依據地優化**。

可能發現:
- 大部分 turn 延遲在等 anthropic API(無法優化)
- 某個 hot path 浪費(可優化)
- Cache 命中率低(調 boundary 位置可改善)

### 為何 subprocess pool?

`Bash` / `Grep` 工具每次 spawn 子程序(50ms)。高 QPS 下有意義:
- ripgrep daemon mode 重用
- bash 不適合 pool(每次需要乾淨環境)

對某些 read-only repeated 工具 pool 化有效。

### Phase 10 故意不做的

| 項目 | 為何不做 |
|---|---|
| 工具補完 100% 對等 TS | 30+ 工具夠用,剩下的 KAIROS / ant-only / Voice 等 scope 外 |
| 自動 hyperparameter tuning(autoML)| 過度工程,人工調夠 |
| 跨 region 部署 | 屬於 ops,不是 phase 範圍 |

## 7. 驗收標準

### 自動測試

```bash
pytest tests/tools/ tests/perf/ -v
```

關鍵測試:

- 每個新工具至少 1 個 happy path test
- `test_tool_search.py`:select / keyword / + 模式都正確
- `test_cron_create.py`:排程設定、執行、刪除
- `test_subprocess_pool.py`:重用、超 pool 上限重建、失效清理

### 手動驗證

跑完整對話跑遍 ~30 個工具:

```bash
> "Edit my Jupyter notebook /tmp/foo.ipynb cell 2"  # NotebookEdit
> "Schedule a daily summary at 9am"                # CronCreate
> "Get LSP diagnostics for /tmp/main.py"           # LSP
> "Create a task to run pytest in background"      # TaskCreate + TaskGet
> "Ask me which framework I prefer"                # AskUserQuestion
```

### 性能驗證

```bash
# 開 profiler
CLAUDE_AGENT_PROFILE=1 python -m claude_agent_py "..."

# 看 profiles/*.html
# 確認:
#   - submit_message 的 90% 時間在等 API(預期)
#   - 沒有單一 sync call > 100ms 阻塞 event loop
```

Stress test 結果:

| Metric | Phase 7 baseline | Phase 10 目標 |
|---|---|---|
| Turn p50 latency | 5s | < 4s |
| Turn p95 latency | 15s | < 10s |
| Cache hit ratio | 65% | > 80% |
| 並發 50 users token throughput | 100K/min | > 150K/min |

### 整合驗證

跑一個 production-like demo session:
1. 多 turn 對話(20+)
2. 觸發 5+ 種工具
3. 觸發 compaction(Phase 3)
4. 大結果觸發第 1-3 層(Phase 2 / 5 / 9)
5. 觸發子 agent(Phase 9)
6. resume 後繼續

全程觀察 OTel trace,沒明顯異常。

## 8. 常見踩雷

### 踩雷 1:LSP server 啟動慢

multilspy 每次 spawn LSP server ~2-5 秒。要 pool 化(per-language 一個 long-running server)。

```python
# 用 lru_cache 維持單一實例
@lru_cache(maxsize=10)
def get_lsp_server(language: str, project_root: str):
    return LanguageServer.create(...)
```

### 踩雷 2:APScheduler job 跨 process

Phase 7 多 worker 部署時,APScheduler 每個 worker 自己一份 → cron 跑 N 次。

修法:用 PostgreSQL job store(`SQLAlchemyJobStore`)+ `coalesce=True`,讓多 worker 只執行一次。

### 踩雷 3:AskUserQuestion 無限等

Phase 6 已有 timeout(60s),但跨多輪要小心:
- 第 1 輪 ask → user 沒回 → 60s deny
- agent 繼續推理 → 又 ask → 又等 60s

要在 ctx 累計 ask 次數,超 N 次自動結束。

### 踩雷 4:Subprocess pool 死鎖

子程序卡住(例:ripgrep 等大檔)→ pool 取出後不回。要加:
- 超時機制(N 秒沒 release → 強殺重建)
- health check(取出時 check returncode)

### 踩雷 5:Profiling overhead

pyinstrument 在 hot path 有 5-10% overhead。Production 不要 always-on。用 env var 開關:

```bash
CLAUDE_AGENT_PROFILE=1 python -m ...  # 只 dev 用
```

或 sampling profiler(`py-spy`,完全 zero overhead)。

### 踩雷 6:Cache 調校陷阱

調 boundary 位置可能讓 static section 變動 → 整段 global cache miss。要先看 telemetry 數據,評估「動」靜態段的代價:
- 「動」一個本來不變的段:0% miss → N% miss(可能 30K tokens × N turn)
- 「不動」一個本來變的段:N% miss → 0% miss(可省 30K × N tokens)

對應 docs/08 §8d 的成本分析。

### 踩雷 7:工具補完範圍蔓延

Phase 10 容易陷入「補 100% 對等」的陷阱。建議:

- 列「最常用 TOP 30」工具(看實際 user demand)
- 補完這 30 個就停,進 production
- 後續迭代視需求補

不要為了「全」而做 Voice / KAIROS / Bridge 等 scope 外工具。

## 9. 參考資料

### docs/01-11

- [docs/11](../11-tools-catalog.md) — 完整工具目錄,看哪些必補
- [docs/02 §10-12](../02-agent-loop.md) — 工具呼叫管線(性能切點)
- [docs/08 §8d](../08-system-prompt.md) — Cache 失效成本

### TS 源檔

- 各個 `src/tools/<XxxTool>/` — 對應工具實作
- `src/utils/queryProfiler.ts` — Profiler 設計
- `src/utils/headlessProfiler.ts` — Headless 模式 profiling

### 外部資源

- [multilspy](https://github.com/microsoft/multilspy) — 多語言 LSP client
- [APScheduler](https://apscheduler.readthedocs.io/) — Python 排程
- [pyinstrument](https://pyinstrument.readthedocs.io/) — call tree profiler
- [py-spy](https://github.com/benfred/py-spy) — sampling profiler(production-safe)

## 完成檢查表

- [ ] 補完 20+ 工具
- [ ] ToolSearch + deferred 機制
- [ ] LSP / Cron / Task / AskUser / Config 完整
- [ ] Subprocess pool 對 hot tool 加速
- [ ] Profiler 整合
- [ ] Cache 命中率 > 80%
- [ ] Stress test pass(並發 50 users)
- [ ] 對外 README + API docs
- [ ] **Phase 0-10 全程心得整理 → 公開 blog**

## 結語

恭喜走完 Phase 0-10 全程!此時你應該:

- 有一個 production-grade Python agent harness
- 對 LLM agent 工程有深刻理解
- 有 11 篇 phase 心得文件 / blog post
- 對 Claude Code 設計每個取捨都有自己的看法

**真正的學習是這個過程,不是終點**。Phase 10 之後的維護 / 擴展 / 對齊 Anthropic 後續版本,會是另一段旅程。

把這 11 個 phase docs 當作「給未來自己的訊息」,改進、迭代、拋棄你不認同的設計。Anthropic 自己也是這樣對待 Claude Code 的(從 v1 演進到 v2.x,未來還會繼續)。

回到 [phases/README.md](./README.md) 看整體 roadmap。

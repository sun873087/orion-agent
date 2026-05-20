# Tools

Agent 能呼叫的「能做事的東西」。30+ 內建 + 自訂 Tool 介面。

**實作位置**:`packages/orion-sdk/src/orion_sdk/tools/`

## Builtin 全清單(by category)

### File system
- **Read** — 讀檔(支援 image / PDF / large file slicing)
- **Write** — 寫檔(snapshot 舊內容到 file-history 給 undo)
- **Edit** — Old-string → new-string,失敗強制 Read 先
- **MultiEdit** — 一次多個 edit 同檔
- **Glob** — 模式比對 list 檔
- **Grep** — ripgrep 包裝(content / paths only / count)

### Shell
- **Bash** — 跑 shell command(local / Docker sandbox 由 ExecutorPolicy 切)
- **BashOutput** — 拉背景 process 的 stdout/stderr

### Web
- **WebFetch** — 抓 URL → markdown(per-session in-memory TTL cache,預設 5 min)
- **WebSearch** — 走 SerpAPI(Google search results)

### Skill / Memory
- **Skill** — load skill bundle inject 進 system
- **MemoryWrite** — 寫一條 markdown memory
- **MemoryRead** — recall by name / type

### MCP-related
- **McpListServers** — 列出已連 MCP server
- 動態:每個 MCP server 的 tools 自動接上(`mcp__<server>__<tool>` 命名)

### Multi-agent
- **AgentTool** / **SubAgentCreate** — spawn sub-agent 跑 sub-task
- **AgentSend** — peer 模式跨 agent 訊息

### Workflow
- **TodoWrite** — 維護 task list(stateful、UI 顯)
- **AskUserQuestion** — pause 對話問 user(1-4 options,multi/single select)
- **PostMessage** — 給 user 推 OS notification
- **PushNotification** — 跨機推

### Plan mode 專用
- **ExitPlanMode** — 提計畫 → 進審核狀態(由 plan-mode wrapper 自動 enforce 唯讀)

### Cowork desktop 專屬
- **OpenPath** / **OpenUrl** — 開 file Finder / 開瀏覽器
- **ScheduleCreate** / **LoopCreate** / **CronCreate** — 排程 / 重複任務

### 其他
- **NotebookEdit** — `.ipynb` cell 編輯
- **Plan** — 規劃 mode 切換

## 自訂 Tool

```python
from orion_sdk.tools.tool_def import ToolDefinition
from orion_sdk.tools.types import ToolInput, ToolResult

class MyTool(ToolDefinition):
    name = "MyTool"
    description = "Does X"
    input_schema = {"type": "object", "properties": {...}}

    async def execute(
        self, params: dict, ctx: AgentContext
    ) -> ToolResult:
        # ... 做事 ...
        return ToolResult(text="done", is_error=False)
```

Tools 是 **Protocol**(typing.Protocol)— 不必繼承,duck type 就 work。

## ExecutorPolicy(`streaming.py`)

每個 tool 宣告自己是 CONCURRENT 還是 SEQUENTIAL:

```python
class ToolDefinition:
    name: str
    description: str
    executor_policy: ExecutorPolicy = ExecutorPolicy.CONCURRENT
```

- **CONCURRENT** — 同一輪 N 個 tool_use 全部 asyncio.gather 平行跑(預設)
- **SEQUENTIAL** — 一個一個跑(state-modifying tool 用,e.g. TodoWrite)

## 註冊

`build_default_tool_set(...)` 接收 callback 注入 host-specific 邏輯:

```python
from orion_sdk.tools.builtin_set import build_default_tool_set

tools = build_default_tool_set(
    workspace_dir=Path("/some/workspace"),
    permission_policy=policy,
    blob_store=blob_store,
    ask_user_question=cowork_asker,        # host 注入
    schedule_create=cowork_scheduler.create,
    loop_create=cowork_scheduler.loop_create,
    ...
)
```

Host 不提供 callback 的 tool 自動不註冊(避免 schedule/loop 在 CLI 環境出現)。

## 設計取捨

- **Tool 即 spec,執行 by host**:SDK 定義 ToolDefinition(name / schema / description / executor_policy),具體執行邏輯由 host 注入 callback。同名 tool 在不同 host 行為不同(`ScheduleCreate` 在 CLI 寫 cron file,Cowork 寫 SQLite)。
- **Permission policy 介入時機**:在 `StreamingExecutor.execute()` 內呼 tool 前 — `always_allow` 直接過,`ask` 走 `AskUserQuestion`-like flow,DSL 比 path / tool name 條件。
- **Plan mode wrapper 自動掛**:`enter_plan_mode()` 之後 SDK 自動把所有非唯讀 tool 拒絕,LLM 只能 Read/Grep/Glob/WebFetch/AskUserQuestion 等;不必 host 介入。

## 限制 / 已知問題

- **Tool 沒 versioning**:同名 tool 跨版本 schema 改 → 舊 transcript 重 replay 可能 fail。要 backward compat 自己保證。
- **Cowork desktop 專屬 tool 不能在 CLI 用**:`OpenPath` 需要本機桌機環境,CLI / chat-api 不註冊。
- **MCP 動態 tools 跨 session 變化**:user 加 / 移 MCP server,tool list 會變,LLM 可能拿舊 cached system prompt 看不到新 tool — 走 cache invalidation 解。

## 看完繼續

- [agent-loop.md](./agent-loop.md) — tool execution 在 loop 哪一段
- [permissions.md](./permissions.md) — tool 怎麼被擋
- [mcp.md](./mcp.md) — MCP 動態 tool 註冊
- [multi-agent.md](./multi-agent.md) — AgentTool / SubAgentCreate

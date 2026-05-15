# Tools

agent 能呼叫的「能做事的東西」。Tools 是 stateless 的 `Protocol`,SDK 帶 30+ 內建工具,使用者也能寫自訂 tool 註冊進去。

**實作位置**:`packages/orion-sdk/src/orion_sdk/tools/`(內建)+ `core/tool.py`(`Tool` Protocol 定義)。

## Tool Protocol

```python
from typing import Protocol, AsyncIterator
from orion_sdk.core.tool import Tool, ToolEvent, ToolInput

class MyTool(Tool[MyToolInput]):
    name: str = "MyTool"
    description: str = "Does something"
    input_schema: type[MyToolInput] = MyToolInput

    async def run(
        self, input: MyToolInput, ctx: AgentContext
    ) -> AsyncIterator[ToolEvent]:
        yield ProgressEvent(data={"stage": "starting"})
        # ... 做事 ...
        yield TextEvent(text="done")
```

`ToolEvent` union:

- `TextEvent` — 中繼純文字輸出(會被收集進 final result)
- `ProgressEvent` — 可結構化的進度 update
- `ErrorEvent` — 錯誤(會被包成 ToolResultMessage with is_error=True)
- `ImageEvent` — 多模態回傳圖片

## 內建工具集

`build_default_tool_set(asker)` 註冊以下(共 30+):

### 檔案

| 工具 | 用途 |
|---|---|
| `Read` | 讀檔(支援 line range、image、PDF、Jupyter notebook) |
| `Write` | 寫新檔(refuse 覆蓋既有) |
| `Edit` | 字串替換(必須 unique;支援 replace_all) |
| `NotebookEdit` | Jupyter cell 編輯 |

### 搜尋

| 工具 | 用途 |
|---|---|
| `Grep` | ripgrep wrapper |
| `Glob` | 檔案 pattern 列舉 |

### Shell / 系統

| 工具 | 用途 |
|---|---|
| `Bash` | 跑 shell 命令(可選 background mode) |

### Web

| 工具 | 用途 |
|---|---|
| `WebFetch` | 抓 URL → markdown(可選 cache) |
| `WebSearch` | 搜尋引擎 |

### Agent 編排

| 工具 | 用途 |
|---|---|
| `Agent` | spawn sub-agent 跑獨立 query |
| `Skill` | 套用 markdown skill bundle |
| `EnterPlanMode` / `ExitPlanMode` | Plan mode 切換 |
| `EnterWorktree` / `ExitWorktree` | git worktree 隔離 |
| `AskUserQuestion` | 對 user 提問(needs asker callable) |

### Task 追蹤

`TaskCreate` / `TaskList` / `TaskGet` / `TaskUpdate` / `TaskStop` / `TaskOutput`(in-conversation 任務看板)

### Schedule

`CronCreate` / `CronList` / `CronDelete`(in-process apscheduler-based)

### 雜項

`ToolSearch`(deferred tool 載入)、`Sleep`、`SyntheticOutput`(僅內部)、`SettingsRead/Write`(`config_tool.py`)

## 啟用 / 停用

預設全開。停用方式:不要傳進 `Conversation(tools=...)` 即可。例:

```python
from orion_sdk.tools.builtin_set import build_default_tool_set
all_tools = build_default_tool_set(asker=None)
safe_tools = [t for t in all_tools if t.name not in {"Bash", "Write", "Edit"}]
conv = Conversation(provider=llm, tools=safe_tools)
```

## Permission

每個 tool 執行前過 `Conversation.can_use_tool` callable(預設 `always_allow`)。可改成 ask-user(WS / GUI) 或 DSL rule:

```python
from orion_sdk.permissions.policies import ask_via_callback

conv = Conversation(provider=llm, tools=tools, can_use_tool=ask_via_callback(my_asker))
```

詳見 [permissions.md](./permissions.md)(待寫)。

## Sandbox

工具預設直接動 host。`Sandbox` backend(Docker / local)接管後,工具透過 sandbox proxy 跑命令。詳見 [sandbox.md](./sandbox.md)(待寫)。

## MCP 工具

MCP server 連上後,server 提供的 tools 動態 wrap 成 `Tool` 介面塞進 agent。詳見 [mcp.md](./mcp.md)。

## 寫自訂 tool

1. 定義 `pydantic.BaseModel` 描述 input
2. 寫 class 實作 `Tool` Protocol
3. 在 caller spawn `Conversation` 前 append 進 tools list

例(完整可跑):

```python
from pydantic import BaseModel
from orion_sdk.core.tool import Tool, TextEvent

class MyToolInput(BaseModel):
    name: str

class GreetTool:
    name = "Greet"
    description = "say hi"
    input_schema = MyToolInput

    async def run(self, input: MyToolInput, ctx):
        yield TextEvent(text=f"hi {input.name}")

conv = Conversation(provider=llm, tools=[GreetTool(), *builtin_tools])
```

## 限制

- 同 conversation 內 tool name 不可重複(MCP server 衝突會 prefix `<server>:<tool>`)
- 沒有 timeout 預設值 — 慢工具要自己用 `asyncio.timeout`
- Tool 輸出超過 ~100KB 自動 spill 到 disk(`storage/large_result.py`)— caller 看不到差別

## 相關

- [agent-loop.md](./agent-loop.md) — 工具何時被呼叫
- [sandbox.md](./sandbox.md) — Sandbox 隔離
- [mcp.md](./mcp.md) — MCP tool 動態註冊

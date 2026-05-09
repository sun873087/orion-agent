# Phase 1:Agent Loop 核心

## 速覽

- **預計時程**:4-6 週(**最大、最關鍵**)
- **前置 Phase**:Phase 0 必須完成(含 LLMProvider 抽象,Phase 1 透過它支援 Claude / OpenAI)
- **後續 Phase**:Phase 2-10 全部依賴本 phase
- **主要交付物**:
  - `Conversation` class(對應 TS `QueryEngine`)
  - `query_loop` async generator(對應 TS `query.ts:queryLoop`)
  - `StreamingToolExecutor`(含並發、sibling abort)
  - `partition_tool_calls` 演算法
  - Pre/Post hook 框架
  - `can_use_tool` 三決策(allow/ask/deny)
  - 10 個基礎工具:Read / Write / Edit / Bash / Grep / Glob / WebFetch / Agent / Skill / TodoWrite

## 1. 目標與動機

Phase 0 跑通了「單 turn 一個工具」。Phase 1 要做出**真正的 agent loop**:

```
使用者輸入
   ↓
模型推理 → 可能 yield 多個 tool_use
   ↓
並發執行(若可)/序列執行
   ↓
回填 tool_result
   ↓
模型繼續推理 ← 直到沒 tool_use → Terminal
```

**對應 docs**:
- [docs/02](../02-agent-loop.md) 整章(Agent 主迴圈、QueryEngine vs query() 雙層拆分、工具呼叫管線)
- [docs/10](../10-tool-concurrency.md) 整章(並發策略、sibling abort、order preservation)
- [docs/06 模組 1-2](../06-harness-engineering.md) Harness 工程觀點

完成本 phase 後,你的系統就有 Claude Code 的「靈魂」 — 後面 phase 都是在這個迴圈上加細節(持久化、記憶、UI、sandbox)。

## 2. TS 源檔映射

| Python 模組 | 對應 TS 源檔 | 行數 | 注意事項 |
|---|---|---|---|
| `src/core/conversation.py` | `src/QueryEngine.ts` | 1295 | 改名為 `Conversation` 更貼合「對話」語意 |
| `src/core/query_loop.py` | `src/query.ts` | 1729 | 主迴圈,async generator |
| `src/core/transitions.py` | `src/query/transitions.ts` | — | `Terminal` / `Continue` 狀態 |
| `src/core/streaming_executor.py` | `src/services/tools/StreamingToolExecutor.ts` | 530 | 串流模式並發控制 |
| `src/core/tool_orchestration.py` | `src/services/tools/toolOrchestration.ts` | 188 | 批次模式 partition |
| `src/core/tool_execution.py` | `src/services/tools/toolExecution.ts` | 1745 | 單工具執行細節(權限、hooks 串接) |
| `src/permissions/decisions.py` | `src/hooks/useCanUseTool.tsx` | — | 三決策 allow/ask/deny |
| `src/hooks/registry.py` | `src/utils/hooks/` | 多檔 | Pre/Post hook 簡化版(完整版 Phase 8) |
| `src/tools/file/{read,write,edit}.py` | `src/tools/{FileReadTool,FileWriteTool,FileEditTool}/` | 各檔 | Phase 0 已起手 Read |
| `src/tools/shell/bash.py` | `src/tools/BashTool/BashTool.tsx` + `commandSemantics.ts` + `bashSecurity.ts` | 大 | 含 isReadOnly 動態判斷 |
| `src/tools/search/grep.py` | `src/tools/GrepTool/GrepTool.ts` | 中 | shell out to ripgrep |
| `src/tools/search/glob.py` | `src/tools/GlobTool/GlobTool.ts` | 中 | 用 Python `pathlib.Path.glob` |
| `src/tools/web/fetch.py` | `src/tools/WebFetchTool/WebFetchTool.ts` | 中 | httpx + 簡化 markdown 化 |
| `src/tools/agent/agent_tool.py` | `src/tools/AgentTool/AgentTool.tsx` + `runAgent.ts` | 大 | 子 agent spawn(共用 Conversation class) |
| `src/tools/agent/skill_tool.py` | `src/tools/SkillTool/SkillTool.ts` | 中 | Skill loader 簡化版 |
| `src/tools/todo/todo_write.py` | `src/tools/TodoWriteTool/TodoWriteTool.ts` | 小 | session 內待辦 |

## 3. 任務拆解

### Week 1:核心型別與骨架

- [ ] 1.1 `transitions.py`:`Terminal` / `Continue` 型別
- [ ] 1.2 `query_loop.py`:`QueryParams` dataclass + `query_loop` 函式骨架(只架構,不實作)
- [ ] 1.3 `conversation.py`:`Conversation` class 骨架(`mutable_messages`、`total_usage` 等欄位)
- [ ] 1.4 `messages.py`:擴充 Phase 0 的訊息型別,加 `ToolUseMessage`、`ToolResultMessage`、`SystemMessage`
- [ ] 1.5 `permissions/decisions.py`:`PermissionDecision` enum(allow/ask/deny)+ `CanUseToolFn` Protocol

### Week 2:單 turn 串流 + 工具執行

- [ ] 2.1 完整 streaming 解析(處理 ContentBlockStart/Delta/Stop 細節)
- [ ] 2.2 `tool_execution.py`:`run_tool_use` 單工具執行(權限檢查 + 呼叫)
- [ ] 2.3 `tool_orchestration.py`:`partition_tool_calls` 演算法(批次模式)
- [ ] 2.4 `tool_orchestration.py`:`run_tools` 批次入口
- [ ] 2.5 整合測試:模型 yield 一個工具 → 執行 → 回填 → 再推理 → 終止

### Week 3:多輪迴圈

- [ ] 3.1 `query_loop.py`:完整 `query_loop` 實作(while not Terminal)
- [ ] 3.2 `conversation.py`:`Conversation.submit_message` 委派給 `query_loop`
- [ ] 3.3 跨 turn 狀態:`mutable_messages`、`total_usage`、`permission_denials`
- [ ] 3.4 整合測試:多輪對話、模型呼叫多個工具、`Terminal` 終止

### Week 4:並發與串流 executor

- [ ] 4.1 `streaming_executor.py`:`StreamingToolExecutor` class
- [ ] 4.2 `can_execute_tool` 邏輯(同 batch concurrency-safe 才能加入並發)
- [ ] 4.3 `process_queue` 排隊邏輯(non-safe 擋住後續工具)
- [ ] 4.4 Sibling abort(只有 Bash 觸發)
- [ ] 4.5 Order preservation(`get_completed_results`)
- [ ] 4.6 並發測試(用 hypothesis 隨機產生 tool_use 序列驗證 partition + order)
- [ ] 4.7 `core/message_queue.py`:命令佇列管理(對應 TS `utils/messageQueueManager.ts` 547 行)
   > 處理:user 連送多條訊息時排隊、命令優先序、`commandLifecycle.ts`(已開始 / 已完成)通知。Phase 1 簡化版可只用 asyncio.Queue,production 用 priority queue。

### Week 5:Hook 框架 + 6 個工具

- [ ] 5.1 `hooks/registry.py`:`HookRegistry`、`PreToolUseHook` / `PostToolUseHook` 介面
- [ ] 5.2 整合 hook 到 `tool_execution.py`(pre 改 input、post 接收 result)
- [ ] 5.3 工具:`FileWriteTool`、`FileEditTool`(基於 Phase 0 的 Read,加寫入)
- [ ] 5.4 工具:`BashTool`(含 `is_read_only` 動態判斷,用 `bashlex` 解析)
- [ ] 5.5 工具:`GrepTool`(shell out to ripgrep)、`GlobTool`(用 pathlib)
- [ ] 5.6 工具:`WebFetchTool`(httpx + readability)

### Week 6:子 agent + Skill + Todo + 收尾

- [ ] 6.1 工具:`AgentTool` — spawn 子 `Conversation`(共用本 phase 寫好的 class)— **`run_forked_agent` 機制見 [Phase 12](./12-internal-mechanics.md) `forked_agent.py`**
- [ ] 6.2 工具:`SkillTool` — markdown skill loader 簡化版
- [ ] 6.3 工具:`TodoWriteTool` — session 內待辦
- [ ] 6.4 端到端整合測試:複雜 demo(讀檔 → grep → 編輯 → bash 跑測試)
- [ ] 6.5 性能 baseline 測量(turn 延遲、工具執行延遲)
- [ ] 6.6 寫 Phase 1 心得

## 4. 模組架構與檔案

```
src/claude_agent_py/
├── core/
│   ├── tool.py                        # (Phase 0 已建)
│   ├── messages.py                    # ◀ 擴充
│   ├── state.py                       # (Phase 0 已建)
│   ├── conversation.py                # ◀ NEW Conversation class(對應 QueryEngine)
│   ├── query_loop.py                  # ◀ NEW query_loop async gen
│   ├── transitions.py                 # ◀ NEW Terminal/Continue
│   ├── streaming_executor.py          # ◀ NEW StreamingToolExecutor
│   ├── tool_orchestration.py          # ◀ NEW partition + run_tools
│   └── tool_execution.py              # ◀ NEW run_tool_use 單工具
│
├── permissions/
│   ├── __init__.py
│   └── decisions.py                   # ◀ NEW allow/ask/deny
│
├── hooks/
│   ├── __init__.py
│   └── registry.py                    # ◀ NEW HookRegistry
│
└── tools/
    ├── file/
    │   ├── read.py                    # (Phase 0)
    │   ├── write.py                   # ◀ NEW
    │   └── edit.py                    # ◀ NEW
    ├── shell/
    │   └── bash.py                    # ◀ NEW
    ├── search/
    │   ├── grep.py                    # ◀ NEW
    │   └── glob.py                    # ◀ NEW
    ├── web/
    │   └── fetch.py                   # ◀ NEW
    ├── agent/
    │   ├── agent_tool.py              # ◀ NEW
    │   └── skill_tool.py              # ◀ NEW
    └── todo/
        └── todo_write.py              # ◀ NEW
```

## 5. Python Skeleton

### 5.1 `core/transitions.py`

```python
"""query loop 的狀態轉換型別。對應 TS src/query/transitions.ts。"""
from __future__ import annotations
from dataclasses import dataclass


@dataclass
class Terminal:
    """query loop 結束(模型回出最終回應,無 tool_use)。"""
    reason: str = "natural_stop"


@dataclass
class Continue:
    """query loop 要繼續(剛執行完工具,結果已回填)。"""
    reason: str  # "tool_results" / "auto_compact" / "reactive_compact" / ...
```

### 5.2 `core/query_loop.py`

```python
"""query_loop — 真正的 agent 主迴圈。對應 TS src/query.ts:queryLoop。

無狀態 generator:給定 messages + tools + canUseTool,跑完一個 turn。
不認識 conversation,不持久化跨 turn 狀態(那是 Conversation 的事)。
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import AsyncIterator

from claude_agent_py.core.tool import Tool
from claude_agent_py.core.messages import Message, AssistantMessage, UserMessage
from claude_agent_py.core.state import AgentContext
from claude_agent_py.core.transitions import Terminal, Continue
from claude_agent_py.permissions.decisions import CanUseToolFn
from claude_agent_py.hooks.registry import HookRegistry
from claude_agent_py.core.tool_orchestration import run_tools
from claude_agent_py.services.anthropic_client import AnthropicStreamingClient


@dataclass
class QueryParams:
    """query_loop 的輸入。對應 TS QueryParams(query.ts:181)。"""
    messages: list[Message]
    system_prompt: str
    tools: list[Tool]
    can_use_tool: CanUseToolFn
    hooks: HookRegistry
    max_turns: int = 30


async def query_loop(
    params: QueryParams,
    ctx: AgentContext,
) -> AsyncIterator[Message]:
    """主迴圈。

    對應 TS query.ts:241 queryLoop。
    while not Terminal:
        ① 呼叫模型
        ② 解析 ContentBlock(text yield、tool_use 進管線)
        ③ 工具執行(StreamingToolExecutor / run_tools)
        ④ 預算 / compaction(Phase 3)
        ⑤ Stop hooks
        ⑥ 決定 Continue 或 Terminal
    """
    state_messages = list(params.messages)
    turn_count = 0
    transition: Continue | Terminal = Continue(reason="initial")

    client = AnthropicStreamingClient()

    while not isinstance(transition, Terminal):
        if turn_count >= params.max_turns:
            transition = Terminal(reason="max_turns_reached")
            break
        turn_count += 1

        # ① 呼叫模型
        tool_uses: list = []
        async for block in client.stream(
            system=params.system_prompt,
            messages=[m.to_api() for m in state_messages],
            tools=[t.input_schema.model_json_schema() for t in params.tools],
        ):
            if block.type == "text":
                yield AssistantMessage(content=block.text)
            elif block.type == "tool_use":
                tool_uses.append(block)

        # 沒 tool_use → 終止
        if not tool_uses:
            transition = Terminal(reason="natural_stop")
            break

        # ③ 工具執行(批次,Phase 1 先用 run_tools;StreamingToolExecutor 是 Phase 1 後段)
        async for update in run_tools(
            tool_uses,
            assistant_messages=[],
            can_use_tool=params.can_use_tool,
            hooks=params.hooks,
            tools=params.tools,
            ctx=ctx,
        ):
            yield update.message
            state_messages.append(update.message)

        # ⑥ 繼續下一輪
        transition = Continue(reason="tool_results")
```

### 5.3 `core/conversation.py`

```python
"""Conversation — 對應 TS QueryEngine。

Session 級有狀態 wrapper。一個 conversation 一個實例,跨多輪保留:
  - mutable_messages、total_usage、permission_denials、read_file_state

submit_message 內部 for await query_loop({...}),把 query_loop yield 的訊息累積。

對應 TS src/QueryEngine.ts。
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import AsyncIterator

from claude_agent_py.core.tool import Tool
from claude_agent_py.core.messages import Message, UserMessage
from claude_agent_py.core.state import AgentContext
from claude_agent_py.core.query_loop import query_loop, QueryParams
from claude_agent_py.permissions.decisions import CanUseToolFn
from claude_agent_py.hooks.registry import HookRegistry


@dataclass
class TokenUsage:
    input: int = 0
    output: int = 0
    cache_read: int = 0
    cache_creation: int = 0


@dataclass
class PermissionDenial:
    tool_name: str
    tool_use_id: str
    tool_input: dict


class Conversation:
    """Session 級 wrapper,擁有跨 turn 狀態。"""

    def __init__(
        self,
        ctx: AgentContext,
        tools: list[Tool],
        can_use_tool: CanUseToolFn,
        hooks: HookRegistry | None = None,
        system_prompt: str = "",
    ) -> None:
        self.ctx = ctx
        self.tools = tools
        self.can_use_tool = can_use_tool
        self.hooks = hooks or HookRegistry()
        self.system_prompt = system_prompt

        # 跨 turn 狀態
        self.mutable_messages: list[Message] = []
        self.total_usage = TokenUsage()
        self.permission_denials: list[PermissionDenial] = []
        # self.read_file_state: FileStateCache = ...  # 完整 staleness check 見 Phase 12

    async def submit_message(self, prompt: str) -> AsyncIterator[Message]:
        """送一個使用者訊息,yield 模型與工具產出的訊息。

        對應 TS QueryEngine.submitMessage(src/QueryEngine.ts:209)。
        """
        # 包裝 can_use_tool 以追蹤 denials
        async def wrapped_can_use_tool(tool, input, ctx, tool_use_id):
            decision = await self.can_use_tool(tool, input, ctx, tool_use_id)
            if decision != "allow":
                self.permission_denials.append(PermissionDenial(
                    tool_name=tool.name,
                    tool_use_id=tool_use_id,
                    tool_input=input.model_dump(),
                ))
            return decision

        user_msg = UserMessage(content=prompt)
        self.mutable_messages.append(user_msg)

        params = QueryParams(
            messages=self.mutable_messages,
            system_prompt=self.system_prompt,
            tools=self.tools,
            can_use_tool=wrapped_can_use_tool,
            hooks=self.hooks,
        )

        async for msg in query_loop(params, self.ctx):
            self.mutable_messages.append(msg)
            yield msg
```

### 5.4 `core/tool_orchestration.py`

```python
"""批次模式工具編排。對應 TS src/services/tools/toolOrchestration.ts。

partition_tool_calls + run_tools。並發執行 read-only 工具,序列執行其他。
"""
from __future__ import annotations

import os
from dataclasses import dataclass
from typing import AsyncIterator

import anyio

from claude_agent_py.core.tool import Tool


def get_max_concurrency() -> int:
    """對應 TS getMaxToolUseConcurrency。"""
    return int(os.environ.get("CLAUDE_AGENT_MAX_TOOL_CONCURRENCY", "10"))


@dataclass
class Batch:
    is_concurrency_safe: bool
    blocks: list  # ToolUseBlock from anthropic SDK


def partition_tool_calls(tool_uses: list, tools: list[Tool]) -> list[Batch]:
    """連續的 concurrency-safe 工具打成同一 batch,non-safe 自成 batch。

    對應 TS toolOrchestration.ts:partitionToolCalls。
    """
    tool_by_name = {t.name: t for t in tools}
    batches: list[Batch] = []

    for tool_use in tool_uses:
        tool = tool_by_name.get(tool_use.name)
        if tool is None:
            is_safe = False
        else:
            try:
                parsed = tool.input_schema.model_validate(tool_use.input)
                is_safe = tool.is_concurrency_safe(parsed)
            except Exception:
                is_safe = False  # 解析失敗保守視為 non-safe

        if is_safe and batches and batches[-1].is_concurrency_safe:
            batches[-1].blocks.append(tool_use)
        else:
            batches.append(Batch(is_concurrency_safe=is_safe, blocks=[tool_use]))

    return batches


async def run_tools(
    tool_uses: list,
    *,
    tools: list[Tool],
    can_use_tool,
    hooks,
    ctx,
    assistant_messages: list,
) -> AsyncIterator:
    """執行所有 tool_use blocks。

    對應 TS toolOrchestration.ts:runTools。
    """
    for batch in partition_tool_calls(tool_uses, tools):
        if batch.is_concurrency_safe:
            # 並發
            async for upd in run_tools_concurrently(
                batch.blocks, tools=tools, can_use_tool=can_use_tool,
                hooks=hooks, ctx=ctx, assistant_messages=assistant_messages,
            ):
                yield upd
        else:
            # 序列
            for tool_use in batch.blocks:
                async for upd in run_one_tool(
                    tool_use, tools=tools, can_use_tool=can_use_tool,
                    hooks=hooks, ctx=ctx, assistant_messages=assistant_messages,
                ):
                    yield upd


async def run_tools_concurrently(
    tool_uses, *, tools, can_use_tool, hooks, ctx, assistant_messages,
) -> AsyncIterator:
    """並發跑多個工具,結果按原順序 yield。

    用 anyio task group 跑,結果暫存到 list 後按順序送出。
    對應 TS runToolsConcurrently 的 all(generators, concurrency)。
    """
    max_conc = get_max_concurrency()
    results_by_index: dict[int, list] = {}
    limiter = anyio.CapacityLimiter(max_conc)

    async def run_indexed(i: int, tu) -> None:
        async with limiter:
            chunks = []
            async for upd in run_one_tool(
                tu, tools=tools, can_use_tool=can_use_tool,
                hooks=hooks, ctx=ctx, assistant_messages=assistant_messages,
            ):
                chunks.append(upd)
            results_by_index[i] = chunks

    async with anyio.create_task_group() as tg:
        for i, tu in enumerate(tool_uses):
            tg.start_soon(run_indexed, i, tu)

    for i in range(len(tool_uses)):
        for upd in results_by_index.get(i, []):
            yield upd


async def run_one_tool(
    tool_use, *, tools, can_use_tool, hooks, ctx, assistant_messages,
) -> AsyncIterator:
    """單一工具執行流程:findTool → preHook → canUseTool → call → postHook → 回填。

    對應 TS run_tool_use(toolExecution.ts)。
    """
    # 細節省略,見 task 拆解 Week 2-5
    ...
```

### 5.5 `core/streaming_executor.py`(Week 4 重構)

```python
"""StreamingToolExecutor — 串流模式並發控制。

對應 TS src/services/tools/StreamingToolExecutor.ts。

vs run_tools(批次模式):
  ─ run_tools  等模型 yield 完所有 tool_use 才開始
  ─ StreamingToolExecutor 模型 yield 一個就立刻開始,並發跑

關鍵 invariant:
  ─ executing tools 全 concurrency-safe + 新 tool 也 safe → 可加入並發
  ─ 否則該 non-safe tool 等 + 擋住後續 tool
  ─ 結果按 add 順序 yield(get_completed_results)
"""
from __future__ import annotations

from typing import AsyncIterator
import anyio


class StreamingToolExecutor:
    def __init__(self, tools, can_use_tool, ctx, hooks):
        self.tools_def = {t.name: t for t in tools}
        self.can_use_tool = can_use_tool
        self.ctx = ctx
        self.hooks = hooks
        self.tracked: list[TrackedTool] = []
        self.has_errored = False
        self.errored_desc = ""
        self.sibling_abort = anyio.Event()
        self.discarded = False

    def add_tool(self, block, assistant_message) -> None:
        """模型 yield 一個 tool_use → 加入 queue,可能立刻開跑。"""
        tool_def = self.tools_def.get(block.name)
        if tool_def is None:
            # 找不到工具,直接做 synthetic error 結果
            ...
            return

        try:
            parsed = tool_def.input_schema.model_validate(block.input)
            is_safe = tool_def.is_concurrency_safe(parsed)
        except Exception:
            is_safe = False

        self.tracked.append(TrackedTool(
            id=block.id, block=block, assistant_message=assistant_message,
            status="queued", is_concurrency_safe=is_safe,
        ))
        # 觸發 process_queue(背景)
        ...

    def can_execute_tool(self, is_safe: bool) -> bool:
        """對應 TS canExecuteTool(StreamingToolExecutor.ts:129)。"""
        executing = [t for t in self.tracked if t.status == "executing"]
        return (
            len(executing) == 0
            or (is_safe and all(t.is_concurrency_safe for t in executing))
        )

    async def process_queue(self) -> None:
        """掃 queue,該開的開,non-safe 擋住後續。"""
        for tool in self.tracked:
            if tool.status != "queued":
                continue
            if self.can_execute_tool(tool.is_concurrency_safe):
                # 開始執行(spawn task)
                ...
            else:
                if not tool.is_concurrency_safe:
                    break  # non-safe 擋住

    def get_completed_results(self) -> AsyncIterator:
        """按 add 順序 yield 結果。前面未完前面後者也得等。

        對應 TS getCompletedResults。
        """
        ...

    async def maybe_abort_siblings(self, tool, error_block) -> None:
        """只有 Bash 觸發 sibling abort。對應 TS sibling abort 邏輯。"""
        if tool.block.name == "Bash":
            self.has_errored = True
            self.errored_desc = self._describe(tool)
            self.sibling_abort.set()
```

### 5.6 `permissions/decisions.py`

```python
"""權限三決策。對應 TS hooks/useCanUseTool.tsx。"""
from __future__ import annotations

from typing import Literal, Protocol

from claude_agent_py.core.tool import Tool, ToolInput
from claude_agent_py.core.state import AgentContext


PermissionDecision = Literal["allow", "ask", "deny"]


class CanUseToolFn(Protocol):
    async def __call__(
        self,
        tool: Tool,
        input: ToolInput,
        ctx: AgentContext,
        tool_use_id: str,
    ) -> PermissionDecision: ...


def always_allow() -> CanUseToolFn:
    """測試 / debug 用:無條件允許。"""
    async def f(tool, input, ctx, tool_use_id):
        return "allow"
    return f


def policy_based(policy_dict) -> CanUseToolFn:
    """根據 policy dict 決定。Phase 7 會擴成完整 policy engine。"""
    async def f(tool, input, ctx, tool_use_id):
        rule = policy_dict.get(tool.name, "ask")
        return rule
    return f
```

### 5.7 `tools/shell/bash.py`(關鍵工具)

```python
"""BashTool — 動態 isReadOnly 判斷。

對應 TS src/tools/BashTool/BashTool.tsx + commandSemantics.ts。
"""
from __future__ import annotations

import asyncio
import shlex
from typing import AsyncIterator

from claude_agent_py.core.tool import Tool, ToolInput, ToolEvent, TextEvent, ErrorEvent
from claude_agent_py.core.state import AgentContext


READ_ONLY_COMMANDS = {
    "ls", "cat", "head", "tail", "wc", "stat",
    "grep", "find", "echo", "pwd", "whoami",
    "date", "uname", "which", "type", "file",
    # ... 完整清單見 commandSemantics.ts
}


class BashInput(ToolInput):
    command: str
    description: str | None = None
    timeout: int = 120_000  # ms
    run_in_background: bool = False


class BashTool:
    name = "Bash"
    description = "Execute a bash command. Use absolute paths."
    input_schema = BashInput

    def is_read_only(self, input: BashInput) -> bool:
        """解析命令,看主程式是否在白名單。失敗 → 保守 False。

        對應 TS BashTool.isReadOnly(用 commandSemantics 解析)。
        """
        try:
            tokens = shlex.split(input.command)
            if not tokens:
                return False
            main_cmd = tokens[0].split("/")[-1]  # 處理 /usr/bin/ls
            return main_cmd in READ_ONLY_COMMANDS
        except Exception:
            return False  # 解析失敗保守

    def is_concurrency_safe(self, input: BashInput) -> bool:
        return self.is_read_only(input)

    def max_result_size_chars(self) -> int | float:
        return 30_000  # 對應 TS BashTool 的 30K(自己有 preview 邏輯)

    async def call(
        self,
        input: BashInput,
        ctx: AgentContext,
    ) -> AsyncIterator[ToolEvent]:
        # 注意:Phase 1 直接跑;Phase 7 改成 sandbox 內跑
        proc = await asyncio.create_subprocess_shell(
            input.command,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.STDOUT,
            cwd=ctx.cwd,
        )
        try:
            stdout, _ = await asyncio.wait_for(
                proc.communicate(), timeout=input.timeout / 1000
            )
        except asyncio.TimeoutError:
            proc.kill()
            yield ErrorEvent(message=f"Bash timeout after {input.timeout}ms")
            return

        text = stdout.decode("utf-8", errors="replace")
        if proc.returncode == 0:
            yield TextEvent(text=text)
        else:
            yield ErrorEvent(message=f"Bash exit {proc.returncode}:\n{text}")
```

## 6. 設計決策與取捨

### 為何 `Conversation` 而非 `QueryEngine`?

純命名 — Python 慣用 `Conversation` / `Session` / `Chat` 做這個語意。`QueryEngine` 是 Anthropic 的命名,不貼合 Python 生態。

### 為何 query_loop 是 module function 而非 method?

- TS 是 module-level `export async function* query()`
- Python 也應該保持「無狀態 generator」性質
- `Conversation.submit_message` 內呼叫 `query_loop()`,語意清楚
- 容易測試(只測 `query_loop`,不需要建整個 Conversation)

### 為何用 `anyio` 而非 `asyncio`?

`anyio` 提供:
- `CapacityLimiter`:比 `asyncio.Semaphore` 語意更清楚(限制並行數)
- `Event`:跨 task 信號(取代 `asyncio.Event`)
- `create_task_group`:結構化並行,例外處理乾淨
- 跨相容 trio(若未來換)

實際 backend 仍是 asyncio。

### 為何 batch 模式與 streaming 模式都要實作?

- 批次模式(`run_tools`):**先做**,概念簡單,容易測
- 串流模式(`StreamingToolExecutor`):**Phase 1 後段**做,生產用,可重疊延遲

兩者並存(對應 TS),測試時可切換,debug 時批次模式更易追蹤。

### Sibling abort 為何只 Bash?

照 TS 設計(`StreamingToolExecutor.ts:356-358` 註解):
> *Bash commands often have implicit dependency chains (e.g. mkdir fails → subsequent commands pointless). Read/WebFetch/etc are independent — one failure shouldn't nuke the rest.*

Python port 直接照搬這個設計。

### Phase 1 故意不做的

| 項目 | 留給哪個 phase |
|---|---|
| 工具結果三層持久化 | Phase 2 |
| Resume 機制 | Phase 2 |
| Memory 系統 | Phase 3 |
| AutoCompact / reactive compact | Phase 3 |
| System prompt section + cache | Phase 4 |
| MCP tool 動態載入 | Phase 5 |
| FastAPI / WebSocket | Phase 6 |
| Docker sandbox | Phase 7 |
| 完整 hook(8 種 event) | Phase 8 |
| Worktree | Phase 9(用 sandbox 替代) |
| 30+ 補完工具 | Phase 10 |
| Fallback model / retry | 後續 |

## 7. 驗收標準

### 自動測試

```bash
pytest tests/ --cov=claude_agent_py
mypy --strict src/
```

關鍵測試:

- `test_partition_tool_calls.py` — 用 hypothesis 隨機產生 (tool_name, is_safe) 序列,驗證 partition 結果正確
- `test_streaming_executor.py` — 並發場景:Read+Read+Bash(ls)、Edit、Read+Read 各種混合
- `test_order_preservation.py` — 並發完成順序亂序,但 yield 順序與 add 順序一致
- `test_sibling_abort.py` — Bash 出錯 → 並行兄弟 abort;Read 出錯 → 兄弟不受影響
- `test_query_loop_terminate.py` — 多輪後正常 Terminal;超 max_turns 強制 Terminal
- `test_conversation_state.py` — 跨 turn `mutable_messages` 累積、`permission_denials` 累積

### 手動驗證

```bash
python -m claude_agent_py
> Read /etc/hosts
> Look at the current dir, find all .py files, then grep for 'TODO'
> Edit /tmp/foo.txt and add a line
```

預期:
- 第 1 個只用 Read
- 第 2 個並發呼叫 Glob + Grep(可能多次)
- 第 3 個用 Read 後 Edit(序列)
- 全程 streaming,第一個字輸出 < 2 秒

### 整合驗證

跑通一個複雜 demo(在某 Python 專案內):

```
> 修這個 bug:當輸入空字串時 foo() 拋 None。先 grep 找 foo 定義、Read 看實作、修改、跑測試確認。
```

預期 agent 自主:
1. Grep 找 `def foo`(讀類並發)
2. Read 該檔(讀類並發)
3. Edit 修補
4. Bash `pytest` 驗證
5. 回報結果

## 8. 常見踩雷

### 踩雷 1:async generator 取消

`async for ... yield ...` 被外層取消時,Python 的 `aclose()` 會送 `GeneratorExit`。要在 `try / finally` 中清理(關 subprocess、釋放 lock)。

```python
async def query_loop(...):
    try:
        while ...:
            yield ...
    finally:
        await cleanup()
```

否則 timeout 取消時會留 zombie subprocess。

### 踩雷 2:hypothesis 對 ToolUseBlock 的 strategy

寫不出 hypothesis strategy 直接用 `@given` 裝飾就拋例外。要先寫 custom strategy:

```python
from hypothesis import strategies as st

@st.composite
def tool_use_strategy(draw):
    name = draw(st.sampled_from(["Read", "Bash", "Edit", "Write"]))
    return MockToolUse(name=name, input={...})
```

### 踩雷 3:partition 演算法的 edge case

- 空 list → return []
- 全 safe 一個 batch → 對
- 全 non-safe N 個 batch → 對
- 中間夾一個解析失敗的 → 對(視為 non-safe)
- 找不到 tool 的 name → 視為 non-safe

hypothesis 通常能找到你沒想到的組合。

### 踩雷 4:streaming + abort 訊號

模型 yield 過程中使用者 abort,要正確中斷:

```python
async def stream(...):
    try:
        async with self.client.messages.stream(...) as s:
            async for event in s:
                if ctx.abort_event.is_set():
                    break
                yield event
    except anyio.get_cancelled_exc_class():
        raise
```

### 踩雷 5:Conversation 的 mutable state vs 並行

若同一 `Conversation` 實例同時跑兩個 `submit_message`(不該發生但要防禦),`mutable_messages` 會 race。加 `anyio.Lock`:

```python
class Conversation:
    def __init__(self, ...):
        self._submit_lock = anyio.Lock()

    async def submit_message(self, prompt):
        async with self._submit_lock:
            ...
```

### 踩雷 6:子 agent 的 ctx 不要共用

`AgentTool` spawn 子 agent 時要建 **新的 AgentContext**(新 session_id、新 abort_event、新 token_budget),不要 share 父 ctx。否則父被 abort 會把子也 abort 掉(或反過來)。

```python
def fork_context(parent: AgentContext) -> AgentContext:
    return AgentContext(
        session_id=uuid4(),
        cwd=parent.cwd,
        abort_event=anyio.Event(),  # 新的
        feature_flags=dict(parent.feature_flags),  # copy
        # ...
    )
```

### 踩雷 7:WebFetchTool 的 readability

TS 版用 Anthropic API 內部 Haiku 模型摘要。Python 版可以:

- 用 `readability-lxml` + `markdownify` 純 Python 提取
- 或用 anthropic Haiku 自己呼叫一次(額外成本)

Phase 1 用前者,Phase 10 可選擇升級。

## 9. 參考資料

### docs/01-11

- [docs/02](../02-agent-loop.md) — 整章必讀(QueryEngine + query loop 的完整剖析)
- [docs/10](../10-tool-concurrency.md) — 整章必讀(並發機制細節)
- [docs/06 模組 1-2](../06-harness-engineering.md) — 編排循環 + 工具

### TS 源檔(實作對照)

- `src/QueryEngine.ts:209` — `submitMessage` 入口
- `src/query.ts:181-330` — `QueryParams` + `queryLoop` 開頭
- `src/services/tools/toolOrchestration.ts` — 整檔 188 行,完整看
- `src/services/tools/StreamingToolExecutor.ts` — 整檔 530 行
- `src/Tool.ts` — Tool 介面細節
- 各工具實作檔(對照寫 Python 版)

### 外部資源

- [anyio docs](https://anyio.readthedocs.io/) — `CapacityLimiter`、`create_task_group`
- [Anthropic SDK streaming](https://docs.anthropic.com/en/api/messages-streaming) — 完整事件型別
- [hypothesis](https://hypothesis.readthedocs.io/) — partition 測試必備
- [bashlex](https://github.com/idank/bashlex) — Bash AST 解析(BashTool isReadOnly 進階版)

## 完成檢查表

- [ ] 10 個工具全部跑通
- [ ] partition + 並發測試覆蓋率 > 80%
- [ ] 端到端 demo 跑通(複雜的 grep+read+edit+bash)
- [ ] streaming 延遲合理(模型第一字 < 2s)
- [ ] sibling abort 正確(Bash 觸發、Read 不觸發)
- [ ] order preservation 驗證
- [ ] Conversation 多輪 state 累積正確
- [ ] 寫 Phase 1 心得(這是最大 phase,值得詳寫)

完成後進入 [Phase 2:Storage & State](./02-storage-state.md)。

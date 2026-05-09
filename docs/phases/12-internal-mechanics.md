# Phase 12:Internal Mechanics(內部機制)

## 速覽

- **預計時程**:1-2 週
- **前置 Phase**:Phase 1(Conversation)、Phase 3(memory 用了 sideQuery)、Phase 4(system prompt)
- **本文件目的**:補 Phase 1-10 漏掉的「跨切點通用機制」與細部狀態
- **主要交付物**:
  - **Plan Mode 狀態機**(EnterPlanMode / ExitPlanMode 完整生命週期)
  - **`side_query` 通用機制**(spawn 小 Sonnet 不汙染主對話)
  - **`forked_agent` 機制**(共享父 prompt cache 的 fork)
  - **AppState 詳細模型**(toolPermissionContext / additionalWorkingDirectories / IDE state)
  - **File state cache + staleness check**(Edit 前驗證檔案沒變)

## 1. 為何需要本 phase?

Phase 1-10 跑通了主流程,但**有幾個跨切點機制**散落在多個 phase 裡用,沒抽出獨立實作:

```
Phase 3 用了 sideQuery 但沒實作 → 直接呼 sideQuery() 會失敗
Phase 3 / 9 用了 forkedAgent 但沒實作
Phase 1 列了 EnterPlanMode 工具但沒處理「進入後限制」狀態機
Phase 1 提到 file_state_cache 但沒寫 staleness check
```

本 phase **抽出來統一實作**,後續所有 phase 才能引用。

**對應 TS 源碼**:
- `src/utils/sideQuery.ts`(222 行)
- `src/utils/forkedAgent.ts`(689 行)
- `src/tools/EnterPlanModeTool/`、`src/tools/ExitPlanModeTool/`
- `src/state/AppState.tsx`、`AppStateStore.ts`
- `src/utils/fileStateCache.ts`

## 2. TS 源檔映射

| Python 模組 | 對應 TS 源檔 | 行數 | 注意 |
|---|---|---|---|
| `src/utils/side_query.py` | `src/utils/sideQuery.ts` | 222 | 通用 sub-Sonnet 呼叫 |
| `src/utils/forked_agent.py` | `src/utils/forkedAgent.ts` | 689 | cache-safe params + run fork |
| `src/plan_mode/state.py` | (散落)| — | Plan mode state 抽象 |
| `src/plan_mode/restrictions.py` | `src/utils/planModeV2.ts` | — | 限制 read-only 工具 |
| `src/state/app_state.py` | `src/state/AppState.tsx`、`AppStateStore.ts` | — | Redux 風格 store(簡化版) |
| `src/utils/file_state.py` | `src/utils/fileStateCache.ts` | — | Read 後 staleness check |

## 3. 任務拆解

### Week 1:sideQuery + forkedAgent

- [ ] 1.1 `utils/side_query.py`:`side_query()` 通用機制
- [ ] 1.2 設計:不寫 transcript / 不影響 main usage / 用獨立 abort signal
- [ ] 1.3 整合到 Phase 3 的 `select_relevant_memories`(改用 side_query)
- [ ] 1.4 `utils/forked_agent.py`:`CacheSafeParams` + `run_forked_agent`
- [ ] 1.5 整合到 Phase 3 的 `extract_memories`(改用 forked_agent)
- [ ] 1.6 整合到 Phase 1 的 `AgentTool.call`(子 agent 用 forked_agent)
- [ ] 1.7 測試:fork 用同 prompt prefix → cache hit

### Week 2:Plan mode + AppState + file state

- [ ] 2.1 `plan_mode/state.py`:`PlanModeState` enum + 轉換
- [ ] 2.2 `plan_mode/restrictions.py`:plan mode 下限制工具白名單
- [ ] 2.3 改造 Phase 1 EnterPlanModeTool / ExitPlanModeV2Tool 使用 state
- [ ] 2.4 整合到 `can_use_tool`(plan mode 時非 read-only 工具直接 deny)
- [ ] 2.5 `state/app_state.py`:AppState 詳細模型(toolPermissionContext 等)
- [ ] 2.6 `utils/file_state.py`:`FileStateCache` + `is_stale`(Edit 前 check)
- [ ] 2.7 測試 + 心得

## 4. 模組架構

```
src/claude_agent_py/
├── utils/
│   ├── side_query.py                   # ◀ 通用 sub-Sonnet
│   ├── forked_agent.py                 # ◀ cache-safe fork
│   └── file_state.py                   # ◀ Read 後 staleness
│
├── plan_mode/
│   ├── __init__.py
│   ├── state.py                        # ◀ PlanModeState
│   └── restrictions.py                 # ◀ 工具限制
│
└── state/
    └── app_state.py                    # ◀ AppState 詳細模型
```

## 5. Python Skeleton

### 5.1 `utils/side_query.py`(關鍵跨切點)

```python
"""side_query — 主迴圈中插入小 Sonnet 呼叫,不汙染主對話。

對應 TS utils/sideQuery.ts。被多處使用:
  - find_relevant_memories(memory selector)
  - compaction summary
  - title generation
  - prompt suggestion
"""
from __future__ import annotations
from dataclasses import dataclass
from typing import Any, Literal
import anthropic
import anyio


SideQuerySource = Literal[
    "memdir_relevance",
    "compact_summary",
    "title_generation",
    "prompt_suggestion",
    "general",
]


@dataclass
class SideQueryParams:
    model: str
    system: str
    messages: list[dict]
    skip_system_prompt_prefix: bool = True
    max_tokens: int = 256
    output_format: dict | None = None
    query_source: SideQuerySource = "general"


@dataclass
class SideQueryResult:
    content: list  # ContentBlocks
    usage: dict


async def side_query(
    params: SideQueryParams,
    *,
    signal: anyio.Event | None = None,
) -> SideQueryResult:
    """執行 side query。

    特性:
      - 不寫 transcript(主對話沒紀錄)
      - 用獨立 abort signal(可被 turn-level abort 取消)
      - 不影響主對話的 total_usage(獨立計費,但仍進 cost tracker)
      - skip_system_prompt_prefix=True → 完全自訂 system,不繼承主 system
    """
    client = anthropic.AsyncAnthropic()

    api_kwargs = dict(
        model=params.model,
        system=params.system,
        messages=params.messages,
        max_tokens=params.max_tokens,
    )

    # 若需要 JSON Schema 強制輸出,改用 tools
    if params.output_format and params.output_format.get("type") == "json_schema":
        schema = params.output_format["schema"]
        api_kwargs["tools"] = [{
            "name": "respond",
            "description": "Respond with structured data",
            "input_schema": schema,
        }]
        api_kwargs["tool_choice"] = {"type": "tool", "name": "respond"}

    response = await client.messages.create(**api_kwargs)

    return SideQueryResult(
        content=response.content,
        usage={
            "input_tokens": response.usage.input_tokens,
            "output_tokens": response.usage.output_tokens,
            "cache_read_input_tokens": getattr(response.usage, "cache_read_input_tokens", 0),
        },
    )


# Phase 3 改造後的呼叫示例:
async def select_relevant_memories(query: str, memories, recent_tools):
    manifest = format_memory_manifest(memories)
    result = await side_query(
        SideQueryParams(
            model="claude-sonnet-4-6",
            system=SELECT_MEMORIES_SYSTEM_PROMPT,
            messages=[{
                "role": "user",
                "content": f"Query: {query}\n\nAvailable memories:\n{manifest}",
            }],
            output_format={
                "type": "json_schema",
                "schema": {
                    "type": "object",
                    "properties": {
                        "selected_memories": {"type": "array", "items": {"type": "string"}},
                    },
                    "required": ["selected_memories"],
                },
            },
            query_source="memdir_relevance",
        )
    )
    # parse tool_use block
    for block in result.content:
        if block.type == "tool_use":
            return block.input.get("selected_memories", [])
    return []
```

### 5.2 `utils/forked_agent.py`(cache-safe fork)

```python
"""forked_agent — 共享父 prompt cache 的 fork agent。

對應 TS utils/forkedAgent.ts。被多處使用:
  - extract_memories(背景萃取)
  - AgentTool spawn 子 agent
  - 任何需要「跑一下子流程但要省 token」的場景

關鍵:CacheSafeParams 確保 fork 的 system + tools + 訊息前綴
與父對話 byte-identical → Anthropic prompt cache 命中。
"""
from __future__ import annotations
from dataclasses import dataclass, field
from typing import AsyncIterator
import anyio

from claude_agent_py.core.tool import Tool
from claude_agent_py.core.state import AgentContext
from claude_agent_py.core.messages import Message
from claude_agent_py.permissions.decisions import CanUseToolFn


@dataclass
class CacheSafeParams:
    """保證 byte-identical 前綴的參數包。"""
    system_prompt: list[str]
    tools: list[Tool]
    messages_prefix: list[Message]
    """父對話的訊息(這些必須不變)。"""

    @classmethod
    def from_parent(cls, parent_conv) -> "CacheSafeParams":
        """從父 Conversation 抽 cache-safe 部分。"""
        return cls(
            system_prompt=list(parent_conv.last_system_prompt),  # 必須在 Phase 4 留存
            tools=list(parent_conv.tools),
            messages_prefix=list(parent_conv.mutable_messages),
        )


@dataclass
class ForkedAgentResult:
    messages: list[Message]
    total_usage: dict
    written_paths: list[str] = field(default_factory=list)


async def run_forked_agent(
    *,
    parent: CacheSafeParams,
    user_prompt: str,
    can_use_tool: CanUseToolFn,
    fork_label: str = "subagent",
    max_turns: int = 5,
    skip_transcript: bool = True,
    parent_ctx: AgentContext,
) -> ForkedAgentResult:
    """跑 fork agent。

    與父共享 prompt cache 前綴(system + tools + messages_prefix)。
    fork 加自己的 user_prompt 後跑 query_loop,結束後返回結果。
    """
    from claude_agent_py.core.query_loop import query_loop, QueryParams
    from claude_agent_py.core.state import AgentContext
    from claude_agent_py.hooks.registry import HookRegistry
    from uuid import uuid4

    # 新 ctx 但繼承部分父狀態
    fork_ctx = AgentContext(
        session_id=uuid4(),
        cwd=parent_ctx.cwd,
        abort_event=anyio.Event(),  # 新的,父 abort 不影響 fork
        feature_flags=dict(parent_ctx.feature_flags),
        # sandbox:Phase 7 後從 pool 取新 sandbox(不重用父的)
    )

    # 父 messages + 新 user prompt
    new_message = {"role": "user", "content": user_prompt}
    fork_messages = [*parent.messages_prefix, new_message]

    params = QueryParams(
        messages=fork_messages,
        system_prompt="\n\n".join(parent.system_prompt),  # ← byte-identical 前綴
        tools=parent.tools,                                # ← 同 tools list 才命中 cache
        can_use_tool=can_use_tool,
        hooks=HookRegistry(),  # fork 不繼承父 hook(避免重複觸發)
        max_turns=max_turns,
    )

    collected_messages = []
    total_usage = {"input_tokens": 0, "output_tokens": 0, "cache_read_input_tokens": 0}

    async for msg in query_loop(params, fork_ctx):
        if not skip_transcript:
            # 寫 transcript(若需要 resume)
            pass
        collected_messages.append(msg)
        # 累積 usage
        if hasattr(msg, "usage"):
            for k in total_usage:
                total_usage[k] += getattr(msg.usage, k, 0)

    # 從 collected_messages 抽出 written paths(若 fork 寫了檔)
    written_paths = _extract_written_paths(collected_messages)

    return ForkedAgentResult(
        messages=collected_messages,
        total_usage=total_usage,
        written_paths=written_paths,
    )


def _extract_written_paths(messages: list) -> list[str]:
    paths = []
    for m in messages:
        if not isinstance(m.content, list):
            continue
        for block in m.content:
            if block.get("type") != "tool_use":
                continue
            if block.get("name") in ("Edit", "Write"):
                fp = block.get("input", {}).get("file_path")
                if fp:
                    paths.append(fp)
    return paths
```

### 5.3 `plan_mode/state.py`

```python
"""Plan mode state 抽象。對應 TS planModeV2 + EnterPlanMode/ExitPlanMode 工具。"""
from __future__ import annotations
from dataclasses import dataclass, field
from enum import Enum
from pathlib import Path
from uuid import UUID, uuid4


class PlanModeStatus(str, Enum):
    INACTIVE = "inactive"
    ACTIVE = "active"           # 進 plan mode,工具受限
    AWAITING_APPROVAL = "awaiting_approval"  # 模型 call ExitPlanMode 後等使用者按鈕


@dataclass
class PlanModeState:
    status: PlanModeStatus = PlanModeStatus.INACTIVE
    plan_id: UUID | None = None
    plan_file: Path | None = None
    """plan 寫到的檔案路徑(供使用者 review)。"""

    entered_at_message_uuid: str | None = None
    """進 plan mode 那輪的 message UUID(便於 exit 時回到該點)。"""


def enter_plan_mode(state: PlanModeState, plan_dir: Path) -> PlanModeState:
    if state.status != PlanModeStatus.INACTIVE:
        raise ValueError(f"Cannot enter plan mode from status {state.status}")
    plan_id = uuid4()
    plan_file = plan_dir / f"{plan_id}.md"
    plan_file.parent.mkdir(parents=True, exist_ok=True)
    plan_file.touch()
    return PlanModeState(
        status=PlanModeStatus.ACTIVE,
        plan_id=plan_id,
        plan_file=plan_file,
    )


def submit_plan(state: PlanModeState) -> PlanModeState:
    """模型 call ExitPlanMode → 等使用者批准。"""
    if state.status != PlanModeStatus.ACTIVE:
        raise ValueError("Not in plan mode")
    return PlanModeState(
        status=PlanModeStatus.AWAITING_APPROVAL,
        plan_id=state.plan_id,
        plan_file=state.plan_file,
        entered_at_message_uuid=state.entered_at_message_uuid,
    )


def approve_and_exit(state: PlanModeState) -> PlanModeState:
    """使用者 approve → 退出 plan mode。"""
    return PlanModeState(status=PlanModeStatus.INACTIVE)
```

### 5.4 `plan_mode/restrictions.py`

```python
"""Plan mode 下的工具限制。"""
from __future__ import annotations
from claude_agent_py.plan_mode.state import PlanModeState, PlanModeStatus


# Plan mode 下允許的工具(必須是 read-only / 純查詢)
PLAN_MODE_ALLOWED_TOOLS = {
    "Read", "Grep", "Glob", "WebFetch", "WebSearch",
    "LSP", "Agent",  # spawn read-only sub-agent
    "ExitPlanMode",  # 必須能退出
    "ToolSearch",
}


def is_tool_allowed_in_plan_mode(tool_name: str, plan_state: PlanModeState) -> bool:
    """檢查工具是否在 plan mode 下能用。"""
    if plan_state.status != PlanModeStatus.ACTIVE:
        return True  # 不在 plan mode,不限制
    return tool_name in PLAN_MODE_ALLOWED_TOOLS
```

整合到 `can_use_tool`:

```python
# permissions/decisions.py 改造

async def policy_based_can_use_tool(tool, input, ctx, tool_use_id):
    # 先 check plan mode
    if hasattr(ctx, "plan_mode_state"):
        if not is_tool_allowed_in_plan_mode(tool.name, ctx.plan_mode_state):
            return "deny"

    # 再走 policy engine(Phase 7)
    return policy.evaluate(tool.name, input.model_dump())
```

### 5.5 `state/app_state.py`(詳細模型)

```python
"""AppState — Conversation 的 UI / runtime state。

不同於 AgentContext(執行 context),AppState 是更上層的「應用狀態」。
對應 TS state/AppState.tsx 與 AppStateStore.ts。

簡化版:不做 Redux 全套,用 Pydantic + 不可變 update。
"""
from __future__ import annotations
from dataclasses import dataclass, field
from pathlib import Path
from uuid import UUID, uuid4


@dataclass
class ToolPermissionContext:
    """已決策過的權限歷史。"""
    granted: dict[str, list[str]] = field(default_factory=dict)
    """tool_name → list of input patterns 已 allow。"""

    denied: dict[str, list[str]] = field(default_factory=dict)
    """同上,already deny。"""

    additional_working_directories: dict[Path, str] = field(default_factory=dict)
    """允許工具操作的額外 cwd。Key 是路徑,value 是「為何允許」紀錄。"""

    bypass_permissions: bool = False
    """全部繞過(危險,僅 dev 用)。"""


@dataclass
class IDEContext:
    connected: bool = False
    """是否連接 IDE(VS Code 等)。"""
    selection: str | None = None
    """IDE 當前選取文字。"""
    cursor_file: Path | None = None
    """IDE 當前游標所在檔案。"""


@dataclass
class AppState:
    """Session 的應用狀態(廣義)。"""
    session_id: UUID = field(default_factory=uuid4)
    tool_permission_context: ToolPermissionContext = field(default_factory=ToolPermissionContext)
    ide_context: IDEContext = field(default_factory=IDEContext)
    plan_mode_state: "PlanModeState | None" = None
    mcp_server_statuses: dict[str, str] = field(default_factory=dict)
    """server_name → 'connected' / 'failed' / 'pending'。"""

    pending_attachments: list[dict] = field(default_factory=list)
    """從 Phase 11 input pipeline 累積的 attachments(@file 內容等)。"""

    def with_plan_mode(self, plan_state) -> "AppState":
        """immutable update。"""
        from dataclasses import replace
        return replace(self, plan_mode_state=plan_state)
```

### 5.6 `utils/file_state.py`(staleness check)

```python
"""File state cache。對應 TS utils/fileStateCache.ts。

用途:Edit / Write tool 強制要求「先 Read 過該檔」,而且讀後檔案沒被外部修改。
否則模型可能基於過時內容做 edit,造成資料毀損。
"""
from __future__ import annotations
from dataclasses import dataclass, field
from pathlib import Path


@dataclass
class FileSnapshot:
    """Read 時記錄的快照。"""
    path: Path
    mtime_ns: int
    """讀的當下 mtime。Edit 時若 mtime 變了 → 檔案被外部改過。"""

    size: int
    """檔案大小(double check)。"""


class FileStateCache:
    """跨 turn 的 file Read 快取。"""

    def __init__(self):
        self._snapshots: dict[Path, FileSnapshot] = {}

    def record_read(self, path: Path) -> None:
        """FileReadTool 完成讀取後呼叫。"""
        path = path.resolve()
        if not path.exists():
            return
        stat = path.stat()
        self._snapshots[path] = FileSnapshot(
            path=path,
            mtime_ns=stat.st_mtime_ns,
            size=stat.st_size,
        )

    def has_been_read(self, path: Path) -> bool:
        return path.resolve() in self._snapshots

    def is_stale(self, path: Path) -> bool:
        """檔案讀過後是否被外部修改?"""
        path = path.resolve()
        snap = self._snapshots.get(path)
        if snap is None:
            return True  # 沒讀過 → stale
        if not path.exists():
            return True
        stat = path.stat()
        return stat.st_mtime_ns != snap.mtime_ns or stat.st_size != snap.size

    def __contains__(self, path) -> bool:
        return self.has_been_read(Path(path))


# 整合到 FileEditTool / FileWriteTool 的 call:
# if not ctx.read_file_state.has_been_read(path):
#     yield ErrorEvent(message="Must Read this file first before editing.")
#     return
# if ctx.read_file_state.is_stale(path):
#     yield ErrorEvent(message="File modified externally since last Read. Re-read first.")
#     return
```

## 6. 設計決策與取捨

### 為何 sideQuery 不寫 transcript?

side query 是「實作細節」,user 不需要看到「Sonnet 挑了哪些 memory」。寫 transcript 會:
- 污染對話歷史
- resume 時 user 會困惑
- 增加 transcript 大小

對應 TS 的 `skipTranscript: true`。

### 為何 forked_agent 用 CacheSafeParams 而非直接傳 Conversation?

CacheSafeParams 是**精準取**「快取相關的部分」。直接傳 Conversation 會曝露 mutable state(`mutable_messages` 隨後續修改)。

明確 capture 一個 immutable 快照 → fork 時 byte-identical → cache hit。

### 為何 Plan mode 是 state machine 而非 boolean?

三狀態(INACTIVE / ACTIVE / AWAITING_APPROVAL)允許區分:
- ACTIVE:模型在 plan,工具受限
- AWAITING_APPROVAL:plan 寫好等 user 按鈕,工具完全 deny

若只用 boolean(in_plan_mode = True/False),沒辦法表達「等批准」這個中間狀態。對應 TS planModeV2 也是 state machine。

### 為何 file state cache 不直接用 mtime 比?

只比 mtime 偶有 false positive(touch 過但內容沒變)。加 size double-check 抓常見變動。完全準確要 hash,但太貴(每次 stat 又要 hash)。Phase 12 用 mtime + size 是 80/20 解。

### 為何 AppState 不做 Redux 全套?

Phase 12 只需要狀態容器,不需要 action / reducer / middleware。Redux 模式對 React 有用(因為 React 元件需要訂閱 state 變化),Python backend 不需要這層抽象。

**直接用 dataclass + immutable update**(`dataclasses.replace`)夠用。

### Phase 12 故意不做的

| 項目 | 理由 |
|---|---|
| 完整 Redux store(reducers / actions / middleware)| Python backend 不需要 |
| File hash check(SHA-256)| mtime + size 夠用 |
| Plan mode 多步驟(子計畫)| 一層就夠,複雜需求另說 |

## 7. 驗收標準

```bash
pytest tests/utils/test_side_query.py tests/utils/test_forked_agent.py \
       tests/plan_mode/ tests/state/ tests/utils/test_file_state.py -v
```

關鍵測試:

- `test_side_query.py`:
  - 結構化輸出(JSON Schema)正確 parse
  - 不寫 transcript 驗證
  - abort signal 取消生效

- `test_forked_agent_cache_hit.py`:
  - 跑兩次 fork(prefix 一樣)→ 第二次 cache_read > 0
  - 改 prefix → cache_read = 0(驗證 byte-identical 必要)

- `test_plan_mode.py`:
  - 進 plan mode → Edit 工具 deny
  - 進 plan mode → Read 工具 allow
  - submit_plan → 任何工具 deny
  - approve_and_exit → 工具恢復

- `test_file_staleness.py`:
  - Read 後 → has_been_read = True
  - 外部修改後 → is_stale = True
  - Edit 沒先 Read → 拒絕

### 手動驗證

```bash
# Plan mode
> /init   # 觸發 plan mode 風格的探索
# 模型 ExitPlanMode 後等 user approve
# Approve → 開始實作

# File staleness
> Read /tmp/foo.py
# (在另一個終端 echo "x" >> /tmp/foo.py)
> Edit /tmp/foo.py to add a function
# 預期模型收到 stale 錯誤,要求重 Read
```

## 8. 常見踩雷

### 踩雷 1:sideQuery 共用 anthropic client 的 rate limit

主對話 + memory selector + compact summary 共用一個 anthropic API key → 同 rate limit pool。**高 QPS 時 side query 會擠走主對話的容量**。

解法:
- 監控 rate limit headers
- side query 用低優先 retry / backoff
- production 用 dedicated key for side queries

### 踩雷 2:fork cache 失效

fork 想命中 cache,但**任何細節變動**都會 miss:
- system prompt 多一個空白
- tools list 順序變
- 訊息 timestamp 不同(若有寫進 message)

要嚴格 byte-identical。在 Phase 4 的 system prompt 組裝時就要保證 deterministic ordering。

### 踩雷 3:Plan mode 工具限制 vs sub-agent

進 plan mode 後 spawn 子 agent(`Agent` tool)— 子 agent **是否也在 plan mode**?

設計決策:子 agent **不繼承** plan mode(spawn 時新 ctx)。但子 agent 自己有獨立 plan mode 狀態。這樣父 agent 能 spawn 子 agent 跑「實作預覽」(子 agent 在 plan mode 外可寫檔)。

對應 TS 的設計也是這樣。

### 踩雷 4:File state 跨 session

`FileStateCache` 是 per-session 的。Resume 後新 session **不繼承**舊 cache → 第一個 Edit 都會被 reject。

解法:resume 時把 transcript 中所有 Read 的 file_path 重 stat,重建 cache。

### 踩雷 5:AppState 不可變化更新

```python
state.plan_mode_state = ...  # ❌ 直接 mutate
state = state.with_plan_mode(...)  # ✅ immutable
```

養成習慣。否則 multi-task 並發改 state 會 race。

### 踩雷 6:sideQuery max_tokens 太小被截

`max_tokens: 256` 對 memory selector 的 5 個 filename + JSON 框架夠用。但若 selector 改成「總結這段對話」就遠遠不夠。要 case by case 配,不能寫死。

### 踩雷 7:fork 子 agent 寫到主 agent 的 memory dir

對應 docs/07 §7。fork 寫權限應該限縮(`createAutoMemCanUseTool`)。否則惡意 prompt 注入可讓子 agent 寫亂主 agent 的 MEMORY.md。

## 9. 完成清單

- [ ] `side_query` 通用機制
- [ ] Phase 3 memory selector 改用 side_query
- [ ] `forked_agent` 機制 + CacheSafeParams
- [ ] Phase 3 extract_memories 改用 forked_agent
- [ ] Phase 1 AgentTool 改用 forked_agent
- [ ] Plan mode 三狀態機
- [ ] Plan mode 工具限制整合 can_use_tool
- [ ] AppState 詳細模型
- [ ] FileStateCache + staleness check
- [ ] FileEditTool / FileWriteTool 加 staleness check
- [ ] 寫 Phase 12 心得

# Phase 3:Memory & Compaction(記憶與壓縮)

## 速覽

- **預計時程**:3-4 週
- **前置 Phase**:Phase 1(agent loop)+ Phase 2(storage)
- **後續 Phase**:Phase 4(system prompt)會把 `loadMemoryPrompt` 接到 prompt section
- **主要交付物**:
  - memdir(MEMORY.md + 4 類 frontmatter)
  - `find_relevant_memories`(用 Sonnet sideQuery 動態挑選)
  - `extract_memories` fork agent(背景萃取)
  - AutoCompact + reactive compact + snip projection
  - Tombstone 機制

## ⚠️ Web Chat 場景調整(per-user 而非 per-project)

> **TS 原設計**:CLI 在 git repo 內跑 → memory 路徑為 `<project_root>/memory/`
>
> **Web chat 改為**:User 透過瀏覽器連線,**沒有 cwd / git repo 概念**。
>
> **改 per-user**:
> - 路徑改為 `users/<user_id>/memory/`(本機 dev)或 **直接存 Postgres**(production)
> - `find_canonical_git_root` 邏輯**整段刪掉**
> - `is_auto_mem_path` 用 user_id 判斷而非路徑前綴
> - `MEMORY.md` 索引存 DB row(`user_memories_index` 表)
> - Topic 檔存 DB row(`user_memories` 表,user_id + name 唯一)
>
> 完整 skeleton 見本 phase § 5.1 修正版。

## 1. 目標與動機

Phase 1-2 處理短期 / session 內狀態。Phase 3 加上**跨 user 長期記憶**(原 TS 是 per-project,web chat 改 per-user)與**長對話自動壓縮**:

```
無 memory:每個對話都從零開始,使用者要重複介紹自己 / 偏好
有 memory:跨對話累積使用者偏好、專案脈絡、外部系統指標

無 compaction:對話到 200K token 直接爆 / 自動截斷丟資訊
有 compaction:接近上限自動摘要前段、保留近期、tombstone 標記
```

**對應 docs**:
- [docs/07](../07-memory-system.md) 整章必讀(記憶系統完整剖析)
- [docs/06 模組 3-4](../06-harness-engineering.md) Memory 與 Context Management

完成本 phase 後,你的 agent 有「個性化」與「長對話能力」。

## 2. TS 源檔映射

| Python 模組 | 對應 TS 源檔 | 行數 | 注意事項 |
|---|---|---|---|
| `src/memory/paths.py` | `src/memdir/paths.ts` | 279 | per-project 路徑解析 + 安全性 |
| `src/memory/memdir.py` | `src/memdir/memdir.ts` | 508 | `load_memory_prompt`、雙重截斷 |
| `src/memory/types.py` | `src/memdir/memoryTypes.ts` | 22 KB | 4 類定義 + frontmatter 範本 |
| `src/memory/scan.py` | `src/memdir/memoryScan.ts` | 95 | 掃 .md 讀前 30 行 frontmatter |
| `src/memory/relevance.py` | `src/memdir/findRelevantMemories.ts` | 142 | **用 Sonnet sideQuery 挑選** |
| `src/memory/extract.py` | `src/services/extractMemories/extractMemories.ts` | 21 KB | Fork agent 背景萃取 |
| `src/memory/extract_prompts.py` | `src/services/extractMemories/prompts.ts` | 7.7 KB | 萃取 agent 的 user prompt |
| `src/compact/auto.py` | `src/services/compact/autoCompact.ts` | 中 | 主動壓縮 |
| `src/compact/reactive.py` | `src/services/compact/reactiveCompact.ts` | 中 | API 回 prompt-too-long 時觸發 |
| `src/compact/snip.py` | `src/services/compact/snipCompact.ts` + `snipProjection.ts` | 大 | 截大型工具輸出 |
| `src/compact/strategies.py` | `src/services/compact/compact.ts` | 中 | `buildPostCompactMessages` |

## 3. 任務拆解

### Week 1:Memdir 結構 + 讀取(整本注入)

- [ ] 1.1 `memory/paths.py`:`get_auto_mem_path`(per-project 解析 + 4 種優先序)
- [ ] 1.2 `memory/types.py`:4 類 enum、frontmatter 範本字串
- [ ] 1.3 `memory/scan.py`:`scan_memory_files`(讀前 30 行)、`format_memory_manifest`
- [ ] 1.4 `memory/memdir.py`:`load_memory_prompt`(整本 MEMORY.md + 行為指引)
- [ ] 1.5 `truncate_entrypoint_content`(雙重上限 200 行 / 25 KB)
- [ ] 1.6 測試:截斷正確、警告字串、4 類 frontmatter 解析

### Week 2:相關性挑選(Sonnet)+ 注入

- [ ] 2.1 `memory/relevance.py`:`find_relevant_memories`(scan + selectRelevantMemories)
- [ ] 2.2 `select_relevant_memories`:用 anthropic Sonnet sideQuery + JSON Schema(**進階版見 [Phase 12](./12-internal-mechanics.md) `side_query` 通用機制**)
- [ ] 2.3 6 種跳過條件(see docs/07 §6)
- [ ] 2.4 `start_relevant_memory_prefetch`(turn 開頭非阻塞觸發)
- [ ] 2.5 整合到 Phase 1 的 `query_loop`(yield attachment)
- [ ] 2.6 測試:相關 prompt 挑對、單字 prompt 跳過、已 surface 過不重選

### Week 3:Fork 萃取 + 互斥

- [ ] 3.1 `memory/extract.py`:`run_extraction`(handleStopHooks 觸發)
- [ ] 3.2 `has_memory_writes_since`(主 agent 已寫過 → 跳過)
- [ ] 3.3 `create_auto_mem_can_use_tool`(限縮權限 — 只能 Read/Grep/Glob/read-only Bash/寫到 memory dir)
- [ ] 3.4 `run_forked_agent` 整合(共享父 prompt cache)— **完整實作見 [Phase 12](./12-internal-mechanics.md)**
- [ ] 3.5 節流(預設每 turn 跑、可調)
- [ ] 3.6 測試:主 agent 寫過 → fork 跳過;沒寫 → fork 跑
- [ ] 3.7 **完整 Team Memory Sync**(若 enable team feature):對應 TS `services/teamMemorySync/`(44 KB)
   - `index.ts`(主邏輯):從 git remote 拉 / push team memory dir
   - `secretScanner.ts`(9.5 KB):掃描密文(API key / token / password)防止上傳
   - `watcher.ts`(13 KB):本地檔案 watch + auto-sync
   - `teamMemSecretGuard.ts`(1.5 KB):secret 守門
   - 用 `gitpython` 操作 git;`detect-secrets` lib 掃密文

### Week 4:Compaction + Tombstone

- [ ] 4.1 `compact/auto.py`:`auto_compact`(每輪檢查 token 接近上限)
- [ ] 4.2 `compact/reactive.py`:接到 prompt-too-long → 強制 compact 重試
- [ ] 4.3 `compact/snip.py`:截大型工具輸出
- [ ] 4.4 Tombstone 標記(壓縮過的訊息不送 API 但保留供 UI/resume)
- [ ] 4.5 整合到 `query_loop`
- [ ] 4.6 測試:長對話自動壓縮、preservedSegment 保 resume 連貫
- [ ] 4.7 寫 Phase 3 心得

## 4. 模組架構與檔案

```
src/claude_agent_py/
├── memory/
│   ├── __init__.py
│   ├── paths.py                       # ◀ NEW per-project 路徑
│   ├── types.py                       # ◀ NEW 4 類 + frontmatter 範本
│   ├── scan.py                        # ◀ NEW frontmatter 掃描
│   ├── memdir.py                      # ◀ NEW load_memory_prompt
│   ├── relevance.py                   # ◀ NEW Sonnet selector
│   ├── extract.py                     # ◀ NEW fork 萃取
│   └── extract_prompts.py             # ◀ NEW 萃取 agent prompts
│
├── compact/
│   ├── __init__.py
│   ├── auto.py                        # ◀ NEW 主動壓縮
│   ├── reactive.py                    # ◀ NEW 反應式壓縮
│   ├── snip.py                        # ◀ NEW 工具輸出截斷
│   └── strategies.py                  # ◀ NEW 通用 compact 邏輯
│
└── core/
    └── query_loop.py                  # ◀ 擴充:整合 compaction 檢查
```

## 5. Python Skeleton

### 5.1 `memory/paths.py`(Web Chat 版,per-user)

```python
"""Memory 路徑解析(per-user)。

差異於 TS 原版:沒有 git_root / project_root 概念。
本機 dev 用 fs(per-user 目錄);production 用 Postgres(直接存 DB row)。
"""
from __future__ import annotations
import os
from pathlib import Path


def get_memory_base_dir() -> Path:
    """本機 dev 用 fs。"""
    if env := os.environ.get("CLAUDE_AGENT_DATA_DIR"):
        return Path(env)
    return Path("~/.claude_agent_py").expanduser()


def get_user_memory_dir(user_id: str) -> Path:
    """per-user memory 目錄(本機 dev)。"""
    base = get_memory_base_dir()
    d = base / "users" / user_id / "memory"
    d.mkdir(parents=True, exist_ok=True)
    return d


def get_user_memory_entrypoint(user_id: str) -> Path:
    """MEMORY.md 路徑。"""
    return get_user_memory_dir(user_id) / "MEMORY.md"


# Production 模式:直接存 Postgres,沒 fs path
# (本檔案在 production 模式下 unused,改用 src/storage/postgres.py 的 user_memories 表)
```

### 5.1b `storage/postgres.py` 補充(production 用)

```python
"""User memory tables(production)。"""
from sqlalchemy import String, Text, ForeignKey, JSON, Index
from sqlalchemy.orm import Mapped, mapped_column


class UserMemory(Base):
    """單一 memory topic(對應 TS 的 .md 檔)。"""
    __tablename__ = "user_memories"

    id: Mapped[UUID] = mapped_column(primary_key=True, default=uuid4)
    user_id: Mapped[str] = mapped_column(ForeignKey("users.id"), index=True)
    name: Mapped[str] = mapped_column(String(255))
    description: Mapped[str] = mapped_column(Text)
    type: Mapped[str] = mapped_column(String(20))  # user/feedback/project/reference
    content: Mapped[str] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(default=datetime.utcnow)
    updated_at: Mapped[datetime] = mapped_column(default=datetime.utcnow, onupdate=datetime.utcnow)

    __table_args__ = (
        Index("ix_user_name", "user_id", "name", unique=True),
    )


# MEMORY.md 索引可從 user_memories 動態組(不需要獨立表)
# 或快取到 Redis 加速

async def get_memory_index(user_id: str, db) -> str:
    """重組 MEMORY.md 內容(從 user_memories 表)。"""
    rows = (await db.execute(
        select(UserMemory).where(UserMemory.user_id == user_id)
        .order_by(UserMemory.updated_at.desc())
    )).scalars().all()

    lines = [
        f"- [{m.name}](memory/{m.name}.md) — {m.description}"
        for m in rows
    ]
    return "\n".join(lines)
```

### 5.1c `is_auto_mem_path` 改用 user_id 判斷

```python
def is_user_memory_path(path: Path, user_id: str) -> bool:
    """是否在 user 自己的 memory 範圍內(供 write carve-out)。"""
    user_dir = get_user_memory_dir(user_id)
    try:
        path.relative_to(user_dir)  # 拋例外 = 不在內
        return True
    except ValueError:
        return False
```

### 5.2 `memory/memdir.py`

```python
"""MEMORY.md 載入與行為指引組裝。對應 TS memdir/memdir.ts。"""
from __future__ import annotations
from dataclasses import dataclass
from pathlib import Path

from claude_agent_py.memory.paths import get_auto_mem_entrypoint, get_auto_mem_path
from claude_agent_py.memory.types import build_memory_lines


MAX_ENTRYPOINT_LINES = 200
MAX_ENTRYPOINT_BYTES = 25_000


@dataclass
class EntrypointTruncation:
    content: str
    line_count: int
    byte_count: int
    was_line_truncated: bool
    was_byte_truncated: bool


def truncate_entrypoint_content(raw: str) -> EntrypointTruncation:
    """雙重上限截斷。對應 TS memdir.ts:57。"""
    trimmed = raw.strip()
    lines = trimmed.split("\n")
    line_count = len(lines)
    byte_count = len(trimmed.encode("utf-8"))

    was_line_trunc = line_count > MAX_ENTRYPOINT_LINES
    was_byte_trunc = byte_count > MAX_ENTRYPOINT_BYTES

    if not was_line_trunc and not was_byte_trunc:
        return EntrypointTruncation(trimmed, line_count, byte_count, False, False)

    truncated = "\n".join(lines[:MAX_ENTRYPOINT_LINES]) if was_line_trunc else trimmed
    truncated_bytes = truncated.encode("utf-8")
    if len(truncated_bytes) > MAX_ENTRYPOINT_BYTES:
        # 切到最後一個 \n 之前
        cut = truncated_bytes[:MAX_ENTRYPOINT_BYTES].rfind(b"\n")
        if cut > 0:
            truncated = truncated_bytes[:cut].decode("utf-8")
        else:
            truncated = truncated_bytes[:MAX_ENTRYPOINT_BYTES].decode("utf-8", errors="ignore")

    reason = (
        f"{byte_count:,} bytes (limit: {MAX_ENTRYPOINT_BYTES:,})"
        if was_byte_trunc and not was_line_trunc
        else f"{line_count} lines (limit: {MAX_ENTRYPOINT_LINES})"
        if was_line_trunc and not was_byte_trunc
        else f"{line_count} lines and {byte_count:,} bytes"
    )

    warning = (
        f"\n\n> WARNING: MEMORY.md is {reason}. Only part of it was loaded. "
        f"Keep index entries to one line under ~200 chars; move detail into topic files."
    )

    return EntrypointTruncation(
        content=truncated + warning,
        line_count=line_count,
        byte_count=byte_count,
        was_line_truncated=was_line_trunc,
        was_byte_truncated=was_byte_trunc,
    )


async def load_memory_prompt() -> str | None:
    """組裝整段 memory prompt(主行為指引 + MEMORY.md 內容)。

    對應 TS loadMemoryPrompt(memdir.ts:419)。
    """
    mem_dir = get_auto_mem_path()
    mem_dir.mkdir(parents=True, exist_ok=True)

    entrypoint = get_auto_mem_entrypoint()

    lines = build_memory_lines(display_name="auto memory", memory_dir=str(mem_dir))

    if entrypoint.exists():
        try:
            content = entrypoint.read_text(encoding="utf-8")
            t = truncate_entrypoint_content(content)
            lines.append(f"\n## MEMORY.md\n\n{t.content}")
        except Exception:
            pass
    else:
        lines.append(
            "\n## MEMORY.md\n\nYour MEMORY.md is currently empty. "
            "When you save new memories, they will appear here."
        )

    return "\n".join(lines)
```

### 5.3 `memory/relevance.py`(關鍵:Sonnet selector)

```python
"""動態挑選相關記憶。對應 TS memdir/findRelevantMemories.ts。

關鍵:**用 Sonnet sideQuery 挑選**,不是關鍵字也不是 embedding。
"""
from __future__ import annotations
from dataclasses import dataclass
from pathlib import Path

import anthropic


SELECT_MEMORIES_SYSTEM_PROMPT = """You are selecting memories that will be useful to Claude Code as it processes a user's query. You will be given the user's query and a list of available memory files with their filenames and descriptions.

Return a list of filenames for the memories that will clearly be useful to Claude Code as it processes the user's query (up to 5). Only include memories that you are certain will be helpful based on their name and description.
- If you are unsure if a memory will be useful in processing the user's query, then do not include it in your list. Be selective and discerning.
- If there are no memories in the list that would clearly be useful, feel free to return an empty list.
- If a list of recently-used tools is provided, do not select memories that are usage reference or API documentation for those tools. DO still select memories containing warnings, gotchas, or known issues about those tools.
"""


@dataclass
class RelevantMemory:
    path: Path
    mtime: float


async def find_relevant_memories(
    query: str,
    memory_dir: Path,
    *,
    recent_tools: list[str] | None = None,
    already_surfaced: set[Path] | None = None,
) -> list[RelevantMemory]:
    """掃 memory dir → manifest → 用 Sonnet 挑 → 返回 path list。

    對應 TS findRelevantMemories.ts:39。
    """
    from claude_agent_py.memory.scan import scan_memory_files, format_memory_manifest

    already_surfaced = already_surfaced or set()
    headers = await scan_memory_files(memory_dir)
    headers = [h for h in headers if h.file_path not in already_surfaced]

    if not headers:
        return []

    selected_filenames = await _select_relevant_memories(
        query, headers, recent_tools or []
    )
    by_filename = {h.filename: h for h in headers}
    selected = [by_filename[f] for f in selected_filenames if f in by_filename]
    return [RelevantMemory(path=h.file_path, mtime=h.mtime) for h in selected]


async def _select_relevant_memories(
    query: str,
    memories: list,
    recent_tools: list[str],
) -> list[str]:
    """用 Sonnet 挑選。用 JSON Schema 強制輸出格式。"""
    manifest = "\n".join(
        f"- [{m.type}] {m.filename}: {m.description}"
        for m in memories
    )
    tools_section = (
        f"\n\nRecently used tools: {', '.join(recent_tools)}"
        if recent_tools else ""
    )

    client = anthropic.AsyncAnthropic()
    response = await client.messages.create(
        model="claude-sonnet-4-6",
        system=SELECT_MEMORIES_SYSTEM_PROMPT,
        messages=[{
            "role": "user",
            "content": f"Query: {query}\n\nAvailable memories:\n{manifest}{tools_section}",
        }],
        max_tokens=256,
        # 用 tool 強制 JSON Schema 輸出
        tools=[{
            "name": "select_memories",
            "description": "Return list of relevant memory filenames",
            "input_schema": {
                "type": "object",
                "properties": {
                    "selected_memories": {
                        "type": "array",
                        "items": {"type": "string"},
                    }
                },
                "required": ["selected_memories"],
            },
        }],
        tool_choice={"type": "tool", "name": "select_memories"},
    )

    for block in response.content:
        if block.type == "tool_use" and block.name == "select_memories":
            return block.input.get("selected_memories", [])
    return []


def should_skip_prefetch(messages: list, ctx) -> bool:
    """6 種跳過條件。對應 TS attachments.ts:startRelevantMemoryPrefetch。"""
    last_user = next((m for m in reversed(messages) if m.role == "user"), None)
    if last_user is None:
        return True
    text = last_user.content if isinstance(last_user.content, str) else ""
    if not text or " " not in text.strip():
        return True  # 單字 prompt
    # ... 其他條件:already surfaced size、feature flag 等
    return False
```

### 5.4 `memory/extract.py`(背景萃取)

```python
"""Fork agent 背景萃取。對應 TS services/extractMemories/extractMemories.ts。"""
from __future__ import annotations
from pathlib import Path
from uuid import UUID

from claude_agent_py.memory.paths import get_auto_mem_path, is_auto_mem_path


def has_memory_writes_since(messages: list, since_uuid: str | None) -> bool:
    """掃自 cursor 後是否主 agent 已寫過 memory。

    對應 TS hasMemoryWritesSince。
    """
    found_start = since_uuid is None
    for m in messages:
        if not found_start:
            if m.uuid == since_uuid:
                found_start = True
            continue
        if m.role != "assistant":
            continue
        # 掃 m.content 找 Edit/Write 對 memory dir 的 tool_use
        if not isinstance(m.content, list):
            continue
        for block in m.content:
            if block.get("type") != "tool_use":
                continue
            if block.get("name") not in ("Edit", "Write"):
                continue
            input_dict = block.get("input", {})
            file_path = input_dict.get("file_path")
            if file_path and is_auto_mem_path(Path(file_path)):
                return True
    return False


def create_auto_mem_can_use_tool(memory_dir: Path):
    """限縮 fork 的權限:只能 Read/Grep/Glob/read-only Bash/寫到 memory dir。

    對應 TS createAutoMemCanUseTool。
    """
    READ_ONLY = {"Read", "Grep", "Glob"}

    async def can_use(tool, input, ctx, tool_use_id):
        if tool.name in READ_ONLY:
            return "allow"
        if tool.name == "Bash":
            if tool.is_read_only(input):
                return "allow"
            return "deny"
        if tool.name in ("Edit", "Write"):
            file_path = getattr(input, "file_path", None)
            if file_path and is_auto_mem_path(Path(file_path)):
                return "allow"
        return "deny"

    return can_use


class ExtractMemoriesRunner:
    """背景萃取主邏輯。對應 TS extractMemories.ts:runExtraction。"""

    def __init__(self):
        self.last_message_uuid: str | None = None
        self.in_progress = False
        self.turns_since_last = 0

    async def run(self, ctx, messages, append_system_message) -> None:
        """每 query 結束(handleStopHooks)觸發。"""
        if has_memory_writes_since(messages, self.last_message_uuid):
            # 主 agent 已寫過,推進 cursor 跳過
            if messages:
                self.last_message_uuid = messages[-1].uuid
            return

        self.turns_since_last += 1
        if self.turns_since_last < 1:  # tengu_bramble_lintel 預設 1
            return
        self.turns_since_last = 0

        # 啟動 fork agent(共享父 prompt cache)
        # 細節:用 Phase 1 的 Conversation,但帶 createAutoMemCanUseTool
        # + 預先注入 manifest(避免 fork 用 ls turn)
        # + maxTurns=5 硬上限
        ...
```

### 5.5 `compact/auto.py`

```python
"""主動壓縮。對應 TS services/compact/autoCompact.ts。"""
from __future__ import annotations


def calculate_token_warning_state(messages: list, max_tokens: int) -> dict:
    """估算當前 token 用量,接近上限時警告。"""
    # 估法:用 Anthropic SDK 的 count_tokens API,或自寫 rough estimator
    ...


async def auto_compact(messages: list, ctx) -> list | None:
    """若 token 接近上限,壓縮前段。

    返回 None 表示無需 compact;否則返回新 messages(含 tombstone)。
    對應 TS autoCompact.ts。
    """
    state = calculate_token_warning_state(messages, ctx.token_budget.max_input_tokens)
    if not state["should_compact"]:
        return None

    # 把前段對話交給 Sonnet 摘要
    summary = await _summarize_messages(messages[: state["compact_until"]])

    # 後段保留,前段變 tombstone + 開頭加摘要
    new_messages = [
        SystemMessage(content=f"[Previous conversation summarized]\n{summary}"),
        *_make_tombstones(messages[: state["compact_until"]]),
        *messages[state["compact_until"]:],
    ]
    return new_messages


async def _summarize_messages(messages: list) -> str:
    """用 Sonnet 摘要。對應 TS compact.ts:buildPostCompactMessages。"""
    ...
```

## 6. 設計決策與取捨

### 為何 selector 用 LLM 而非 embedding?

(回顧 docs/07 設計取捨)
- 索引最多 200 條,可一次塞進 256 token selector context
- LLM 對「相關性」精細度高(同字串不同 context 不同意義)
- 沒有 embedding 服務依賴 / stale 問題
- 成本低($0.003-0.006/次)

Python port 直接照搬。

### 為何雙寫入路徑(主 agent + fork 萃取)?

- 主 agent 直寫:使用者明確要求,當下記
- Fork 萃取:背景挖,使用者沒明說但對話有值得記的

互斥(`hasMemoryWritesSince`)避免重複。

### 為何 Tombstone 而非真刪除?

- UI 仍要顯示「這段對話被壓縮了」
- Resume 時要正確重建 preservedSegment
- 後續 export 完整對話有資料

對應 TS 設計。

### 為何 frontmatter 只讀前 30 行?

平衡:讀整檔 200 個太貴、只讀 frontmatter 又無法判斷。30 行是經驗折衷,涵蓋絕大多數合理 frontmatter。

### Phase 3 故意不做的

| 項目 | 留給哪個 phase |
|---|---|
| KAIROS daily-log 模式 | 不做(scope 外) |
| TEAMMEM 團隊同步 | Phase 7+ 若需要 |
| Memory 跨 user 隔離 | Phase 7 |
| Embedding-based 進階檢索 | 不做(LLM 夠用) |

## 7. 驗收標準

### 自動測試

```bash
pytest tests/memory/ tests/compact/ -v
```

關鍵測試:

- `test_truncate_entrypoint.py`:雙重上限,警告字串正確
- `test_scan_frontmatter.py`:4 類正確、缺 type 視為 None、超過 30 行不讀
- `test_selector_relevance.py`:mock anthropic API,驗證 manifest 格式 + 解析
- `test_has_memory_writes_since.py`:cursor 邏輯正確
- `test_can_use_tool_carve_out.py`:Edit 寫到 memory dir allow、別處 deny
- `test_auto_compact.py`:接近上限觸發、tombstone 正確、resume 連貫

### 手動驗證

```bash
python -m claude_agent_py
> "我是 Go 工程師,React 是新接觸的"
# 觀察 memory dir 出現 user_role.md
ls ~/.claude_agent_py/projects/.../memory/
```

新 session:

```bash
python -m claude_agent_py
> "解釋這個 React component"
# 觀察 attachment 含 user_role.md
# 模型回應應該用「後端類比」風格
```

### 整合驗證

跑 30+ turn 對話:

- 觀察 token 用量逼近上限時自動壓縮
- 壓縮後對話繼續正常
- transcript 內含 tombstone 訊息
- resume 後對話一致

## 8. 常見踩雷

### 踩雷 1:Sonnet selector 失敗 fallback

API 失敗 / 解析失敗 / abort → 不要 crash。回 `[]` 跳過 prefetch:

```python
try:
    selected = await _select_relevant_memories(...)
except Exception as e:
    logger.warning(f"selector failed: {e}")
    return []
```

### 踩雷 2:fork agent 共享 prompt cache 設定

要確保 fork 的 system prompt + tools list + 訊息前綴與父 byte-identical,否則 cache miss。`createCacheSafeParams` 在 TS 是專門做這個。Python port 要重寫等價邏輯。

### 踩雷 3:tombstone 保留 metadata

壓縮時不能完全丟棄訊息,要保留:
- uuid
- timestamp
- tool_use_id (若有)

否則 resume 時 `applyPreservedSegmentRelinks` 失敗。

### 踩雷 4:writes_since 的 cursor 過期

若 cursor UUID 已被 compaction 移除,fallback 為「掃所有訊息」(視為全 fresh)。否則 cursor 永遠停在過時位置。

### 踩雷 5:相對日期 → 絕對日期

`project` 類記憶要求模型把「Thursday」轉成「2026-03-05」。這在 prompt 強制(見 `WHEN_TO_SAVE`),Python port 要把整段提示完整翻譯。

### 踩雷 6:reactive compact 與 retry 互動

API 回 `prompt-too-long` 時,先嘗試 reactive compact 重試一次。若還失敗 → 報錯。要在 `query_loop` 加 try/except 邏輯,**只試一次**(避免無限迴圈)。

## 9. 參考資料

### docs/01-11

- [docs/07](../07-memory-system.md) — 整章必讀
- [docs/06 模組 3-4](../06-harness-engineering.md) — 設計取捨
- [docs/05 §5c](../05-settings-memory-context.md) — Context 組合流程

### TS 源檔

- `src/memdir/memdir.ts` — 整檔 508 行
- `src/memdir/findRelevantMemories.ts` — 142 行,核心 selector 邏輯
- `src/services/extractMemories/extractMemories.ts` — 21 KB
- `src/services/compact/autoCompact.ts` — 主動壓縮

### 外部資源

- [Anthropic structured outputs via tools](https://docs.anthropic.com/en/docs/build-with-claude/tool-use)
- [GitPython](https://gitpython.readthedocs.io/) — find_canonical_git_root
- [python-frontmatter](https://python-frontmatter.readthedocs.io/) — 解析 markdown frontmatter

## 完成檢查表

- [ ] memdir 路徑解析(per-project)
- [ ] MEMORY.md 雙重上限截斷
- [ ] Sonnet selector 挑選
- [ ] 6 種跳過條件
- [ ] Fork 萃取 + 互斥
- [ ] 限縮 canUseTool
- [ ] AutoCompact + tombstone
- [ ] Reactive compact retry
- [ ] coverage > 75%
- [ ] 寫 Phase 3 心得

完成後進入 [Phase 4:System Prompt](./04-system-prompt.md)。

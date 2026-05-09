# Phase 2:Storage & State(持久化與狀態)

## 速覽

- **預計時程**:3-4 週
- **前置 Phase**:Phase 1 必須完成(`Conversation` + `query_loop` 跑通)
- **後續 Phase**:Phase 3(memory)、Phase 6(FastAPI)、Phase 7(production)會依賴本 phase 的持久化基礎
- **主要交付物**:
  - 工具結果三層持久化(對應 docs/09)
  - `ContentReplacementState`(frozen / mustReapply / fresh 三類分流)
  - File history snapshot(寫前快照)
  - Session storage(JSONL transcript)
  - `/resume <session-id>` 機制 + `reconstructContentReplacementState`

## 1. 目標與動機

Phase 1 跑通了 agent loop,但**所有狀態都在記憶體**:重啟丟失、長對話爆 token、不能 resume。Phase 2 加上**持久化與狀態管理**:

```
Phase 1: prompt → loop → result → 結束
Phase 2: prompt → loop → 大結果寫檔 → transcript JSONL →
         session 結束 → /resume → 重建 state → 繼續對話
```

**對應 docs**:
- [docs/09](../09-large-tool-results.md) 整章必讀(大結果三層防線)
- [docs/06 模組 7](../06-harness-engineering.md) State & Checkpointing

完成本 phase 後,你的系統有「記憶」 — 對話可中斷可恢復、大結果不爆 context、prompt cache 可命中。

## 2. TS 源檔映射

| Python 模組 | 對應 TS 源檔 | 行數 | 注意事項 |
|---|---|---|---|
| `src/storage/tool_result.py` | `src/utils/toolResultStorage.ts` | 1000+ | 三層持久化主邏輯 |
| `src/storage/replacement_state.py` | 同上 `ContentReplacementState` 部分 | — | frozen/mustReapply/fresh 分類 |
| `src/storage/file_history.py` | `src/utils/fileHistory.ts` | 中 | 寫檔前快照,supports undo |
| `src/storage/session.py` | `src/utils/sessionStorage.ts` | 中 | JSONL transcript |
| `src/storage/resume.py` | `src/commands/resume/resume.tsx` + `reconstructContentReplacementState` | — | 從 transcript 重建 state |
| `src/storage/mcp_output.py` | `src/utils/mcpOutputStorage.ts` | 中 | binary 與 large output 持久化 |
| `src/core/conversation.py`(擴充) | `src/QueryEngine.ts` mutableMessages 部分 | — | 整合 storage |

## 3. 任務拆解

### Week 1:工具結果第 2 層(通用持久化)

- [ ] 1.1 `storage/paths.py`:tool-results 目錄路徑(per-session)
- [ ] 1.2 `storage/tool_result.py`:`persist_tool_result` 寫檔
- [ ] 1.3 `generate_preview` + `build_large_tool_result_message`(2 KB preview + filepath)
- [ ] 1.4 `maybe_persist_large_tool_result`(空結果替換、image 跳過、size 判斷、persist)
- [ ] 1.5 整合到 `tool_execution.py`:工具完成後過 `processToolResultBlock`
- [ ] 1.6 測試:大結果寫檔、preview 正確、空結果替換

### Week 2:第 3 層(聚合預算)+ ReplacementState

- [ ] 2.1 `storage/replacement_state.py`:`ContentReplacementState`(seen_ids、replacements)
- [ ] 2.2 `partition_by_prior_decision`(mustReapply / frozen / fresh)
- [ ] 2.3 `select_fresh_to_replace`(挑最大幾個直到回到預算下)
- [ ] 2.4 `enforce_tool_result_budget` + `apply_tool_result_budget`
- [ ] 2.5 整合到 `query_loop.py`:每 turn 進 API 前過聚合預算
- [ ] 2.6 測試:N 並行工具撐爆預算 → 挑最大替換 / 凍結後不再變

### Week 3:File history + Session storage

- [ ] 3.1 `storage/file_history.py`:`make_snapshot` 寫前快照
- [ ] 3.2 整合到 `FileWriteTool` / `FileEditTool`(寫前先 snapshot)
- [ ] 3.3 `storage/session.py`:`SessionStorage` JSONL writer
- [ ] 3.4 `record_transcript`(每訊息追加一行)
- [ ] 3.5 整合到 `Conversation`:每 yield 訊息 record 一筆
- [ ] 3.6 測試:transcript 完整、JSONL 可解析

### Week 4:Resume 機制

- [ ] 4.1 `storage/resume.py`:`load_session` 從 JSONL 讀回 messages
- [ ] 4.2 `reconstruct_content_replacement_state`(從 records 重建 state)
- [ ] 4.3 `Conversation.resume(session_id)` 方法
- [ ] 4.4 整合測試:對話 → 結束 → resume → 繼續對話 → 預期 prompt cache 命中
- [ ] 4.5 寫 Phase 2 心得

## 4. 模組架構與檔案

```
src/claude_agent_py/
├── storage/
│   ├── __init__.py
│   ├── paths.py                       # ◀ NEW per-session 路徑
│   ├── tool_result.py                 # ◀ NEW 第 2 層持久化
│   ├── replacement_state.py           # ◀ NEW 第 3 層 + 三類分流
│   ├── file_history.py                # ◀ NEW 寫前快照
│   ├── session.py                     # ◀ NEW transcript JSONL
│   ├── resume.py                      # ◀ NEW resume 重建
│   └── mcp_output.py                  # ◀ NEW(Phase 5 才用,先 stub)
│
└── core/
    └── conversation.py                # ◀ 擴充:整合 storage
```

## 5. Python Skeleton

### 5.1 `storage/paths.py`

```python
"""Per-session 持久化路徑。對應 TS 的 ~/.claude/projects/.../tool-results/。"""
from __future__ import annotations
from pathlib import Path
from uuid import UUID
import os


def get_session_dir(session_id: UUID) -> Path:
    """每 session 一個目錄。

    Phase 2 用本機 fs;Phase 7 改成 S3 / 對象儲存。
    """
    base = Path(os.environ.get("CLAUDE_AGENT_DATA_DIR", "~/.claude_agent_py")).expanduser()
    d = base / "sessions" / str(session_id)
    d.mkdir(parents=True, exist_ok=True)
    return d


def get_tool_results_dir(session_id: UUID) -> Path:
    d = get_session_dir(session_id) / "tool-results"
    d.mkdir(parents=True, exist_ok=True)
    return d


def get_transcript_path(session_id: UUID) -> Path:
    return get_session_dir(session_id) / "transcript.jsonl"


def get_file_history_dir(session_id: UUID) -> Path:
    d = get_session_dir(session_id) / "file-history"
    d.mkdir(parents=True, exist_ok=True)
    return d
```

### 5.2 `storage/tool_result.py`

```python
"""第 2 層工具結果持久化。對應 TS utils/toolResultStorage.ts:272 maybePersistLargeToolResult。"""
from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from uuid import UUID
import json

from claude_agent_py.storage.paths import get_tool_results_dir


PREVIEW_SIZE_BYTES = 2_000
DEFAULT_MAX_RESULT_SIZE = 100_000


@dataclass
class PersistedToolResult:
    filepath: Path
    original_size: int
    is_json: bool
    preview: str
    has_more: bool


@dataclass
class PersistError:
    error: str


def is_tool_result_content_empty(content) -> bool:
    """對應 TS isToolResultContentEmpty。"""
    if not content:
        return True
    if isinstance(content, str):
        return content.strip() == ""
    # list of blocks
    if not isinstance(content, list) or not content:
        return True
    return all(
        b.get("type") == "text" and not b.get("text", "").strip()
        for b in content
    )


def has_image_block(content) -> bool:
    if not isinstance(content, list):
        return False
    return any(b.get("type") == "image" for b in content)


def generate_preview(content_str: str, size: int = PREVIEW_SIZE_BYTES) -> tuple[str, bool]:
    if len(content_str) <= size:
        return content_str, False
    return content_str[:size], True


def build_large_tool_result_message(result: PersistedToolResult) -> str:
    """對應 TS buildLargeToolResultMessage。"""
    msg = "<persisted-output>\n"
    msg += f"Output too large ({result.original_size:,} bytes). "
    msg += f"Full output saved to: {result.filepath}\n\n"
    msg += f"Preview (first {PREVIEW_SIZE_BYTES:,} bytes):\n"
    msg += result.preview
    msg += "\n...\n" if result.has_more else "\n"
    msg += "</persisted-output>"
    return msg


async def persist_tool_result(
    content,
    tool_use_id: str,
    session_id: UUID,
) -> PersistedToolResult | PersistError:
    """寫工具結果到 tool-results/<id>.{json|txt}。

    對應 TS persistToolResult(toolResultStorage.ts:137)。
    用 'wx' flag 避免重複寫(microcompact replay 不會覆寫)。
    """
    is_json = isinstance(content, list)
    if is_json:
        # 含非文字 block 不能 persist
        if any(b.get("type") != "text" for b in content):
            return PersistError(error="Cannot persist non-text content")

    content_str = (
        json.dumps(content, ensure_ascii=False, indent=2) if is_json
        else str(content)
    )

    ext = "json" if is_json else "txt"
    filepath = get_tool_results_dir(session_id) / f"{tool_use_id}.{ext}"

    try:
        # 'x' = exclusive create,已存在則 EEXIST 例外(對應 TS 'wx')
        with open(filepath, "x", encoding="utf-8") as f:
            f.write(content_str)
    except FileExistsError:
        pass  # 已存在,fall through

    preview, has_more = generate_preview(content_str)
    return PersistedToolResult(
        filepath=filepath,
        original_size=len(content_str),
        is_json=is_json,
        preview=preview,
        has_more=has_more,
    )


async def maybe_persist_large_tool_result(
    tool_result_block: dict,
    tool_name: str,
    session_id: UUID,
    threshold: int | None = None,
) -> dict:
    """對應 TS maybePersistLargeToolResult。

    返回原 block(若不需 persist)或 content 替換為 preview 訊息的新 block。
    """
    content = tool_result_block.get("content")

    # 空結果替換(inc-4586 workaround)
    if is_tool_result_content_empty(content):
        return {
            **tool_result_block,
            "content": f"({tool_name} completed with no output)",
        }

    if not content:
        return tool_result_block

    # 圖片不持久化
    if has_image_block(content):
        return tool_result_block

    size = sum(len(b.get("text", "")) for b in content) if isinstance(content, list) else len(str(content))
    if size <= (threshold or DEFAULT_MAX_RESULT_SIZE):
        return tool_result_block

    result = await persist_tool_result(
        content, tool_result_block["tool_use_id"], session_id
    )
    if isinstance(result, PersistError):
        return tool_result_block

    return {
        **tool_result_block,
        "content": build_large_tool_result_message(result),
    }
```

### 5.3 `storage/replacement_state.py`(第 3 層,最複雜)

```python
"""ContentReplacementState — 第 3 層聚合預算 + 三類分流。

對應 TS utils/toolResultStorage.ts:enforceToolResultBudget。

核心 invariant:
  - mustReapply:已替換,套快取(byte-identical,zero I/O)
  - frozen:已送過全內容,**永不變動**(prompt cache 穩定)
  - fresh:本輪新進來,可決策

決策不可逆:fresh → 決定不替換 → frozen(永遠不變)
              fresh → 決定替換   → mustReapply(永遠套同樣 preview)
"""
from __future__ import annotations

from dataclasses import dataclass, field


MAX_TOOL_RESULTS_PER_MESSAGE_CHARS = 200_000


@dataclass
class ToolResultCandidate:
    tool_use_id: str
    size: int
    content: object  # 原始 content


@dataclass
class ContentReplacementState:
    """對應 TS createContentReplacementState 回傳的物件。"""
    seen_ids: set[str] = field(default_factory=set)
    """已決策過的 tool_use_id(凍結後不再變動)。"""

    replacements: dict[str, str] = field(default_factory=dict)
    """已替換的 ID → preview 訊息。"""

    def is_frozen(self, tool_use_id: str) -> bool:
        return tool_use_id in self.seen_ids and tool_use_id not in self.replacements

    def is_must_reapply(self, tool_use_id: str) -> bool:
        return tool_use_id in self.replacements


@dataclass
class Partition:
    must_reapply: list[ToolResultCandidate]
    frozen: list[ToolResultCandidate]
    fresh: list[ToolResultCandidate]


def partition_by_prior_decision(
    candidates: list[ToolResultCandidate],
    state: ContentReplacementState,
) -> Partition:
    """三類分流。對應 TS partitionByPriorDecision。"""
    must_reapply, frozen, fresh = [], [], []
    for c in candidates:
        if state.is_must_reapply(c.tool_use_id):
            must_reapply.append(c)
        elif c.tool_use_id in state.seen_ids:
            frozen.append(c)
        else:
            fresh.append(c)
    return Partition(must_reapply, frozen, fresh)


def select_fresh_to_replace(
    eligible: list[ToolResultCandidate],
    frozen_size: int,
    limit: int,
) -> list[ToolResultCandidate]:
    """從 fresh 中挑最大幾個直到回到預算下。

    對應 TS selectFreshToReplace。
    """
    # 按 size 降序排
    sorted_eligible = sorted(eligible, key=lambda c: c.size, reverse=True)
    selected = []
    fresh_remaining = sum(c.size for c in eligible)

    for c in sorted_eligible:
        if frozen_size + fresh_remaining <= limit:
            break
        selected.append(c)
        fresh_remaining -= c.size

    return selected


async def enforce_tool_result_budget(
    messages: list,
    state: ContentReplacementState,
    session_id,
) -> tuple[list, list]:
    """執行第 3 層預算檢查 + 替換。

    對應 TS enforceToolResultBudget。
    返回 (新 messages, 本次新增 replacement records)。
    """
    # 細節省略:掃 messages 找 tool_result block、partition、select、persist、replace
    ...


def reconstruct_content_replacement_state(
    messages: list,
    records: list,  # 從 transcript 讀回的 ContentReplacementRecord[]
) -> ContentReplacementState:
    """Resume 時從 transcript 重建 state。

    對應 TS reconstructContentReplacementState。

    每個 candidate ID:
      - 在 records 有對應 → replacements 設值
      - 在 messages 有但 records 沒 → 加入 seen_ids(視為 frozen)
    """
    state = ContentReplacementState()
    candidate_ids = _collect_candidate_ids(messages)

    for cid in candidate_ids:
        state.seen_ids.add(cid)
    for r in records:
        if r["kind"] == "tool-result" and r["tool_use_id"] in candidate_ids:
            state.replacements[r["tool_use_id"]] = r["replacement"]

    return state


def _collect_candidate_ids(messages: list) -> set[str]:
    ids = set()
    for m in messages:
        if not isinstance(m.get("content"), list):
            continue
        for block in m["content"]:
            if block.get("type") == "tool_result":
                ids.add(block["tool_use_id"])
    return ids
```

### 5.4 `storage/file_history.py`

```python
"""寫檔前快照。對應 TS utils/fileHistory.ts。

設計:不是每次 read 快照,只在 Edit/Write 之前。原檔不存在不快照。
"""
from __future__ import annotations

import shutil
from pathlib import Path
from uuid import UUID, uuid4
from datetime import datetime

from claude_agent_py.storage.paths import get_file_history_dir


async def make_snapshot(file_path: Path, session_id: UUID) -> Path | None:
    """寫前快照。檔案不存在 → 不快照。"""
    if not file_path.exists():
        return None

    snap_id = uuid4()
    snap_path = get_file_history_dir(session_id) / f"{snap_id}.snap"
    shutil.copy2(file_path, snap_path)

    # 寫 metadata(原檔路徑、時間)
    meta_path = snap_path.with_suffix(".meta.json")
    meta_path.write_text(
        f'{{"orig_path": "{file_path}", "ts": "{datetime.now().isoformat()}"}}'
    )

    return snap_path
```

### 5.5 `storage/session.py`

```python
"""Session transcript JSONL writer。對應 TS utils/sessionStorage.ts。"""
from __future__ import annotations

import json
import anyio
from uuid import UUID
from typing import AsyncIterator

from claude_agent_py.storage.paths import get_transcript_path


class SessionStorage:
    def __init__(self, session_id: UUID):
        self.session_id = session_id
        self.path = get_transcript_path(session_id)
        self._lock = anyio.Lock()

    async def record(self, message: dict) -> None:
        """追加一筆 message 到 JSONL。"""
        line = json.dumps(message, ensure_ascii=False) + "\n"
        async with self._lock:
            # anyio file 操作
            async with await anyio.open_file(self.path, "a") as f:
                await f.write(line)

    async def record_replacement(self, record: dict) -> None:
        """寫 ContentReplacementRecord(供 resume 重建)。"""
        # 用同一 transcript 也行;或分別寫到 replacements.jsonl
        await self.record({"kind": "replacement_record", **record})

    async def load(self) -> AsyncIterator[dict]:
        """讀回所有 messages。"""
        async with await anyio.open_file(self.path, "r") as f:
            async for line in f:
                if line.strip():
                    yield json.loads(line)
```

### 5.6 `storage/resume.py`

```python
"""Resume 機制。對應 TS commands/resume/。"""
from __future__ import annotations

from uuid import UUID

from claude_agent_py.storage.session import SessionStorage
from claude_agent_py.storage.replacement_state import (
    ContentReplacementState,
    reconstruct_content_replacement_state,
)


async def load_session(session_id: UUID) -> tuple[list, ContentReplacementState]:
    """從 transcript 重建 messages + replacement state。"""
    storage = SessionStorage(session_id)
    messages = []
    records = []
    async for entry in storage.load():
        if entry.get("kind") == "replacement_record":
            records.append(entry)
        else:
            messages.append(entry)

    state = reconstruct_content_replacement_state(messages, records)
    return messages, state
```

## 6. 設計決策與取捨

### 為何不直接用 Postgres?

Phase 2 用本機 fs(JSONL + 持久化檔案),理由:
- 簡單,不依賴 DB 服務
- transcript 是 append-only,JSONL 天生適合
- Phase 7 才需要多 user → 改 Postgres + S3

過早引入 DB 增加複雜度。**Phase 抽象設計時就把介面留好**,Phase 7 只換實作。

### 為何用 'x' flag(exclusive create)?

對應 TS 的 'wx'。原因:同一 `tool_use_id` 內容是 deterministic,microcompact 重播時不該重寫。`'x'` 已存在拋 `FileExistsError`,catch 後 fall through。比 stat-then-write 沒 race。

### 為何 ReplacementState 決策不可逆?

prompt cache 命中要前綴**位元組一致**(見 [docs/09 §5](../09-large-tool-results.md))。已送過全內容若改 preview → cache miss → 後續所有訊息重算 → 浪費 20-50K tokens。

**凍結後永不變**才能保 cache。

### 為何 frozen + must_reapply 分兩個結構?

- `seen_ids` (set):記「曾被決策過」
- `replacements` (dict):記「替換結果」
- 交集 = mustReapply、差集 = frozen

兩個結構**O(1) lookup**,比掃整個列表快。對應 TS 的設計。

### 為何不用 sqlite?

可以,但 JSONL 對 transcript 是天然 fit:
- append-only,並發友善
- 純文字可手動檢視 / grep
- 不需要 schema migration
- python `json` stdlib 即可

sqlite 適合 indexed query(Phase 7 之後可加)。

### Phase 2 故意不做的

| 項目 | 留給哪個 phase |
|---|---|
| 多 session 並行同 user | Phase 7 |
| Postgres / S3 後端 | Phase 7 |
| 跨 user 資料隔離 | Phase 7 |
| ContentReplacement 給 sub-agent fork | Phase 9 worktree+sub-agent |
| Compaction(本身不含 replacement) | Phase 3 |

## 7. 驗收標準

### 自動測試

```bash
pytest tests/storage/ -v
mypy --strict src/claude_agent_py/storage/
```

關鍵測試:

- `test_persist_size_threshold.py`:< 100K 不持久化、> 100K 持久化、空結果替換 marker、image 跳過
- `test_replacement_state.py`:partition 三類正確、frozen 不再變動、mustReapply 套同 preview
- `test_select_fresh_to_replace.py`:挑最少數量、按 size 降序
- `test_resume_round_trip.py`:寫 transcript → load → state byte-identical 重建
- `test_file_history.py`:snapshot 寫對、原檔不存在不快照
- `test_session_concurrent_write.py`:用 hypothesis 並發寫 transcript 不錯亂

### 手動驗證

跑一個會產大結果的對話:

```bash
python -m claude_agent_py
> Bash: ls -laR /usr/include  # 大量輸出
```

預期:
- tool-results/<id>.txt 寫入
- 模型看到 `<persisted-output>` preview
- 對話繼續正常

然後 resume:

```bash
python -m claude_agent_py --resume <session-id>
> 繼續對話
```

預期:
- 載入舊 transcript
- ReplacementState 重建
- 繼續對話 prompt cache 命中(觀察 anthropic SDK 回傳的 cache_read_input_tokens)

### 整合驗證

跑長對話(20+ turn,含多次大結果),session 結束後:

```bash
ls ~/.claude_agent_py/sessions/<session-id>/
# transcript.jsonl
# tool-results/<...>.json (多個)
# file-history/<...>.snap (若有 Edit/Write)
```

resume 該 session,**整段 conversation 應能 byte-for-byte 重現**(prompt cache 全命中)。

## 8. 常見踩雷

### 踩雷 1:JSONL 寫入並發

`async with anyio.open_file(..., "a")` 不保證跨多個 task 的 atomicity。一定要外加 `anyio.Lock`(見 skeleton),否則多個並行 yield 會交錯寫成損壞的 JSONL。

### 踩雷 2:Pydantic 序列化非標準型別

訊息含 datetime / UUID 等非 JSON-native 型別時,直接 `json.dumps` 會 crash。Pydantic v2:

```python
from pydantic import BaseModel
msg.model_dump(mode="json")  # 自動轉 ISO 格式
```

或自訂 `default=str`。

### 踩雷 3:resume 後 ReplacementState 與 messages 不對齊

如果 transcript 寫一半 process 死掉,可能有 message 但對應的 replacement_record 沒寫(或反之)。`reconstruct_content_replacement_state` 要 graceful 處理:

- record 提到的 ID 不在 messages → 跳過
- messages 有但 record 沒提的 → 加 seen_ids(視為 frozen,不主動替換)

### 踩雷 4:大結果寫入失敗

磁碟滿、權限問題等。`persist_tool_result` 要回 `PersistError`,caller 要 fallback(回原 content + 警告)。**不要**讓持久化失敗導致整個 turn 中斷。

### 踩雷 5:ReplacementState 的 thread safety

多 session 有自己的 state(per-session 隔離),所以不用擔心。但**單 session 內**,若 streaming executor 並發處理 tool_result,要在 enforce_tool_result_budget 加 lock。

### 踩雷 6:File history 路徑碰撞

兩個工具同時 Edit 同一檔案 → 兩個 snapshot 都用 uuid4 命名,**不會碰撞**。但要記得 `snap_path.with_suffix(".meta.json")` 跟著 uuid 走。

### 踩雷 7:checkpoint 後 cwd 改變

Resume 時若使用者在不同目錄,`AgentContext.cwd` 改變。要決定:延用舊 cwd 還是新 cwd?Claude Code 是延用 session 開始時的 cwd。Phase 7 sandbox 化後 cwd 是容器內 mount 點,問題消失。

## 9. 參考資料

### docs/01-11

- [docs/09](../09-large-tool-results.md) — 整章必讀(三層持久化詳解)
- [docs/06 模組 7](../06-harness-engineering.md) — State & Checkpointing 設計取捨

### TS 源檔

- `src/utils/toolResultStorage.ts:137-960` — 整個第 2-3 層 + replacement state
- `src/utils/fileHistory.ts` — 寫前快照
- `src/utils/sessionStorage.ts` — JSONL transcript
- `src/commands/resume/resume.tsx` — Resume UI

### 外部資源

- [anyio file IO](https://anyio.readthedocs.io/en/stable/fileio.html)
- [JSONL spec](https://jsonlines.org/)
- [Anthropic prompt caching](https://docs.anthropic.com/en/docs/build-with-claude/prompt-caching) — 理解為何要保 byte-identical

## 完成檢查表

- [ ] 第 2 層持久化(單工具大結果)
- [ ] 第 3 層聚合預算 + 三類分流
- [ ] ReplacementState 決策不可逆
- [ ] File history 寫前快照
- [ ] JSONL transcript 並發安全
- [ ] Resume 重建 state byte-identical
- [ ] coverage > 80%(storage 層尤其重要)
- [ ] 寫 Phase 2 心得

完成後進入 [Phase 3:Memory & Compaction](./03-memory-compaction.md)。

# Phase 13:Resilience(韌性與生產化補強)

## 速覽

- **預計時程**:1-2 週
- **前置 Phase**:Phase 7(production)、Phase 11(input pipeline)
- **本文件目的**:補 Phase 7-12 漏掉的「生產實際撞牆才會遇到」韌性問題
- **主要交付物**:
  - **Settings migrations 框架**(版本遷移,等冪、可回滾)
  - **ConversationRecovery**(corrupt transcript 修復)
  - **Permission persistence**(「Always Allow」學習寫回 settings)
  - **CLAUDE.md 完整 hierarchy**(子目錄繼承、衝突合併、nested attachment)
  - **(輕量)Output styles + Auto-update 通知**

## ⚠️ Web Chat 場景調整

> **TS 原設計**:CLAUDE.md hierarchy(`<cwd>/CLAUDE.md`、`<git_root>/CLAUDE.md`、`~/.claude/CLAUDE.md` 等)— 假設 agent 在某 cwd 跑。
>
> **Web chat 改為**:**沒有 cwd 概念**,改成兩層:
>
> | 層級 | 對應 |
> |---|---|
> | **Per-conversation custom instructions** | 類似 ChatGPT 的「Custom Instructions for this chat」UI |
> | **Per-user 預設 instructions** | 類似 ChatGPT 的「About me / How I want to be helped」 |
>
> 兩層都存 Postgres(per-user / per-conversation row)。Phase 4 的 `get_user_context` 改從 DB 讀,不從 fs 找 CLAUDE.md。
>
> **本 phase 的 `prompt/claudemd.py`(完整 hierarchy 邏輯)整段刪掉**,改下方 § 5.4 的 `prompt/instructions.py`。

## 1. 為何需要本 phase?

Phase 7 跑通 production,但 6 個月後**會遇到**:

```
"使用者升級了模型,settings 沒遷移,某個欄位變成 null 引發崩潰"
   → 需要 settings migrations

"transcript JSONL 寫到一半 process 死,後續 resume 失敗"
   → 需要 ConversationRecovery

"使用者每次都要按 Allow,煩"
   → 需要 permission persistence(Always Allow → 寫進 settings)

"這個 repo 的 CLAUDE.md 很複雜,nested 子目錄 / 衝突 / 大檔"
   → 需要完整 hierarchy 邏輯
```

**對應 TS 源碼**:
- `src/migrations/`(11 個遷移腳本)
- `src/utils/conversationRecovery.ts`(597 行)
- `src/services/policyLimits/` 的 rule 加入機制
- `src/utils/claudemd.ts`(完整 hierarchy)
- `src/outputStyles/`(輕量)

## 2. TS 源檔映射

| Python 模組 | 對應 TS 源檔 | 行數 | 注意 |
|---|---|---|---|
| `src/migrations/framework.py` | (無對應,新框架) | — | 等冪、版本化、可回滾 |
| `src/migrations/m_*.py` | `src/migrations/migrate*.ts` | 各 | 11 個遷移腳本翻譯 |
| `src/recovery/transcript.py` | `src/utils/conversationRecovery.ts` | 597 | corrupt 修復 |
| `src/permissions/persistence.py` | `src/services/policyLimits/` 加 rule 邏輯 | — | Always Allow 寫回 |
| `src/prompt/claudemd.py` | `src/utils/claudemd.ts` | — | 完整 hierarchy |
| `src/output_styles/loader.py` | `src/outputStyles/loadOutputStylesDir.ts` | — | 自訂 style |

## 3. 任務拆解

### Week 1:Migrations + Recovery

- [ ] 1.1 `migrations/framework.py`:Migration Protocol + Runner
- [ ] 1.2 Migration version 在 settings.json 內紀錄(`_schema_version` 欄位)
- [ ] 1.3 寫 5-6 個範例 migrations(對應 TS 的 11 個重要的)
- [ ] 1.4 啟動時自動跑 migrations
- [ ] 1.5 `recovery/transcript.py`:JSONL parse with skip-bad-lines
- [ ] 1.6 `recover_session`:檢查 tool_use 與 tool_result 對應、補 synthetic
- [ ] 1.7 整合到 Phase 2 resume:第一步先 recover

### Week 2:Permission persist + CLAUDE.md + Output styles

- [ ] 2.1 `permissions/persistence.py`:Always Allow → 加 policy rule
- [ ] 2.2 寫回 user / project / local 哪一層(由 user 選擇)
- [ ] 2.3 `prompt/claudemd.py`:完整 hierarchy(全域 / 專案 / 子目錄繼承)
- [ ] 2.4 衝突合併策略(後者覆蓋前者 / 累加)
- [ ] 2.5 大檔截斷 + 警告
- [ ] 2.6 `output_styles/loader.py`:從 `~/.claude/output-styles/` 載入
- [ ] 2.7 `commands/builtin/output.py`:`/output-style <name>` 切換
- [ ] 2.8 `utils/git/` + `utils/github/` helpers — 對應 TS `utils/git/`、`utils/github/`
   - `utils/git/operations.py`:git status / diff / log / commit / push wrapper(用 GitPython 或 subprocess)
   - `utils/github/auth.py`:gh CLI auth 狀態(對應 `utils/github/ghAuthStatus.ts`)
   - `commands/builtin/commit.py`:`/commit` 命令(包 git commit + 對話內生成 commit message)
   - `commands/builtin/pr.py`:`/pr` 命令(用 gh CLI 開 PR)
   - `commands/builtin/review.py`:`/review` 命令(spawn coordinator 跑 multi-angle review,對應 Phase 15)
- [ ] 2.9 寫 Phase 13 心得

## 4. 模組架構

```
src/claude_agent_py/
├── migrations/
│   ├── __init__.py
│   ├── framework.py                    # ◀ Protocol + Runner
│   └── m_*.py                          # ◀ 各遷移腳本
│
├── recovery/
│   ├── __init__.py
│   └── transcript.py                   # ◀ corrupt 修復
│
├── permissions/
│   └── persistence.py                  # ◀ Always Allow 寫回
│
├── prompt/
│   └── claudemd.py                     # ◀ 完整 hierarchy
│
└── output_styles/
    ├── __init__.py
    └── loader.py                       # ◀ 自訂 style 載入
```

## 5. Python Skeleton

### 5.1 `migrations/framework.py`

```python
"""Settings migrations 框架。對應 TS migrations/。

設計原則:
  - 等冪:同 version 跑多次不變
  - 版本化:settings.json 含 _schema_version 欄位
  - 可回滾:每個 migration 提供 down 函式(可選)
  - 啟動時自動跑
"""
from __future__ import annotations
from dataclasses import dataclass
from typing import Callable, Awaitable
import structlog


log = structlog.get_logger()

CURRENT_SCHEMA_VERSION = "13"


@dataclass
class Migration:
    version: str
    """遷移到此 version。e.g. "08"。"""

    description: str

    up: Callable[[dict], dict]
    """forward migration:接舊 settings,返回新 settings。"""

    down: Callable[[dict], dict] | None = None
    """rollback(可選)。"""


class MigrationRunner:
    def __init__(self, migrations: list[Migration]):
        # 按 version 字串排序(假設用 "01" "02" ... "13" 格式)
        self.migrations = sorted(migrations, key=lambda m: m.version)

    def get_current_version(self, settings: dict) -> str:
        return settings.get("_schema_version", "00")

    def get_pending(self, settings: dict) -> list[Migration]:
        current = self.get_current_version(settings)
        return [m for m in self.migrations if m.version > current]

    def migrate(self, settings: dict) -> dict:
        """跑所有 pending migrations。"""
        pending = self.get_pending(settings)
        if not pending:
            return settings

        log.info(f"running {len(pending)} migrations",
                 from_version=self.get_current_version(settings),
                 to_version=pending[-1].version)

        for m in pending:
            try:
                settings = m.up(settings)
                settings["_schema_version"] = m.version
                log.info(f"migration applied", version=m.version, desc=m.description)
            except Exception as e:
                log.error(f"migration failed", version=m.version, error=str(e))
                raise

        return settings


# 範例 migrations
def m_01_add_default_model(settings: dict) -> dict:
    """v01:加 default model 欄位。"""
    if "model" not in settings:
        settings["model"] = "claude-sonnet-4-6"
    return settings


def m_02_rename_legacy_field(settings: dict) -> dict:
    """v02:repl_bridge_enabled → remote_control_at_startup。"""
    if "repl_bridge_enabled" in settings:
        settings["remote_control_at_startup"] = settings.pop("repl_bridge_enabled")
    return settings


def m_03_normalize_mcp_config(settings: dict) -> dict:
    """v03:mcpServers 結構標準化。"""
    servers = settings.get("mcpServers", {})
    for name, conf in servers.items():
        if isinstance(conf, str):
            # 舊格式直接是命令字串 → 包成 dict
            servers[name] = {"command": conf, "type": "stdio"}
    return settings


# 列出所有 migrations
ALL_MIGRATIONS = [
    Migration(version="01", description="Add default model field", up=m_01_add_default_model),
    Migration(version="02", description="Rename repl_bridge", up=m_02_rename_legacy_field),
    Migration(version="03", description="Normalize MCP config", up=m_03_normalize_mcp_config),
    # ... 補完到 13
]


def get_runner() -> MigrationRunner:
    return MigrationRunner(ALL_MIGRATIONS)
```

整合到啟動:

```python
# api/app.py 啟動 hook
@asynccontextmanager
async def lifespan(app: FastAPI):
    # Phase 13:跑 migrations
    from claude_agent_py.migrations.framework import get_runner
    from claude_agent_py.utils.settings import load_settings, save_settings

    settings = load_settings()
    runner = get_runner()
    new_settings = runner.migrate(settings)
    if new_settings is not settings:
        save_settings(new_settings)

    # ...其他啟動 logic
    yield
```

### 5.2 `recovery/transcript.py`

```python
"""Conversation recovery — 從 corrupt transcript 修復。

對應 TS utils/conversationRecovery.ts。

常見 corrupt 情境:
  1. JSONL 中間有寫到一半的行(process 死)
  2. tool_use 寫了但對應的 tool_result 沒寫
  3. compact_boundary 標記但 preservedSegment 缺
"""
from __future__ import annotations
from dataclasses import dataclass
from pathlib import Path
import json
import structlog


log = structlog.get_logger()


@dataclass
class RecoveryReport:
    total_lines: int
    valid_messages: int
    skipped_corrupt_lines: int
    orphan_tool_uses: list[str]  # 沒有對應 result 的 tool_use_id
    fix_actions: list[str]


def load_transcript_safe(path: Path) -> tuple[list[dict], RecoveryReport]:
    """安全載入 JSONL,跳過 corrupt 行。"""
    messages = []
    report = RecoveryReport(
        total_lines=0,
        valid_messages=0,
        skipped_corrupt_lines=0,
        orphan_tool_uses=[],
        fix_actions=[],
    )

    if not path.exists():
        return messages, report

    with open(path, "r", encoding="utf-8") as f:
        for line_no, line in enumerate(f, 1):
            report.total_lines += 1
            line = line.strip()
            if not line:
                continue
            try:
                msg = json.loads(line)
                messages.append(msg)
                report.valid_messages += 1
            except json.JSONDecodeError as e:
                log.warning(f"skipping corrupt line",
                            line_no=line_no, error=str(e))
                report.skipped_corrupt_lines += 1
                report.fix_actions.append(f"skipped line {line_no}: corrupt JSON")

    return messages, report


def detect_orphan_tool_uses(messages: list[dict]) -> list[str]:
    """找有 tool_use 但沒對應 tool_result 的 ID。"""
    tool_use_ids = set()
    tool_result_ids = set()

    for m in messages:
        content = m.get("content")
        if not isinstance(content, list):
            continue
        for block in content:
            if block.get("type") == "tool_use":
                tool_use_ids.add(block["id"])
            elif block.get("type") == "tool_result":
                tool_result_ids.add(block.get("tool_use_id"))

    return list(tool_use_ids - tool_result_ids)


def fix_orphan_tool_uses(
    messages: list[dict],
    orphan_ids: list[str],
) -> list[dict]:
    """為 orphan tool_use 注入 synthetic tool_result(error)。"""
    if not orphan_ids:
        return messages

    # 在最後一個 assistant message 後加一個 user message 含所有 orphan results
    synthetic_results = [
        {
            "type": "tool_result",
            "tool_use_id": tid,
            "content": "<tool_use_error>Tool execution interrupted (recovered from corrupt transcript)</tool_use_error>",
            "is_error": True,
        }
        for tid in orphan_ids
    ]

    messages.append({
        "role": "user",
        "content": synthetic_results,
        "_synthetic": True,
    })
    return messages


def recover_session(transcript_path: Path) -> tuple[list[dict], RecoveryReport]:
    """完整 recovery flow。"""
    messages, report = load_transcript_safe(transcript_path)

    # 偵測 + 修補 orphan
    orphan_ids = detect_orphan_tool_uses(messages)
    report.orphan_tool_uses = orphan_ids

    if orphan_ids:
        messages = fix_orphan_tool_uses(messages, orphan_ids)
        report.fix_actions.append(f"injected {len(orphan_ids)} synthetic tool_results")

    # TODO: 偵測 + 修補 compact_boundary 缺 preservedSegment 的情況
    # TODO: 偵測 + 修補 ContentReplacement record 不一致

    log.info(f"recovery complete",
             total=report.total_lines,
             valid=report.valid_messages,
             skipped=report.skipped_corrupt_lines,
             orphans=len(orphan_ids))

    return messages, report
```

整合到 Phase 2 resume:

```python
# storage/resume.py 改造

async def load_session(session_id: UUID) -> tuple[list, ContentReplacementState, RecoveryReport]:
    transcript_path = get_transcript_path(session_id)
    messages, report = recover_session(transcript_path)
    state = reconstruct_content_replacement_state(messages, ...)
    return messages, state, report
```

### 5.3 `permissions/persistence.py`

```python
"""Always Allow 寫回 settings。對應 TS policyLimits 加 rule。"""
from __future__ import annotations
from dataclasses import dataclass
from typing import Literal
from pathlib import Path

from claude_agent_py.utils.settings import (
    load_settings_layer, save_settings_layer,
)


@dataclass
class PermissionRule:
    tool_name: str
    decision: Literal["allow", "deny"]
    matcher: dict | None = None
    """進階:input 條件匹配,e.g. {command: "ls *"}"""


def add_permission_rule(
    rule: PermissionRule,
    *,
    scope: Literal["user", "project", "local"] = "user",
) -> None:
    """寫回 settings.json 對應層。

    scope:
      - "user" → ~/.claude/settings.json(全域永久)
      - "project" → <project>/.claude/settings.json(commit 進 repo)
      - "local" → <project>/.claude/settings.local.json(gitignored)
    """
    settings = load_settings_layer(scope)

    permissions = settings.setdefault("permissions", {})
    rules = permissions.setdefault("rules", [])

    # 避免重複
    rule_dict = {
        "tool_name": rule.tool_name,
        "decision": rule.decision,
        "matcher": rule.matcher,
    }
    if rule_dict not in rules:
        rules.append(rule_dict)
        save_settings_layer(scope, settings)


# Phase 6 的 ws permission ask 整合:
async def make_can_use_tool_with_persist(
    ws,
    pending: dict,
    pending_persist: dict,
):
    """擴充 Phase 6 的 ws permission ask:
    回傳值除了 allow/deny 外,還可能是 'always_allow' 'always_deny'
    → 自動 add_permission_rule。
    """
    async def can_use(tool, input, ctx, tool_use_id):
        # 先 check 已存在 rule(從 settings 讀)
        existing = check_existing_rules(tool.name, input.model_dump())
        if existing:
            return existing  # "allow" / "deny"

        # 沒 rule → ws round-trip 問 user
        decision = await ask_via_ws(ws, pending, tool, input, tool_use_id)

        if decision == "always_allow":
            add_permission_rule(
                PermissionRule(
                    tool_name=tool.name,
                    decision="allow",
                    matcher=_extract_matcher(input),
                ),
                scope="user",
            )
            return "allow"
        elif decision == "always_deny":
            add_permission_rule(
                PermissionRule(
                    tool_name=tool.name,
                    decision="deny",
                    matcher=_extract_matcher(input),
                ),
                scope="user",
            )
            return "deny"

        return decision  # "allow" / "deny"(這次 only)

    return can_use


def _extract_matcher(input) -> dict:
    """從 input 抽 matcher 條件(避免太精準導致下次不 match)。

    例:Bash command 'ls -la /tmp' → matcher: {command_starts_with: 'ls'}
    """
    # 簡化版:不抽 matcher(全 tool_name match)
    return None
```

### 5.4 `prompt/instructions.py`(Web Chat 版,**取代** CLAUDE.md hierarchy)

```python
"""Per-user / per-conversation custom instructions。

取代 TS `utils/claudemd.ts`(CLAUDE.md hierarchy)。
Web chat 沒 cwd 概念,改用 ChatGPT 風格的「Custom Instructions」。

兩層 instructions:
  - User-level:user 在 settings 設定的「About me / How I want help」
  - Conversation-level:每 conversation 開頭可設「This conversation context」
"""
from __future__ import annotations
from dataclasses import dataclass
from sqlalchemy import select

from claude_agent_py.storage.postgres import (
    UserPreference, ConversationMetadata,
)


CONVERSATION_INSTRUCTION_LIMIT_CHARS = 5000
USER_INSTRUCTION_LIMIT_CHARS = 5000


@dataclass
class CustomInstructions:
    user_level: str | None
    conversation_level: str | None


async def get_custom_instructions(
    user_id: str,
    session_id: str,
    db,
) -> CustomInstructions:
    """從 DB 讀兩層 instructions。"""
    user_pref = (await db.execute(
        select(UserPreference).where(UserPreference.user_id == user_id)
    )).scalar_one_or_none()

    conv_meta = (await db.execute(
        select(ConversationMetadata).where(
            ConversationMetadata.session_id == session_id
        )
    )).scalar_one_or_none()

    user_inst = (user_pref.custom_instructions if user_pref else None) or None
    conv_inst = (conv_meta.custom_instructions if conv_meta else None) or None

    # 截斷
    if user_inst and len(user_inst) > USER_INSTRUCTION_LIMIT_CHARS:
        user_inst = user_inst[:USER_INSTRUCTION_LIMIT_CHARS] + "...[truncated]"
    if conv_inst and len(conv_inst) > CONVERSATION_INSTRUCTION_LIMIT_CHARS:
        conv_inst = conv_inst[:CONVERSATION_INSTRUCTION_LIMIT_CHARS] + "...[truncated]"

    return CustomInstructions(
        user_level=user_inst,
        conversation_level=conv_inst,
    )


def assemble_instructions_section(inst: CustomInstructions) -> str:
    """組成 user message 前綴(類似 Phase 4 的 userContext)。"""
    parts = []
    if inst.user_level:
        parts.append(f"## About this user\n\n{inst.user_level}")
    if inst.conversation_level:
        parts.append(f"## Context for this conversation\n\n{inst.conversation_level}")
    return "\n\n".join(parts)


# 整合到 Phase 4 的 get_user_context
async def get_user_context_for_web_chat(
    user_id: str,
    session_id: str,
    db,
) -> dict[str, str]:
    """Web chat 的 user context。對應 Phase 4 的 get_user_context。"""
    inst = await get_custom_instructions(user_id, session_id, db)
    return {
        "current_date": datetime.now().date().isoformat(),
        "custom_instructions": assemble_instructions_section(inst) if (
            inst.user_level or inst.conversation_level
        ) else "",
    }
```

#### Postgres 表新增

```python
# storage/postgres.py 補

class UserPreference(Base):
    __tablename__ = "user_preferences"
    user_id: Mapped[str] = mapped_column(primary_key=True, ForeignKey="users.id")
    custom_instructions: Mapped[str | None] = mapped_column(Text)
    timezone: Mapped[str | None] = mapped_column(String(64))
    # ...其他偏好


class ConversationMetadata(Base):
    __tablename__ = "conversation_metadata"
    session_id: Mapped[UUID] = mapped_column(primary_key=True, ForeignKey="sessions.id")
    title: Mapped[str | None] = mapped_column(String(255))
    custom_instructions: Mapped[str | None] = mapped_column(Text)
```

#### REST endpoints

```python
# api/routes/preferences.py

@router.put("/me/custom-instructions")
async def update_user_instructions(
    instructions: str,
    user=Depends(current_user),
    db=Depends(get_db),
):
    # upsert UserPreference
    ...


@router.put("/sessions/{sid}/custom-instructions")
async def update_conv_instructions(
    sid: UUID,
    instructions: str,
    user=Depends(current_user),
    db=Depends(get_db),
):
    # upsert ConversationMetadata
    ...
```

### 5.4b ~~原 CLAUDE.md hierarchy 程式碼(CLI / 本機 dev only)~~

```python
"""⚠️ 本段保留作為 CLI 模式 reference。Web chat 用 5.4 的 instructions.py。

CLAUDE.md 完整 hierarchy 邏輯。對應 TS utils/claudemd.ts。

完整流程:
  1. 從 cwd 開始,上溯到根目錄,每層找 CLAUDE.md
  2. 加全域 ~/.claude/CLAUDE.md
  3. 大檔截斷(類似 MEMORY.md 200 行 / 25 KB)
  4. nested 子目錄的 CLAUDE.md 不主動載,但工具 trigger 時動態載
"""
from __future__ import annotations
from dataclasses import dataclass
from pathlib import Path


CLAUDE_MD_LINE_LIMIT = 200
CLAUDE_MD_BYTE_LIMIT = 25_000


@dataclass
class ClaudeMdEntry:
    path: Path
    content: str
    truncated: bool
    scope: str  # "global" / "project" / "child" / "ancestor"


def find_claude_mds(start: Path) -> list[ClaudeMdEntry]:
    """完整搜尋 CLAUDE.md。

    搜尋順序:
      1. ~/.claude/CLAUDE.md(全域)
      2. <project_root>/CLAUDE.md(專案根)
      3. <project_root>/.claude/CLAUDE.md(專案隱藏)
      4. <ancestor>/CLAUDE.md(從 cwd 上溯到 project_root)
    """
    found = []
    seen_paths = set()

    # 1. 全域
    home_claude = Path("~/.claude/CLAUDE.md").expanduser()
    if home_claude.exists() and home_claude not in seen_paths:
        found.append(_load_with_truncation(home_claude, "global"))
        seen_paths.add(home_claude)

    # 2-4. 專案 + 上溯
    current = start.resolve()
    while current != current.parent:
        for cand in [current / "CLAUDE.md", current / ".claude/CLAUDE.md"]:
            if cand.exists() and cand not in seen_paths:
                scope = "project" if current == _find_project_root(start) else "ancestor"
                found.append(_load_with_truncation(cand, scope))
                seen_paths.add(cand)

        # 到 git root 或 home 就停
        if (current / ".git").exists() or current == Path.home():
            break
        current = current.parent

    return found


def _find_project_root(start: Path) -> Path:
    """找 git root 或 cwd。"""
    current = start.resolve()
    while current != current.parent:
        if (current / ".git").exists():
            return current
        current = current.parent
    return start


def _load_with_truncation(path: Path, scope: str) -> ClaudeMdEntry:
    try:
        content = path.read_text(encoding="utf-8")
    except Exception:
        return ClaudeMdEntry(path=path, content="", truncated=False, scope=scope)

    lines = content.split("\n")
    truncated = False

    if len(lines) > CLAUDE_MD_LINE_LIMIT:
        content = "\n".join(lines[:CLAUDE_MD_LINE_LIMIT])
        truncated = True

    if len(content.encode("utf-8")) > CLAUDE_MD_BYTE_LIMIT:
        content_bytes = content.encode("utf-8")[:CLAUDE_MD_BYTE_LIMIT]
        content = content_bytes.decode("utf-8", errors="ignore")
        truncated = True

    if truncated:
        content += f"\n\n> WARNING: {path.name} truncated (limit: {CLAUDE_MD_LINE_LIMIT} lines / {CLAUDE_MD_BYTE_LIMIT} bytes)"

    return ClaudeMdEntry(path=path, content=content, truncated=truncated, scope=scope)


def assemble_claude_md_section(entries: list[ClaudeMdEntry]) -> str:
    """組合多個 CLAUDE.md 為 prompt section。"""
    if not entries:
        return ""

    sections = []
    for entry in entries:
        sections.append(f"## Contents of {entry.path}\n\n{entry.content}")

    return "\n\n".join(sections)


# 整合到 Phase 4 的 get_user_context
def get_user_context_with_claude_mds(start: Path) -> dict[str, str]:
    entries = find_claude_mds(start)
    return {
        "claude_md": assemble_claude_md_section(entries),
        "current_date": datetime.now().date().isoformat(),
    }
```

### 5.5 `output_styles/loader.py`(輕量)

```python
"""Output styles。對應 TS outputStyles/loadOutputStylesDir.ts。

讓 user 自訂 agent 回應風格(simple / verbose / formal / casual / 等)。
"""
from __future__ import annotations
from dataclasses import dataclass
from pathlib import Path
import frontmatter


@dataclass
class OutputStyle:
    name: str
    description: str
    prompt: str
    keep_coding_instructions: bool = True


def load_output_styles_dir(directory: Path) -> list[OutputStyle]:
    """從目錄載入所有 .md output style。"""
    if not directory.exists():
        return []

    result = []
    for md_path in directory.glob("*.md"):
        try:
            post = frontmatter.load(md_path)
            result.append(OutputStyle(
                name=post.metadata.get("name", md_path.stem),
                description=post.metadata.get("description", ""),
                prompt=post.content,
                keep_coding_instructions=post.metadata.get("keep_coding_instructions", True),
            ))
        except Exception:
            continue

    return result


def load_all_output_styles() -> list[OutputStyle]:
    sources = [
        Path("~/.claude/output-styles").expanduser(),
        Path(".claude/output-styles"),
    ]
    all_styles = []
    for src in sources:
        all_styles.extend(load_output_styles_dir(src))
    return all_styles


# /output-style 命令(Phase 11 commands/builtin/ 補充)
class OutputStyleCommand:
    name = "output-style"
    description = "Switch output style (simple / verbose / custom)."

    async def execute(self, args, ctx, conversation):
        from claude_agent_py.commands.types import CommandResult

        if not args:
            # 列當前可用 styles
            styles = load_all_output_styles()
            text = "\n".join(f"- {s.name}: {s.description}" for s in styles)
            return CommandResult(text=f"Available styles:\n{text}")

        styles = load_all_output_styles()
        target = next((s for s in styles if s.name == args.strip()), None)
        if target is None:
            return CommandResult(text=f"Style '{args}' not found")

        ctx.feature_flags["active_output_style"] = target.name
        # Phase 4 的 get_output_style_section 會讀這個 flag
        return CommandResult(text=f"Switched to '{target.name}'")
```

## 6. 設計決策與取捨

### 為何 Migrations 紀錄 version 在 settings 內?

替代方案:外部 file(`~/.claude/.migration_state`)。

優點 settings 內:
- single source of truth
- backup settings 自動含 migration state
- multi-machine 不會撞舊 state

對應 TS 也是這樣。

### 為何 ConversationRecovery 注入 synthetic tool_result 而非刪除 orphan?

刪除 orphan tool_use 會讓 messages 順序錯亂,模型困惑。改成**注入 synthetic error**:
- 順序保留
- 模型看到「上一輪工具失敗」,可以決定下一步
- transcript 完整性可審計

代價:user 看 transcript 會看到「錯誤訊息」,要清楚標 `_synthetic: True`。

### 為何 Permission persist scope 給 user 選?

**不同 rule 該寫不同層**:
- 「永遠 allow `/usr/bin/ls`」→ 寫 user(全域)
- 「永遠 allow 這個 repo 的 build script」→ 寫 project(commit 進 repo,team 共享)
- 「allow 這個 dev branch 才有的 tool」→ 寫 local(gitignored)

UI 上應提示 user 選擇,不要寫死。

### 為何 CLAUDE.md 上溯到 git root 就停?

避免無限上溯到 `/`。git root 是合理邊界(專案不會跨 git repo)。沒 git 的話 cwd 就停。

### 為何 Output styles 是輕量章節?

只是 frontmatter + markdown body 載入,跟 Skill loader 機制相同。不需要獨立 phase,Phase 13 順便寫。

### Phase 13 故意不做的

| 項目 | 理由 |
|---|---|
| Auto-update / version 檢查 | SaaS 環境不需要 |
| 完整 14-day 保留 transcript GC | Phase 7 的 quota 已涵蓋 |
| Multi-language CLAUDE.md(中英日)| 一套就夠,需要時自己改 |

## 7. 驗收標準

```bash
pytest tests/migrations/ tests/recovery/ tests/permissions/ tests/prompt/test_claudemd.py -v
```

關鍵測試:

- `test_migration_idempotent.py`:同 migration 跑兩次結果一樣
- `test_migration_skip_already_applied.py`:已套用的不重跑
- `test_recovery_corrupt_jsonl.py`:跳過爛行 + log
- `test_recovery_orphan_tool_use.py`:注入 synthetic
- `test_permission_persist_user.py`:寫到 ~/.claude/settings.json
- `test_permission_persist_project.py`:寫到 <project>/.claude/settings.json
- `test_claudemd_hierarchy.py`:全域 + 專案 + 子目錄繼承
- `test_claudemd_truncation.py`:超過 200 行 / 25 KB 截斷

### 手動驗證

#### Migration

```bash
# 模擬舊 settings
cat > ~/.claude/settings.json <<EOF
{
  "repl_bridge_enabled": true
}
EOF

# 啟動 server
uvicorn claude_agent_py.api.app:app

# check settings 自動 migrate
cat ~/.claude/settings.json
# 應該看到:
# {
#   "_schema_version": "13",
#   "remote_control_at_startup": true,
#   ...
# }
```

#### Recovery

```bash
# 故意把 transcript 寫壞
echo 'invalid json line' >> ~/.claude_agent_py/sessions/<uuid>/transcript.jsonl

# resume 該 session
curl ...

# log 應該看到 "skipping corrupt line"
# 對話正常恢復
```

#### Permission persist

對話中觸發某工具,選 "Always Allow"。check settings:

```bash
cat ~/.claude/settings.json
# permissions.rules 含 {"tool_name": "...", "decision": "allow"}
```

新 session 該工具直接 allow 不再問。

#### CLAUDE.md hierarchy

```bash
mkdir -p /tmp/test-proj/sub/dir
echo "# Project root context" > /tmp/test-proj/CLAUDE.md
echo "# Sub dir context" > /tmp/test-proj/sub/CLAUDE.md

cd /tmp/test-proj/sub/dir
python -m claude_agent_py "hi"

# system prompt 應該含兩個 CLAUDE.md(專案根 + sub 上溯)
```

## 8. 常見踩雷

### 踩雷 1:Migration 改動破壞 schema

寫 migration 時要小心:
- 不要刪欄位(可能有別處依賴),先 deprecate 再刪
- rename 用「先複製,警告 N 版後刪舊」

production migration 一旦跑下去無法回頭(除非有 down)。要先在 staging 驗。

### 踩雷 2:Recovery 太寬容

完全 skip 爛行可能漏掉「真正該炸」的情況(例如整個 transcript 都壞,但 recovery 默默回空)。要設閾值:

```python
if report.skipped_corrupt_lines > report.valid_messages * 0.1:
    raise SeverelyCorruptedError("transcript over 10% corrupt")
```

### 踩雷 3:Permission rule 過度匹配

寫了 `{tool_name: "Bash"}` 沒 matcher → **所有 Bash 命令永遠 allow**。極危險。

UI 上要強制 user 選 matcher 範圍(per-command / per-pattern / global),不能讓 global 太容易勾選。

### 踩雷 4:CLAUDE.md 大檔影響 cache

每加一個 CLAUDE.md 就讓 system prompt 不一樣 → cache 命中變難。Phase 4 的 `userContext` 包成 user message 前綴(不是 system prompt)就是為了這個。**Phase 13 做 hierarchy 仍要走 user message,不要塞 system**。

### 踩雷 5:Migration 跑時 settings 損壞

migration 跑到一半 process 死 → settings 寫到一半 corrupted。要:
- atomic write(寫 tmp file 再 rename)
- 跑前 backup `settings.json.bak.<ts>`

### 踩雷 6:Output style 與 customSystemPrompt 衝突

若 user 同時設了:
- `outputStyle: simple-style`
- `customSystemPrompt: "你是專業客服"`

兩者不該共存(custom 已替換預設,outputStyle 屬於預設的一部分)。要明確優先序 + 警告。

### 踩雷 7:Permission rule 跨機器同步

寫到 `~/.claude/settings.json` 後跨機器不會自動同步。Production SaaS 環境要把 user-level settings 存 DB(Postgres),不是 fs。Phase 7 的 settings 模型要擴充。

## 9. 參考資料

### docs/01-11

- [docs/05](../05-settings-memory-context.md) — settings 多層 / migrations 概念
- [docs/06 模組 7](../06-harness-engineering.md) — State & Checkpointing(recovery)

### TS 源檔

- `src/migrations/migrate*.ts` — 11 個遷移腳本
- `src/utils/conversationRecovery.ts` — 597 行,完整邏輯
- `src/utils/claudemd.ts` — CLAUDE.md hierarchy
- `src/services/policyLimits/` — rule 加入機制
- `src/outputStyles/loadOutputStylesDir.ts` — 輕量

## 10. 完成清單

- [ ] Migration 框架(framework + 5-6 個範例)
- [ ] 啟動時自動跑 migrations
- [ ] ConversationRecovery(corrupt JSONL + orphan tool_use)
- [ ] Phase 2 resume 整合 recovery
- [ ] Permission persistence(Always Allow → settings)
- [ ] Phase 6 ws permission 整合 always_allow / always_deny 選項
- [ ] CLAUDE.md 完整 hierarchy(全域 + 專案 + 上溯 + 截斷)
- [ ] Phase 4 get_user_context 改用 hierarchy
- [ ] Output styles loader + /output-style 命令
- [ ] 寫 Phase 13 心得

---

## 結語:Phase 11 / 12 / 13 與 Phase 0-10 的關係

Phase 11-13 **不是新功能**,是 **Phase 0-10 散落的細節抽出獨立做**:

```
Phase 1 提到 "BashTool 動態判斷 isReadOnly"
   → Phase 12 的 file_state cache 也是這層級的細節

Phase 3 用 "sideQuery"
   → Phase 12 抽出 side_query 通用機制

Phase 6 的 permission ws round-trip
   → Phase 13 補 "Always Allow 寫回 settings"

Phase 7 的 SaaS 化
   → Phase 13 補 settings migrations(版本演進無痛)
```

完成後,**整個 Python port 從「跑得動」升級為「跑得久、跑得穩、跑得舒服」**。

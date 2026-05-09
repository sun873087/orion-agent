# Phase 4:System Prompt(系統提示組裝)

## 速覽

- **預計時程**:2-3 週
- **前置 Phase**:Phase 3(memory)— `load_memory_prompt` 要塞進 prompt section
- **後續 Phase**:Phase 5(MCP)— mcp_instructions section;Phase 8(hooks)— frontmatter hook 整合
- **主要交付物**:
  - `fetch_system_prompt_parts` 三件套(default + userContext + systemContext)
  - `system_prompt_section` cache 機制
  - `DYNAMIC_BOUNDARY` 切分 + cache scope(global/org/null)
  - `context.py`(Git / CLAUDE.md 自動發現)
  - `customSystemPrompt` / `appendSystemPrompt` SDK 注入點

## 1. 目標與動機

Phase 1-3 的 system prompt 都是硬寫一段字串。Phase 4 把它組成**真正的 7 層分層結構**,並做好 prompt cache 切分:

```
靜態段(可享 'global' cache,跨 org 共享)
   ├─ getSimpleIntroSection
   ├─ getSimpleSystemSection
   ├─ getSimpleDoingTasksSection
   ├─ getActionsSection
   ├─ getUsingYourToolsSection
   ├─ getSimpleToneAndStyleSection
   └─ getOutputEfficiencySection
SYSTEM_PROMPT_DYNAMIC_BOUNDARY 標記
動態段(per-section cache,/clear /compact 清)
   ├─ session_guidance / memory / env_info / language / output_style
   ├─ mcp_instructions(DANGEROUS_uncached)
   ├─ scratchpad / frc / summarize_tool_results / token_budget / brief
+ customSystemPrompt / appendSystemPrompt
```

**對應 docs**:
- [docs/08](../08-system-prompt.md) 整章必讀(完整 7 層結構 + cache scope 詳解)
- [docs/05 §5c](../05-settings-memory-context.md) Context 組合流程

完成本 phase 後,prompt cache 命中率最大化,token 成本壓到最低。

## 2. TS 源檔映射

| Python 模組 | 對應 TS 源檔 | 行數 | 注意事項 |
|---|---|---|---|
| `src/prompt/system_prompt.py` | `src/constants/prompts.ts` | 914 | `getSystemPrompt` 主組裝 |
| `src/prompt/sections.py` | `src/constants/systemPromptSections.ts` | 68 | section cache 機制 |
| `src/prompt/templates/main.md` | `src/constants/prompts.ts` 內各 `getXXXSection` 函式 | — | Python 用 markdown 模板 |
| `src/prompt/context.py` | `src/context.ts` | 6 KB | Git + CLAUDE.md |
| `src/prompt/cache_scope.py` | `src/utils/api.ts:splitSysPromptPrefix` | — | global/org/null 切分 |
| `src/prompt/query_context.py` | `src/utils/queryContext.ts` | 179 | `fetch_system_prompt_parts` 三件套 |
| `src/services/anthropic_client.py`(擴充) | `src/services/api/claude.ts:buildSystemPromptBlocks` | — | 加 cache_control 標記 |

## 3. 任務拆解

### Week 1:Section 機制 + 靜態段

- [ ] 1.1 `prompt/sections.py`:`SystemPromptSection` dataclass、`system_prompt_section` factory、`DANGEROUS_uncached_system_prompt_section` factory
- [ ] 1.2 `resolve_system_prompt_sections`(命中 cache 跳過 compute)
- [ ] 1.3 cache lifecycle:`clear_system_prompt_sections`(`/clear` `/compact` 觸發)
- [ ] 1.4 `prompt/templates/main.md`:Claude Code 主提示模板(intro / system / tasks / actions / tools / tone / efficiency)
- [ ] 1.5 載入靜態段函式

### Week 2:動態段 + Context

- [ ] 2.1 `prompt/context.py`:`get_system_context`(Git 分支 / commits)
- [ ] 2.2 `get_user_context`:CLAUDE.md 自動發現(全域 + 專案 + 子目錄繼承)— **完整 hierarchy(衝突合併、雙重截斷)見 [Phase 13](./13-resilience.md)**
- [ ] 2.3 動態 section:session_guidance / memory(接 Phase 3 load_memory_prompt)/ env_info / language / output_style
- [ ] 2.4 `system_prompt.py`:`get_system_prompt` 主函式(靜態段 + boundary + 動態段)
- [ ] 2.5 早退路徑:`CLAUDE_CODE_SIMPLE` env、Proactive 路徑(可選不做)

### Week 3:Cache scope + 序列化 + SDK 注入點

- [ ] 3.1 `cache_scope.py`:`split_sys_prompt_prefix`(三分支)
- [ ] 3.2 `SystemPromptBlock` dataclass(text + cacheScope)
- [ ] 3.3 整合到 `anthropic_client.py`:`build_system_prompt_blocks` 加 cache_control
- [ ] 3.4 `query_context.py`:`fetch_system_prompt_parts`(Promise.all 三件套)
- [ ] 3.5 `customSystemPrompt` / `appendSystemPrompt` 注入邏輯
- [ ] 3.6 整合到 `Conversation`:Phase 1 的硬編碼 system prompt 換成 `fetch_system_prompt_parts`
- [ ] 3.7 測試 + 心得

## 4. 模組架構與檔案

```
src/claude_agent_py/
├── prompt/
│   ├── __init__.py
│   ├── system_prompt.py               # ◀ NEW get_system_prompt 主函式
│   ├── sections.py                    # ◀ NEW section cache 機制
│   ├── context.py                     # ◀ NEW Git + CLAUDE.md
│   ├── cache_scope.py                 # ◀ NEW global/org/null 切分
│   ├── query_context.py               # ◀ NEW fetch_system_prompt_parts
│   └── templates/
│       ├── main.md                    # ◀ NEW Claude Code 主提示
│       ├── tasks.md
│       └── actions.md
│
└── core/
    └── conversation.py                # ◀ 擴充:用 fetch_system_prompt_parts
```

## 5. Python Skeleton

### 5.1 `prompt/sections.py`

```python
"""Section cache 機制。對應 TS constants/systemPromptSections.ts。"""
from __future__ import annotations
from dataclasses import dataclass
from typing import Callable, Awaitable
import asyncio


ComputeFn = Callable[[], Awaitable[str | None]] | Callable[[], str | None]


@dataclass
class SystemPromptSection:
    name: str
    compute: ComputeFn
    cache_break: bool


# Global cache(per-process,可分 session 改 ContextVar)
_section_cache: dict[str, str | None] = {}


def system_prompt_section(name: str, compute: ComputeFn) -> SystemPromptSection:
    """預設工廠。對應 TS systemPromptSection。"""
    return SystemPromptSection(name=name, compute=compute, cache_break=False)


def DANGEROUS_uncached_system_prompt_section(
    name: str,
    compute: ComputeFn,
    reason: str,  # 強制傳,提醒 reviewer
) -> SystemPromptSection:
    """每次重算,會破 cache。對應 TS DANGEROUS_uncachedSystemPromptSection。"""
    return SystemPromptSection(name=name, compute=compute, cache_break=True)


async def resolve_system_prompt_sections(
    sections: list[SystemPromptSection],
) -> list[str | None]:
    """命中 cache 直接返,miss 才計算。對應 TS resolveSystemPromptSections。"""
    async def resolve_one(s: SystemPromptSection) -> str | None:
        if not s.cache_break and s.name in _section_cache:
            return _section_cache[s.name]
        result = s.compute()
        if asyncio.iscoroutine(result):
            result = await result
        _section_cache[s.name] = result
        return result

    return await asyncio.gather(*(resolve_one(s) for s in sections))


def clear_system_prompt_sections() -> None:
    """`/clear` `/compact` 觸發。對應 TS clearSystemPromptSections。"""
    _section_cache.clear()
```

### 5.2 `prompt/system_prompt.py`

```python
"""主 system prompt 組裝。對應 TS constants/prompts.ts:getSystemPrompt。"""
from __future__ import annotations
import os
from pathlib import Path

from claude_agent_py.prompt.sections import (
    SystemPromptSection,
    system_prompt_section,
    DANGEROUS_uncached_system_prompt_section,
    resolve_system_prompt_sections,
)
from claude_agent_py.memory.memdir import load_memory_prompt


SYSTEM_PROMPT_DYNAMIC_BOUNDARY = "__SYSTEM_PROMPT_DYNAMIC_BOUNDARY__"

TEMPLATES_DIR = Path(__file__).parent / "templates"


def _load_template(name: str) -> str:
    return (TEMPLATES_DIR / f"{name}.md").read_text(encoding="utf-8")


def get_simple_intro_section() -> str:
    return _load_template("intro")


def get_simple_system_section() -> str:
    return _load_template("system")


def get_doing_tasks_section() -> str:
    return _load_template("tasks")


def get_actions_section() -> str:
    return _load_template("actions")


def get_using_tools_section(enabled_tools: set[str]) -> str:
    base = _load_template("tools")
    # 可根據 enabled_tools 客製
    return base


def get_tone_style_section() -> str:
    return _load_template("tone")


def get_output_efficiency_section() -> str:
    return _load_template("efficiency")


# --- 動態段 ---

def get_session_guidance_section(enabled_tools: set[str]) -> str | None:
    """session-level 提示。"""
    return None  # 多數情況下沒額外提示


def get_env_info_section() -> str:
    """環境資訊:platform / cwd / model / date。對應 TS computeSimpleEnvInfo。"""
    import platform
    from datetime import date
    return (
        f"# Environment\n"
        f"- Platform: {platform.system()}\n"
        f"- CWD: {os.getcwd()}\n"
        f"- Date: {date.today().isoformat()}"
    )


def get_language_section(language_pref: str | None) -> str | None:
    if not language_pref:
        return None
    return f"# Language\nAlways respond in {language_pref}."


def get_output_style_section(style_config) -> str | None:
    if style_config is None:
        return None
    return f"# Output Style: {style_config.name}\n{style_config.prompt}"


# --- 主組裝函式 ---

async def get_system_prompt(
    *,
    enabled_tools: set[str],
    language_pref: str | None = None,
    output_style_config=None,
) -> list[str]:
    """主組裝。對應 TS getSystemPrompt(prompts.ts:444)。

    返回 string[](不是合併後的單一字串)— 因為要分開標 cache scope。
    """
    # 早退:CLAUDE_CODE_SIMPLE
    if os.environ.get("CLAUDE_CODE_SIMPLE"):
        return [
            f"You are Claude Agent.\nCWD: {os.getcwd()}\n"
            f"Date: {date.today().isoformat()}"
        ]

    # 動態段
    dynamic_sections = [
        system_prompt_section("session_guidance",
            lambda: get_session_guidance_section(enabled_tools)),
        system_prompt_section("memory", load_memory_prompt),
        system_prompt_section("env_info", get_env_info_section),
        system_prompt_section("language",
            lambda: get_language_section(language_pref)),
        system_prompt_section("output_style",
            lambda: get_output_style_section(output_style_config)),
        # mcp_instructions 是 DANGEROUS_uncached(Phase 5 加)
    ]

    resolved_dynamic = await resolve_system_prompt_sections(dynamic_sections)

    return [
        # --- Static(可享 'global' cache)---
        get_simple_intro_section(),
        get_simple_system_section(),
        get_doing_tasks_section(),
        get_actions_section(),
        get_using_tools_section(enabled_tools),
        get_tone_style_section(),
        get_output_efficiency_section(),

        # --- Boundary marker ---
        SYSTEM_PROMPT_DYNAMIC_BOUNDARY,

        # --- Dynamic ---
        *[s for s in resolved_dynamic if s is not None],
    ]
```

### 5.3 `prompt/context.py`

```python
"""Context 組合。對應 TS context.ts。"""
from __future__ import annotations
import subprocess
from pathlib import Path
from datetime import date


def get_system_context() -> dict[str, str]:
    """Git 狀態。對應 TS getSystemContext。"""
    ctx = {}

    try:
        branch = subprocess.check_output(
            ["git", "rev-parse", "--abbrev-ref", "HEAD"],
            stderr=subprocess.DEVNULL,
        ).decode().strip()
        ctx["git_branch"] = branch
    except Exception:
        pass

    try:
        recent_commits = subprocess.check_output(
            ["git", "log", "-5", "--oneline"],
            stderr=subprocess.DEVNULL,
        ).decode().strip()
        ctx["recent_commits"] = recent_commits
    except Exception:
        pass

    return ctx


def find_claude_md_files(start: Path) -> list[Path]:
    """自動發現 CLAUDE.md。對應 TS getUserContext 內邏輯。

    搜尋順序:
      1. ~/.claude/CLAUDE.md(全域)
      2. <project>/CLAUDE.md(專案根)
      3. <project>/.claude/CLAUDE.md(專案隱藏)
      4. <cwd 上溯>/CLAUDE.md(子目錄繼承)
    """
    found = []

    # 全域
    home_claude = Path("~/.claude/CLAUDE.md").expanduser()
    if home_claude.exists():
        found.append(home_claude)

    # 專案 + 上溯
    current = start.resolve()
    while current != current.parent:
        for cand in [current / "CLAUDE.md", current / ".claude/CLAUDE.md"]:
            if cand.exists():
                found.append(cand)
        current = current.parent

    return found


def get_user_context() -> dict[str, str]:
    """User context:CLAUDE.md + currentDate。對應 TS getUserContext。"""
    ctx = {"current_date": date.today().isoformat()}

    claude_mds = find_claude_md_files(Path.cwd())
    if claude_mds:
        sections = []
        for path in claude_mds:
            sections.append(f"## Contents of {path}\n\n{path.read_text()}")
        ctx["claude_md"] = "\n\n".join(sections)

    return ctx
```

### 5.4 `prompt/cache_scope.py`

```python
"""Cache scope 切分。對應 TS utils/api.ts:splitSysPromptPrefix。"""
from __future__ import annotations
from dataclasses import dataclass
from typing import Literal

from claude_agent_py.prompt.system_prompt import SYSTEM_PROMPT_DYNAMIC_BOUNDARY


CacheScope = Literal["global", "org"] | None


@dataclass
class SystemPromptBlock:
    text: str
    cache_scope: CacheScope


def split_sys_prompt_prefix(
    system_prompt: list[str],
    *,
    use_global_cache: bool = True,
) -> list[SystemPromptBlock]:
    """切分 string[] → SystemPromptBlock[],各自帶 cache_scope。

    對應 TS splitSysPromptPrefix。

    主路徑:找到 boundary → static blocks 'global' / dynamic blocks None。
    """
    if not use_global_cache:
        # 全部 'org'(legacy / fallback)
        text = "\n\n".join(s for s in system_prompt if s and s != SYSTEM_PROMPT_DYNAMIC_BOUNDARY)
        return [SystemPromptBlock(text=text, cache_scope="org")] if text else []

    try:
        boundary_idx = system_prompt.index(SYSTEM_PROMPT_DYNAMIC_BOUNDARY)
    except ValueError:
        # 沒找到 boundary,退回全 'org'
        text = "\n\n".join(s for s in system_prompt if s)
        return [SystemPromptBlock(text=text, cache_scope="org")] if text else []

    static_blocks = [s for s in system_prompt[:boundary_idx] if s]
    dynamic_blocks = [s for s in system_prompt[boundary_idx + 1:] if s]

    result = []
    if static_blocks:
        result.append(SystemPromptBlock(
            text="\n\n".join(static_blocks),
            cache_scope="global",
        ))
    if dynamic_blocks:
        result.append(SystemPromptBlock(
            text="\n\n".join(dynamic_blocks),
            cache_scope=None,  # 不 cache
        ))
    return result
```

### 5.5 `prompt/query_context.py`

```python
"""fetch_system_prompt_parts:三件套。對應 TS utils/queryContext.ts。"""
from __future__ import annotations
import asyncio
from dataclasses import dataclass

from claude_agent_py.prompt.system_prompt import get_system_prompt
from claude_agent_py.prompt.context import get_system_context, get_user_context


@dataclass
class SystemPromptParts:
    default_system_prompt: list[str]
    user_context: dict[str, str]
    system_context: dict[str, str]


async def fetch_system_prompt_parts(
    *,
    enabled_tools: set[str],
    custom_system_prompt: str | None = None,
    language_pref: str | None = None,
    output_style_config=None,
) -> SystemPromptParts:
    """三個並行任務。對應 TS fetchSystemPromptParts。

    若 customSystemPrompt 設定 → 跳過 default + systemContext。
    user_context 永遠執行(CLAUDE.md / currentDate 仍要塞)。
    """
    if custom_system_prompt is not None:
        # 只取 user_context
        user_ctx = get_user_context()
        return SystemPromptParts(
            default_system_prompt=[],
            user_context=user_ctx,
            system_context={},
        )

    # 並行三個
    default_prompt, user_ctx, system_ctx = await asyncio.gather(
        get_system_prompt(
            enabled_tools=enabled_tools,
            language_pref=language_pref,
            output_style_config=output_style_config,
        ),
        asyncio.to_thread(get_user_context),
        asyncio.to_thread(get_system_context),
    )

    return SystemPromptParts(
        default_system_prompt=default_prompt,
        user_context=user_ctx,
        system_context=system_ctx,
    )


def assemble_final_system_prompt(
    parts: SystemPromptParts,
    *,
    custom_system_prompt: str | None = None,
    append_system_prompt: str | None = None,
) -> list[str]:
    """組最終 system prompt(string[])。

    對應 TS asSystemPrompt([...defaultSystemPrompt, ...append])。
    """
    if custom_system_prompt is not None:
        result = [custom_system_prompt]
    else:
        result = list(parts.default_system_prompt)

    if append_system_prompt:
        result.append(append_system_prompt)

    return result


def append_system_context(
    system_prompt: list[str],
    system_context: dict[str, str],
) -> list[str]:
    """systemContext 接到 systemPrompt 尾端。對應 TS appendSystemContext。"""
    if not system_context:
        return system_prompt
    ctx_str = "\n".join(f"{k}: {v}" for k, v in system_context.items())
    return [*system_prompt, ctx_str]


def prepend_user_context(messages: list, user_context: dict[str, str]) -> list:
    """userContext 包成 user message 加在 messages 前綴。對應 TS prependUserContext。"""
    if not user_context:
        return messages
    ctx_str = "\n".join(f"{k}: {v}" for k, v in user_context.items())
    return [
        {"role": "user", "content": f"Context:\n{ctx_str}"},
        *messages,
    ]
```

### 5.6 `services/anthropic_client.py`(擴充)

```python
"""擴充 Phase 0 的 client,加 cache_control。"""

async def build_system_prompt_blocks(
    system_prompt: list[str],
    enable_caching: bool = True,
) -> list[dict]:
    """切 + 加 cache_control 標記。對應 TS buildSystemPromptBlocks。"""
    from claude_agent_py.prompt.cache_scope import split_sys_prompt_prefix

    blocks = split_sys_prompt_prefix(system_prompt, use_global_cache=enable_caching)
    result = []
    for b in blocks:
        block = {"type": "text", "text": b.text}
        if enable_caching and b.cache_scope is not None:
            # Anthropic API 的 cache_control
            block["cache_control"] = {"type": "ephemeral"}
            # scope='global' / 'org' 在 Anthropic API 是不同 cache key
            # 細節依 SDK 版本調整
        result.append(block)
    return result
```

## 6. 設計決策與取捨

### 為何用 markdown templates 而非硬編碼字串?

TS 把所有提示寫在 `prompts.ts` 一個 914 行檔案裡。Python 拆 template 檔的優點:

- 可以用 markdown editor 編輯 / 預覽
- 翻譯多語言時只改 templates,不動程式碼
- diff 友善(改提示時只看 templates)
- 設計師 / PM 可以參與

### 為何 cache 用 module-level dict 而非 ContextVar?

Phase 4 的 cache 是 process-wide,**多 session 共享**(同一 system prompt 內容真的一樣)。Phase 7 SaaS 化時若需要 per-tenant cache,改成 `ContextVar[dict[str, str]]`。

### 為何 `DANGEROUS_uncached` 強制 reason?

純粹**社會性守門**(對應 TS 設計)。`reason` 參數 runtime 不用,但:
- code review 時很顯眼(reviewer 會問「真的需要嗎?」)
- grep 容易找出所有破 cache 的點
- 強迫 caller 寫一句話說明動機

Python 用 `_reason: str` 底線前綴表示 unused 但語意保留。

### 為何 user_context 用 `prepend_user_context` 而非塞 system?

TS 設計:
- `systemContext` (Git 狀態)→ 接 system prompt 尾端
- `userContext` (CLAUDE.md)→ 包成 user message 前綴

理由:`userContext` 在不同專案不同(CLAUDE.md 內容 per-project),若放 system prompt 會讓 cache 完全分離 per-project。放在 messages 前綴反而能讓 system prompt 跨 project 共享。

Python port 直接照搬。

### Phase 4 故意不做的

| 項目 | 留給哪個 phase |
|---|---|
| MCP instructions section | Phase 5 |
| Token budget section | 不做(scope 外) |
| Brief / KAIROS sections | 不做 |
| frontmatter hook 整合 | Phase 8 |

## 7. 驗收標準

### 自動測試

```bash
pytest tests/prompt/ -v
```

關鍵測試:

- `test_section_cache.py`:命中 cache 不重 compute、`/clear` 後重 compute、DANGEROUS_uncached 每次重算
- `test_get_system_prompt.py`:輸出正確、boundary 在預期位置、靜態段不變
- `test_split_sys_prompt_prefix.py`:三條路徑(找到 boundary / 沒找到 / use_global_cache=false)
- `test_context.py`:Git 狀態抓對、CLAUDE.md 自動發現順序正確
- `test_custom_system_prompt.py`:custom 替換預設、append 接尾端

### 手動驗證

```bash
python -m claude_agent_py
# 觀察首次發 API 的 system prompt 切分
# (可在 anthropic_client.py 加 debug log 印出 system blocks)
```

預期:
- 看到 `[GLOBAL]` 一個大 block(靜態段)
- 看到 `[NULL]` 一個 block(動態段含 memory / env_info / language)
- 第二輪對話 cache_read_input_tokens > 0(命中)

### 整合驗證

設 `customSystemPrompt`:

```python
conv = Conversation(
    ctx=ctx,
    tools=...,
    custom_system_prompt="You are a Python expert."
)
```

預期:
- `default_system_prompt` 為空
- 最終 system 只含 custom + append
- `systemContext` 跳過(不接 Git 狀態)
- `userContext` 仍注入(CLAUDE.md 還是有)

## 8. 常見踩雷

### 踩雷 1:Boundary marker 是字面字串

`SYSTEM_PROMPT_DYNAMIC_BOUNDARY = "__SYSTEM_PROMPT_DYNAMIC_BOUNDARY__"`

它是 string[] 的其中一個元素,**不是 metadata**。`split_sys_prompt_prefix` 用 `index()` 找位置。若它意外出現在 prompt 內容(不太可能但要防)會 split 錯。可以在前面加 sentinel(罕用 unicode)。

### 踩雷 2:`asyncio.to_thread` 用法

`get_system_context` / `get_user_context` 內部用 subprocess(blocking)。直接 await 會阻塞 event loop。要用:

```python
await asyncio.to_thread(get_system_context)
```

把 sync 函式跑在 thread pool。

### 踩雷 3:Cache 跨 session 污染

Module-level `_section_cache` 不 reset 的話,session A 的 memory 內容會影響 session B 的 system prompt(若它們的 memory 不同)。

修法:每次 session 開始呼叫 `clear_system_prompt_sections()`,或改 ContextVar。

### 踩雷 4:Anthropic API cache_control 細節

不同 SDK 版本的 cache_control 格式不同。最新版:

```python
{"type": "ephemeral"}  # scope 在 ephemeral_lifetime / scope 欄位
```

對 SDK 文件,細節隨時可能變。

### 踩雷 5:CLAUDE.md 含敏感資料

CLAUDE.md 內容直接送模型。若 user 把 token / API key 寫進去,會送到 Anthropic API。要警告 user 不要這樣做(但不能阻止)。

### 踩雷 6:Section name 衝突

兩個 `system_prompt_section` 同 name → 後者覆蓋前者的 cache。寫測試確保 name 唯一(或加 dedup 邏輯)。

### 踩雷 7:模板載入錯誤

`(TEMPLATES_DIR / "intro.md").read_text()` 找不到 → 直接 crash。要在啟動時檢查 templates 都存在,或用 `try / except` 提供 fallback。

## 9. 參考資料

### docs/01-11

- [docs/08](../08-system-prompt.md) — 整章必讀,包括 cache scope 大節
- [docs/05 §5c](../05-settings-memory-context.md) — Context 組合流程

### TS 源檔

- `src/constants/prompts.ts` — 整檔 914 行,各 `getXXXSection` 函式
- `src/constants/systemPromptSections.ts` — 68 行(短但精)
- `src/utils/queryContext.ts` — 179 行(`fetchSystemPromptParts`)
- `src/utils/api.ts:321` — `splitSysPromptPrefix` 完整邏輯
- `src/context.ts` — Git + CLAUDE.md

### 外部資源

- [Anthropic prompt caching](https://docs.anthropic.com/en/docs/build-with-claude/prompt-caching) — 官方 cache_control 用法
- [GitPython](https://gitpython.readthedocs.io/) — get_system_context 用

## 完成檢查表

- [ ] Section cache 機制 + `/clear` reset
- [ ] DYNAMIC_BOUNDARY 切分
- [ ] 7 層靜態段 templates
- [ ] 動態段 + 整合 memory(Phase 3)
- [ ] context.py(Git + CLAUDE.md)
- [ ] cache scope 三分支
- [ ] customSystemPrompt / appendSystemPrompt
- [ ] 整合到 Conversation
- [ ] 觀察 cache_read 比例 > 80%(穩定對話下)
- [ ] 寫 Phase 4 心得

完成後進入 [Phase 5:MCP Integration](./05-mcp-integration.md)。

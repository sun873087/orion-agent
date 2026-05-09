# Phase 8:Hooks / Skills / Plugins

## 速覽

- **預計時程**:3-4 週
- **前置 Phase**:Phase 1(基礎 hook 框架)、Phase 4(system prompt section)、Phase 7(production)
- **後續 Phase**:Phase 9 / 10 用 hook 做 telemetry 與工具註冊
- **主要交付物**:
  - 完整 Hook 系統(8 種 event:PreToolUse / PostToolUse / Failure / UserPromptSubmit / SessionStart / Setup / SubagentStart / FileChanged)
  - `HookRegistry` + `HooksConfigManager`
  - Skill 系統(markdown frontmatter loader + `.claude/skills/` 掃描)
  - Plugin 市集架構(內建 + 第三方)
  - `register_frontmatter_hooks`(skill / command 內宣告 hook)

## ⚠️ Web Chat 場景調整(Webhook + Curated Marketplace)

> **TS 原設計**(CLI per-user):
> - Hook 是 `settings.json` 寫的 shell command,在 user 機器上執行
> - Plugin 從任意 git URL `git clone` 安裝
>
> **Web chat 改為**:
> - **Hook 改為 webhook URL**:user 設定 `{"webhook": "https://user.example.com/hook"}`,server POST event JSON 過去(timeout 5s)— **不執行任意 shell**
> - 進階:user 寫 hook script 在自己 sandbox(Phase 7)內跑(同 user code 安全等級)
> - **Plugin 改為 curated marketplace**:你 maintain plugin registry(內建 + 認證第三方),不允許任意 git URL clone
> - 影響的 skeleton:`hooks/config_manager.py:_build_shell_hook` 改 `_build_webhook_hook`(下方更新)、`plugins/marketplace.py:install_plugin(git_url)` 改 `install_from_registry(plugin_id)`

## 1. 目標與動機

Phase 1 已有 Pre/Post hook 簡化版。Phase 8 補完整套機制,讓系統**可擴展**:

```
無 hook:user 改不了 agent 行為
有 hook:user 在 settings.json 寫 yaml,自動每次工具執行前過 lint、後送通知

無 skill / plugin:工具寫死在程式碼
有 skill:user 寫 markdown 加新工具(無需改程式碼)
有 plugin:第三方分發 skill + hooks + MCP server 一整組
```

**對應 docs**:
- [docs/05](../05-settings-memory-context.md) Hook 系統(8 種 event)
- [docs/06 模組 9](../06-harness-engineering.md) 護欄(三層守門)

完成本 phase 後,你的 agent 是**可被擴展的平台**,不只是固定功能集。

## 2. TS 源檔映射

| Python 模組 | 對應 TS 源檔 | 行數 | 注意事項 |
|---|---|---|---|
| `src/hooks/types.py` | `src/types/hooks.ts` | 9 KB | 8 種 event 型別 |
| `src/hooks/registry.py` | `src/utils/hooks/` 多檔 | — | HookRegistry 主體 |
| `src/hooks/config_manager.py` | `src/utils/hooks/hooksConfigManager.ts` | — | 從 settings.json 載入 hook |
| `src/hooks/frontmatter.py` | `src/utils/hooks/registerFrontmatterHooks.ts` | — | skill / command frontmatter hook |
| `src/hooks/session_hooks.py` | `src/utils/hooks/sessionHooks.ts` | — | session-level event 編排 |
| `src/skills/loader.py` | `src/skills/loadSkillsDir.ts` | — | markdown 掃描 + frontmatter parse |
| `src/skills/builtin.py` | `src/skills/bundledSkills.ts` | — | 內建 skill |
| `src/skills/mcp_skill.py` | `src/skills/mcpSkillBuilders.ts` | — | MCP-derived skill |
| `src/plugins/builtin.py` | `src/plugins/builtinPlugins.ts` | — | 內建 plugin 註冊 |
| `src/plugins/loader.py` | `src/utils/plugins/pluginLoader.ts` | — | 動態載入 |
| `src/plugins/marketplace.py` | (新增) | — | 第三方 plugin 市集 |

## 3. 任務拆解

> **補充說明**:除主 8 種 event 外,還有更細的 hook 切點(對應 TS `utils/hooks/` 多檔):
> - `post_sampling_hooks`:模型 sampling 完成後、parse 前(對應 `postSamplingHooks.ts`)
> - `stop_failure_hooks`:turn 因 stop_reason 異常結束(對應 `stopHooks.ts`)
> - `structured_output_enforcement`:強制 SDK 結構化輸出(對應 `hookHelpers.ts:registerStructuredOutputEnforcement`)
> - `frontmatter_hooks`:skill / command 內 frontmatter 宣告的 hook(對應 `registerFrontmatterHooks.ts`,Phase 8 已涵蓋)
>
> 這些是「subhooks」— 在主 8 種 event 內的細部切點。實作時併入 `HookRegistry`。

### Week 1:8 種 hook event + HookRegistry

- [ ] 1.1 `hooks/types.py`:8 種 event 的 Pydantic schema
  - `PreToolUseEvent` / `PostToolUseEvent` / `PostToolUseFailureEvent`
  - `UserPromptSubmitEvent` / `SessionStartEvent` / `SetupEvent`
  - `SubagentStartEvent` / `FileChangedEvent`
- [ ] 1.2 `hooks/registry.py`:`HookRegistry` class(註冊、執行、結果處理)
- [ ] 1.3 改造 Phase 1 的簡化 hook framework → 用 `HookRegistry`
- [ ] 1.4 整合 8 種 event 到對應觸發點
- [ ] 1.5 測試:每種 event 觸發時 hook 執行、可取消 / 改 input

### Week 2:Config Manager + Frontmatter

- [ ] 2.1 `hooks/config_manager.py`:從 settings.json `hooks` 欄位讀取
- [ ] 2.2 settings hook 格式定義(yaml-like in JSON)
- [ ] 2.3 `hooks/frontmatter.py`:`register_frontmatter_hooks`(skill / command 內 `hooks:` 欄位)
- [ ] 2.4 整合到 session 啟動流程
- [ ] 2.5 測試:settings.json hook 正確 load + skill frontmatter hook 正確 register

### Week 3:Skill 系統

- [ ] 3.1 `skills/loader.py`:`load_skills_dir` 掃 `.claude/skills/`、`~/.claude/skills/`
- [ ] 3.2 frontmatter parse:`name` / `description` / `parameters` / `effort` / `model` / `hooks`
- [ ] 3.3 `skills/builtin.py`:內建 skill 列表(對應 bundled skills)
- [ ] 3.4 改造 Phase 1 的 SkillTool:用 `skills/loader` 動態載入
- [ ] 3.5 測試:skill 從 markdown 載入、執行、frontmatter hook 觸發

### Week 4:Plugin 市集 + 整合

- [ ] 4.1 `plugins/builtin.py`:內建 plugin metadata
- [ ] 4.2 plugin manifest 格式(`plugin.json` 含 skills / hooks / mcp servers)
- [ ] 4.3 `plugins/loader.py`:`load_all_plugins`(從 `~/.claude/plugins/`、市集等)
- [ ] 4.4 plugin enable / disable(寫到 settings.json)
- [ ] 4.5 `plugins/marketplace.py`:從 git URL 安裝(簡易市集)
- [ ] 4.6 整合測試:安裝一個 plugin → skill / hook / MCP 全自動接上
- [ ] 4.7 寫 Phase 8 心得

## 4. 模組架構與檔案

```
src/claude_agent_py/
├── hooks/
│   ├── __init__.py
│   ├── types.py                       # ◀ NEW 8 種 event Pydantic
│   ├── registry.py                    # ◀ NEW HookRegistry(擴充 Phase 1)
│   ├── config_manager.py              # ◀ NEW settings.json hook 載入
│   ├── frontmatter.py                 # ◀ NEW skill/command frontmatter hook
│   └── session_hooks.py               # ◀ NEW session-level 編排
│
├── skills/
│   ├── __init__.py
│   ├── loader.py                      # ◀ NEW markdown skill 掃描
│   ├── builtin.py                     # ◀ NEW 內建 skill registry
│   ├── mcp_skill.py                   # ◀ NEW MCP-derived skill
│   └── types.py                       # ◀ NEW Skill model
│
├── plugins/
│   ├── __init__.py
│   ├── types.py                       # ◀ NEW Plugin manifest model
│   ├── builtin.py                     # ◀ NEW 內建 plugin
│   ├── loader.py                      # ◀ NEW 動態載入
│   └── marketplace.py                 # ◀ NEW 從 git URL 安裝
│
└── tools/
    └── agent/
        └── skill_tool.py              # ◀ 改造:用 skills/loader
```

## 5. Python Skeleton

### 5.1 `hooks/types.py`(8 種 event)

```python
"""8 種 hook event。對應 TS types/hooks.ts。"""
from __future__ import annotations
from typing import Literal, Any
from pydantic import BaseModel


# === 共通 ===
class HookContext(BaseModel):
    """所有 event 共用的 context。"""
    session_id: str
    user_id: str | None = None


# === 1. PreToolUse ===
class PreToolUseEvent(BaseModel):
    type: Literal["PreToolUse"] = "PreToolUse"
    context: HookContext
    tool_name: str
    tool_use_id: str
    tool_input: dict


class PreToolUseResult(BaseModel):
    """hook 回傳:可改 input、可阻擋。"""
    abort: bool = False
    abort_reason: str | None = None
    modified_input: dict | None = None
    additional_data: dict | None = None  # 注入額外 context


# === 2. PostToolUse(成功)===
class PostToolUseEvent(BaseModel):
    type: Literal["PostToolUse"] = "PostToolUse"
    context: HookContext
    tool_name: str
    tool_use_id: str
    tool_input: dict
    tool_output: Any


# === 3. PostToolUseFailure ===
class PostToolUseFailureEvent(BaseModel):
    type: Literal["PostToolUseFailure"] = "PostToolUseFailure"
    context: HookContext
    tool_name: str
    tool_use_id: str
    tool_input: dict
    error_message: str


# === 4. UserPromptSubmit ===
class UserPromptSubmitEvent(BaseModel):
    type: Literal["UserPromptSubmit"] = "UserPromptSubmit"
    context: HookContext
    prompt: str


class UserPromptSubmitResult(BaseModel):
    abort: bool = False
    additional_context: str | None = None  # 注入到 system prompt


# === 5. SessionStart ===
class SessionStartEvent(BaseModel):
    type: Literal["SessionStart"] = "SessionStart"
    context: HookContext
    cwd: str


# === 6. Setup ===
class SetupEvent(BaseModel):
    type: Literal["Setup"] = "Setup"
    context: HookContext


# === 7. SubagentStart ===
class SubagentStartEvent(BaseModel):
    type: Literal["SubagentStart"] = "SubagentStart"
    context: HookContext
    parent_session_id: str
    subagent_type: str
    prompt: str


# === 8. FileChanged ===
class FileChangedEvent(BaseModel):
    type: Literal["FileChanged"] = "FileChanged"
    context: HookContext
    file_path: str
    change_type: Literal["created", "modified", "deleted"]


HookEvent = (
    PreToolUseEvent | PostToolUseEvent | PostToolUseFailureEvent
    | UserPromptSubmitEvent | SessionStartEvent | SetupEvent
    | SubagentStartEvent | FileChangedEvent
)


HookEventName = Literal[
    "PreToolUse", "PostToolUse", "PostToolUseFailure",
    "UserPromptSubmit", "SessionStart", "Setup",
    "SubagentStart", "FileChanged",
]
```

### 5.2 `hooks/registry.py`

```python
"""HookRegistry — 中央註冊與執行。"""
from __future__ import annotations
from typing import Callable, Awaitable, Any
from collections import defaultdict
import asyncio
import structlog

from claude_agent_py.hooks.types import HookEvent, HookEventName


log = structlog.get_logger()


HookFn = Callable[[HookEvent], Awaitable[Any]]


class HookRegistry:
    def __init__(self):
        self._handlers: dict[HookEventName, list[HookFn]] = defaultdict(list)

    def register(self, event: HookEventName, fn: HookFn) -> None:
        self._handlers[event].append(fn)

    def unregister(self, event: HookEventName, fn: HookFn) -> None:
        if fn in self._handlers[event]:
            self._handlers[event].remove(fn)

    async def fire(self, event: HookEvent) -> list[Any]:
        """觸發所有註冊的 handler,收集結果。"""
        handlers = self._handlers.get(event.type, [])
        results = []
        for h in handlers:
            try:
                result = await h(event)
                results.append(result)
            except Exception as e:
                log.warning(f"hook handler failed", event=event.type, error=str(e))
        return results

    async def fire_pre_tool_use(self, event) -> dict | None:
        """聚合 PreToolUseResult:任一 abort → abort,修改 input → 用最後修改。"""
        results = await self.fire(event)
        for r in results:
            if r is not None and r.abort:
                return {"abort": True, "reason": r.abort_reason}
        # input 修改:最後一個寫入的勝出(或合併,看設計)
        modified = next(
            (r.modified_input for r in reversed(results)
             if r is not None and r.modified_input is not None),
            None,
        )
        return {"abort": False, "modified_input": modified}
```

### 5.3 `hooks/config_manager.py`

```python
"""從 settings.json 載入 hook 設定。對應 TS hooksConfigManager.ts。"""
from __future__ import annotations
import asyncio
from pathlib import Path
import json

from claude_agent_py.hooks.registry import HookRegistry
from claude_agent_py.hooks.types import HookEventName


# settings.json 範例:
# {
#   "hooks": {
#     "PreToolUse": [
#       {"command": "/path/to/lint-check.sh", "matcher": {"tool_name": "Edit"}}
#     ],
#     "PostToolUse": [
#       {"command": "echo 'tool ran' >> ~/audit.log"}
#     ]
#   }
# }


def load_hooks_from_settings(
    settings: dict,
    registry: HookRegistry,
) -> None:
    """讀 settings,把每個 hook 註冊到 registry。"""
    hooks_config = settings.get("hooks", {})
    for event_name, hook_list in hooks_config.items():
        if event_name not in HookEventName.__args__:
            continue
        for hook_def in hook_list:
            handler = _build_shell_hook(hook_def)
            registry.register(event_name, handler)


def _build_shell_hook(hook_def: dict):
    """⚠️ CLI / 本機 dev only。Web chat 用 _build_webhook_hook。

    settings 裡的 hook 是 shell 命令 → 包成 async handler。
    """
    command = hook_def["command"]
    matcher = hook_def.get("matcher", {})

    async def handler(event):
        # 過濾 matcher
        if matcher.get("tool_name") and event.tool_name != matcher["tool_name"]:
            return None

        # 把 event 序列化成 JSON 透過 stdin 給命令
        proc = await asyncio.create_subprocess_shell(
            command,
            stdin=asyncio.subprocess.PIPE,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
        )
        event_json = event.model_dump_json().encode()
        stdout, stderr = await proc.communicate(input=event_json)

        # 命令的 stdout 期望是 JSON,parse 成 result
        if proc.returncode != 0:
            return None
        try:
            return json.loads(stdout) if stdout.strip() else None
        except json.JSONDecodeError:
            return None

    return handler


def _build_webhook_hook(hook_def: dict):
    """Web chat 模式 hook:POST event JSON 到 user 設的 URL。

    settings 範例:
      {
        "hooks": {
          "PostToolUse": [
            {"webhook": "https://user.example.com/claude-hook",
             "matcher": {"tool_name": "Edit"},
             "secret": "xxxxx"}
          ]
        }
      }
    """
    import httpx
    import hmac
    import hashlib
    import json

    webhook_url = hook_def["webhook"]
    matcher = hook_def.get("matcher", {})
    secret = hook_def.get("secret")  # 可選:HMAC 簽名

    async def handler(event):
        if matcher.get("tool_name") and event.tool_name != matcher["tool_name"]:
            return None

        body = event.model_dump_json()
        headers = {"Content-Type": "application/json"}
        if secret:
            sig = hmac.new(secret.encode(), body.encode(), hashlib.sha256).hexdigest()
            headers["X-Claude-Signature"] = f"sha256={sig}"

        try:
            async with httpx.AsyncClient(timeout=5.0) as client:
                response = await client.post(webhook_url, content=body, headers=headers)
                if response.status_code != 200:
                    return None
                return response.json() if response.text else None
        except (httpx.TimeoutException, httpx.RequestError):
            return None  # webhook 失敗不影響主流程

    return handler


def load_hooks_from_settings_for_web(settings: dict, registry: HookRegistry) -> None:
    """Web chat 模式 hook 載入(只接受 webhook,不接受 shell command)。"""
    hooks_config = settings.get("hooks", {})
    for event_name, hook_list in hooks_config.items():
        if event_name not in HookEventName.__args__:
            continue
        for hook_def in hook_list:
            if "webhook" in hook_def:
                handler = _build_webhook_hook(hook_def)
                registry.register(event_name, handler)
            elif "command" in hook_def:
                # 安全考量:web chat 模式拒絕 shell command hook
                log.warning(
                    "Shell command hook rejected in web chat mode",
                    event=event_name,
                )
                continue

```

### 5.4 `skills/loader.py`

```python
"""Skill 載入。對應 TS skills/loadSkillsDir.ts。"""
from __future__ import annotations
from dataclasses import dataclass
from pathlib import Path

import frontmatter  # python-frontmatter


@dataclass
class Skill:
    name: str
    description: str
    body: str  # markdown 主體(送給模型當 prompt)
    parameters: dict | None = None  # JSON Schema
    hooks: list[dict] | None = None  # frontmatter 內宣告的 hook
    effort: str | None = None  # low / medium / high
    model: str | None = None  # 覆寫模型
    source_path: Path | None = None


def load_skills_dir(directory: Path) -> list[Skill]:
    """掃描目錄載入所有 .md skill。"""
    if not directory.exists():
        return []

    result = []
    for md_path in directory.glob("**/*.md"):
        try:
            post = frontmatter.load(md_path)
            skill = Skill(
                name=post.metadata.get("name", md_path.stem),
                description=post.metadata.get("description", ""),
                body=post.content,
                parameters=post.metadata.get("parameters"),
                hooks=post.metadata.get("hooks"),
                effort=post.metadata.get("effort"),
                model=post.metadata.get("model"),
                source_path=md_path,
            )
            result.append(skill)
        except Exception as e:
            # log warning,跳過
            continue

    return result


def load_all_skills() -> list[Skill]:
    """從多個來源載入 skill。對應 TS bundledSkills + .claude/skills 掃描。"""
    sources = [
        Path("~/.claude/skills").expanduser(),  # 全域
        Path(".claude/skills"),  # 專案
        # 進階:plugin 提供的 skills(Phase 8 後段加)
    ]
    all_skills = []
    for src in sources:
        all_skills.extend(load_skills_dir(src))

    # dedup by name(後者覆蓋前者?or 報衝突?)
    return all_skills
```

範例 skill:

```markdown
---
name: code-review
description: Review code changes for bugs and style issues
parameters:
  files:
    type: array
    items: {type: string}
hooks:
  - event: PreToolUse
    matcher: {tool_name: Edit}
    command: ./scripts/pre-edit-lint.sh
effort: medium
---

You are a code reviewer. For each file in `files`, perform a careful review:

1. Bugs and logic errors
2. Style and naming consistency
3. Test coverage
...
```

### 5.5 `plugins/types.py`

```python
"""Plugin manifest。"""
from __future__ import annotations
from dataclasses import dataclass
from pathlib import Path


@dataclass
class PluginManifest:
    name: str
    version: str
    description: str
    skills: list[str]  # relative paths
    hooks: list[dict]  # 同 settings.json 格式
    mcp_servers: dict  # MCP server config
    source: Path  # plugin 根目錄
```

`plugin.json` 範例:

```json
{
  "name": "github-tools",
  "version": "0.1.0",
  "description": "GitHub PR/issue tools",
  "skills": ["skills/review-pr.md", "skills/triage-issues.md"],
  "hooks": [
    {"event": "PostToolUse",
     "matcher": {"tool_name": "Bash"},
     "command": "node hooks/audit.js"}
  ],
  "mcp_servers": {
    "github": {"command": "node", "args": ["mcp/server.js"]}
  }
}
```

### 5.6 `plugins/loader.py`

```python
"""Plugin 載入。對應 TS plugins/builtinPlugins.ts + utils/plugins/pluginLoader.ts。"""
from __future__ import annotations
import json
from pathlib import Path

from claude_agent_py.plugins.types import PluginManifest


def discover_plugins(roots: list[Path]) -> list[PluginManifest]:
    """掃描多個目錄找 plugin.json。"""
    found = []
    for root in roots:
        if not root.exists():
            continue
        for manifest_path in root.glob("*/plugin.json"):
            try:
                data = json.loads(manifest_path.read_text())
                manifest = PluginManifest(
                    name=data["name"],
                    version=data["version"],
                    description=data.get("description", ""),
                    skills=data.get("skills", []),
                    hooks=data.get("hooks", []),
                    mcp_servers=data.get("mcp_servers", {}),
                    source=manifest_path.parent,
                )
                found.append(manifest)
            except Exception:
                continue
    return found


def get_enabled_plugins(settings: dict) -> set[str]:
    """從 settings.json 讀 enabled plugins。"""
    return set(settings.get("enabledPlugins", []))


async def load_all_plugins(
    settings: dict,
    *,
    hook_registry,
    skill_loader,
    mcp_client,
) -> list[PluginManifest]:
    """完整載入 plugin → 註冊 skill / hook / MCP。"""
    enabled = get_enabled_plugins(settings)
    roots = [
        Path("~/.claude/plugins").expanduser(),
        Path(".claude/plugins"),
    ]

    discovered = discover_plugins(roots)
    loaded = []
    for plugin in discovered:
        if plugin.name not in enabled:
            continue

        # 載入 plugin 的 skills
        for skill_rel in plugin.skills:
            skill_path = plugin.source / skill_rel
            # 用 skill_loader 載入
            ...

        # 註冊 plugin 的 hooks
        for hook_def in plugin.hooks:
            event = hook_def["event"]
            handler = _build_shell_hook(hook_def, plugin.source)
            hook_registry.register(event, handler)

        # 連接 plugin 的 MCP servers
        for server_name, server_config in plugin.mcp_servers.items():
            await mcp_client.connect(server_config)

        loaded.append(plugin)

    return loaded
```

### 5.7 `plugins/marketplace.py`(Web Chat 版:Curated Registry)

```python
"""Curated plugin marketplace。

Web chat 不接受任意 git URL,改成 registry 機制:
  - 內建 plugins:你自己寫的(rs/, vendor/...)
  - 認證 plugins:第三方提交,你 review 過
  - User-private plugins:user 自己寫(進階,只在他 sandbox 跑,Phase 9)

不允許 git clone 任意 URL → 防 supply chain 攻擊。
"""
from __future__ import annotations
import json
from pathlib import Path
from typing import Literal
from dataclasses import dataclass

import httpx


@dataclass
class RegistryEntry:
    plugin_id: str
    """e.g. 'github-tools@1.0.0'"""

    name: str
    description: str
    version: str
    source: Literal["builtin", "verified", "user-private"]
    download_url: str  # 你的 CDN / S3
    signature: str | None = None  # SHA-256 of bundle
    author: str | None = None


class PluginRegistry:
    """從你的 server-side registry 讀 plugin metadata。"""

    def __init__(self, registry_url: str):
        self.registry_url = registry_url
        self._cache: dict[str, RegistryEntry] = {}

    async def list_available(self) -> list[RegistryEntry]:
        """從 registry 拉所有可用 plugin。"""
        async with httpx.AsyncClient() as client:
            response = await client.get(f"{self.registry_url}/plugins.json")
            data = response.json()
            return [RegistryEntry(**p) for p in data]

    async def get(self, plugin_id: str) -> RegistryEntry | None:
        if plugin_id in self._cache:
            return self._cache[plugin_id]
        for entry in await self.list_available():
            self._cache[entry.plugin_id] = entry
            if entry.plugin_id == plugin_id:
                return entry
        return None


async def install_from_registry(
    plugin_id: str,
    user_id: str,
    *,
    registry: PluginRegistry,
    install_dir: Path,
) -> Path:
    """從 registry 下載並安裝 plugin。"""
    entry = await registry.get(plugin_id)
    if entry is None:
        raise ValueError(f"Plugin {plugin_id} not in registry")

    # 下載 zip / dxt
    async with httpx.AsyncClient() as client:
        response = await client.get(entry.download_url)
        bundle_bytes = response.content

    # 驗 signature(若有)
    if entry.signature:
        import hashlib
        actual = hashlib.sha256(bundle_bytes).hexdigest()
        if actual != entry.signature:
            raise ValueError(f"Plugin signature mismatch")

    # 解 zip 到 user 的 plugin dir(per-user)
    target = install_dir / user_id / entry.plugin_id.replace("@", "_")
    target.mkdir(parents=True, exist_ok=True)

    import zipfile
    from io import BytesIO
    with zipfile.ZipFile(BytesIO(bundle_bytes)) as zf:
        zf.extractall(target)

    return target


async def uninstall(plugin_id: str, user_id: str, install_dir: Path) -> None:
    target = install_dir / user_id / plugin_id.replace("@", "_")
    if target.exists():
        import shutil
        shutil.rmtree(target)
```

#### Plugin Registry 後端 schema

`plugins.json` 範例(你自己 host):

```json
{
  "plugins": [
    {
      "plugin_id": "github-tools@1.0.0",
      "name": "GitHub Tools",
      "description": "PR / issue / repo operations",
      "version": "1.0.0",
      "source": "builtin",
      "download_url": "https://cdn.example.com/plugins/github-tools-1.0.0.zip",
      "signature": "abc123...",
      "author": "your-company"
    }
  ]
}
```

## 6. 設計決策與取捨

### 為何 hook handler 用 shell 命令而非 Python 函式?

**對應 TS 設計**(對應 `settings.json` 內 `command` 字串)。理由:

- **語言中立**:user 用 bash / Python / Node 寫 hook 都行
- **隔離**:hook crash 不影響 agent
- **可審計**:command 字串看得見

代價:
- 啟動 subprocess 慢(~50ms)
- 序列化 JSON 過 stdin/stdout

替代:Python 模組 hook(`module:function` 格式),省 fork。Phase 8 同時支援,user 選。

### 為何 8 種 event?

對應 TS 設計,各自處理不同生命週期切點:
- 工具相關 3 種:Pre / Post / Failure
- Session 相關 2 種:SessionStart / Setup
- 子流程 2 種:UserPromptSubmit / SubagentStart
- 檔案 1 種:FileChanged

省略 / 合併會讓 user 沒辦法精準掛點。對應 docs/05 的 hook 系統。

### 為何 Skill 是 markdown?

- 不要寫 code 就能加新 prompt-based 工具
- frontmatter 標準格式(YAML)有現成 parser
- markdown body 直接送模型當 prompt
- 相容 TS 的 skill 設計(可互通)

複雜邏輯仍需要寫 Python tool。Skill 是「prompt + 參數」的中間層。

### 為何 Plugin 同時包 skill + hook + MCP?

一個常見場景需要這三者:
- 「GitHub 整合 plugin」:有 skill(/review-pr)+ hook(PreToolUse 過 lint)+ MCP server(github 工具)

分散安裝麻煩。一個 `plugin.json` 一鍵搞定。對應 TS `plugins/builtinPlugins.ts` 設計。

### 為何 Plugin 從 git URL 安裝?

- **去中心**:不需要中央 registry
- **版本管理**:git tag / branch
- **fork 友善**:user fork 後改一改可用

對應 TS `{name}@{marketplace}` ID 格式。Phase 8 簡化版只支援 git URL,進階版可支援 npm-style registry。

### Phase 8 故意不做的

| 項目 | 留給哪個 phase |
|---|---|
| Hook DSL(yaml-based 條件)| 不做(simple shell 夠用) |
| Plugin 簽名驗證 | 不做(production 才需要) |
| Hot reload skill / hook | Phase 9 |
| Plugin 沙盒(plugin 不該執行任意程式)| 重要但範疇大,可 Phase 9 |

## 7. 驗收標準

### 自動測試

```bash
pytest tests/hooks/ tests/skills/ tests/plugins/ -v
```

關鍵測試:

- `test_8_event_types.py`:每種 event 觸發位置正確
- `test_pre_tool_use_abort.py`:hook abort → 工具不執行
- `test_pre_tool_use_modify_input.py`:hook 改 input → 工具用新 input
- `test_skill_load.py`:.md frontmatter 正確 parse、缺欄位 graceful
- `test_skill_frontmatter_hook.py`:skill 內宣告的 hook 自動 register
- `test_plugin_install.py`:從 mock git URL 安裝、enable / disable
- `test_plugin_lifecycle.py`:enable plugin → skill / hook / MCP 全接上

### 手動驗證

寫一個 `~/.claude/skills/be-concise.md`:

```markdown
---
name: be-concise
description: Force concise responses
---

You should respond as concisely as possible.
```

呼叫 skill:
```
> Use the be-concise skill to summarize this article: [URL]
```

預期:模型載入 skill body + URL,回應簡潔。

寫 hook 在 `settings.json`:

```json
{
  "hooks": {
    "PreToolUse": [
      {"command": "echo 'tool: '$(jq -r .tool_name) >> /tmp/audit.log"}
    ]
  }
}
```

跑對話 → check `/tmp/audit.log` 有每個 tool 紀錄。

### 整合驗證

裝一個完整 plugin(自寫一個 `plugin.json` 含 skill + hook + MCP),驗證:
- enable 後 skill 出現在 SkillTool 列表
- hook 命中時觸發
- MCP server 連線成功,工具出現在 tools registry

## 8. 常見踩雷

### 踩雷 1:Hook 順序

多個 hook 註冊到同一 event,順序怎麼定?Phase 8 用註冊順序。但若 Pre hook A 改 input、B 也改 input → 後者 wins(覆蓋前者)。

精細需求(merge / chain)要明確設計。

### 踩雷 2:Hook subprocess 卡死

shell hook 卡死 → 整個 turn 卡。要加 timeout:

```python
proc = await asyncio.create_subprocess_shell(...)
try:
    await asyncio.wait_for(proc.communicate(...), timeout=5.0)
except asyncio.TimeoutError:
    proc.kill()
    return None
```

對應 TS `services/hookExecution` 也有 timeout。

### 踩雷 3:Frontmatter parse 容錯

Skill frontmatter 寫錯(missing colon、wrong type)→ `frontmatter.load` 拋。要 try/except,跳過該 skill,log warning。

### 踩雷 4:Skill name 衝突

兩個 skill 同 name(專案 vs 全域)→ 哪個勝出?Phase 8 用 last-wins(專案覆蓋全域)。對應 TS 也是這樣。

### 踩雷 5:Plugin 互相依賴

Plugin A 依賴 plugin B 的 skill / MCP server。如何解?Phase 8 不做依賴解析(每個 plugin 獨立)。複雜情境讓 user 自己處理。

### 踩雷 6:Hook injection 攻擊

惡意 plugin 寫的 hook 可以 hijack `Bash` tool 改 command 為 `rm -rf /`。Phase 8 信任 user 安裝的 plugin。Phase 9 加 plugin 沙盒(限制 hook 能做什麼)。

### 踩雷 7:Settings hot reload

User 改 `settings.json` 後 hook 沒立即生效。Phase 8 簡化:重啟 session 才 reload。Phase 10 可加 watch + 動態 reload。

## 9. 參考資料

### docs/01-11

- [docs/05](../05-settings-memory-context.md) — Hook 系統 8 種 event
- [docs/06 模組 9](../06-harness-engineering.md) — 護欄三層守門

### TS 源檔

- `src/types/hooks.ts` — 8 種 event Pydantic schema 對應
- `src/utils/hooks/hooksConfigManager.ts` — settings.json 載入
- `src/utils/hooks/registerFrontmatterHooks.ts` — skill / command frontmatter
- `src/skills/loadSkillsDir.ts` — markdown 掃描
- `src/plugins/builtinPlugins.ts` — plugin 註冊

### 外部資源

- [python-frontmatter](https://python-frontmatter.readthedocs.io/) — markdown frontmatter parser
- [PEP 621 — Project metadata](https://peps.python.org/pep-0621/) — manifest 設計參考

## 完成檢查表

- [ ] 8 種 hook event 全部觸發點正確
- [ ] HookRegistry 支援 register / fire / unregister
- [ ] Settings.json hook 載入(shell command 包裝)
- [ ] Skill markdown loader + frontmatter parse
- [ ] SkillTool 整合動態 skill
- [ ] Plugin manifest + discovery
- [ ] Plugin enable / disable
- [ ] Plugin 從 git URL 安裝
- [ ] 端到端 plugin 範例驗證
- [ ] 寫 Phase 8 心得

完成後進入 [Phase 9:Worktree + Telemetry](./09-worktree-telemetry.md)。

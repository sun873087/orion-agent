# Phase 8 — Hooks / Skills / Plugins 基礎 完工記錄

**完成日期**:2026-05-07
**Plan doc**:`docs/phases/08-hooks-skills-plugins.md`(範圍 C:Hooks 完整 +
Skills v2 + Plugins 基礎,**不含** marketplace registry / git URL 安裝 → Phase 8c)
**狀態**:✅ `make check` 全綠 — **400 unit tests passed**(無 skipped),
mypy --strict 121 files clean,ruff clean。

---

## 交付清單

### 新增模組

```
src/orion_agent/
├── hooks/
│   ├── events.py                         [改] 加 6 種新 event(從 dataclass 擴)
│   ├── registry.py                       [改] 加 fire / fire_pre_tool_use /
│   │                                          fire_user_prompt_submit / unregister / count
│   ├── config_manager.py                 [新] settings.json hook 載入(shell + webhook)
│   └── frontmatter.py                    [新] register_frontmatter_hooks
├── skills/                               [全新]
│   ├── __init__.py
│   ├── loader.py                         frontmatter parse + load_all_skills(last-wins)
│   └── builtin.py                        be-concise / review-diff
└── plugins/                              [全新]
    ├── __init__.py
    ├── types.py                          PluginManifest
    ├── loader.py                         discover / get_enabled / load_all_plugins /
    │                                       enable / disable
    └── builtin.py                        (空清單,等實質內建 plugin)
```

### 修改既有檔

```
src/orion_agent/
├── core/conversation.py                  send() 加 SessionStart / UserPromptSubmit hook;
│                                          Conversation 加 _session_started 內部欄位
├── core/state.py                         (Phase 7 既有)
├── core/tool_execution.py                run_one_tool 加 PreToolUse modified_input、
│                                          PostToolUseFailure、FileChanged event
├── tools/agent/skill_tool.py             改用 skills.loader 動態載入(dropping disk path
│                                          硬 coding;支援 builtin + frontmatter)
├── tools/agent/agent_tool.py             加 parent_hooks 參數 + SubagentStart 觸發
├── api/app.py                            lifespan 起 HookRegistry + 觸發 SetupEvent

pyproject.toml                            python-frontmatter>=1.1
                                          mypy override:frontmatter.* ignore_missing_imports
```

### Tests(全新,8 檔,共 53 案例)

```
tests/unit/hooks/
├── test_events_phase8.py        9 tests(8 種 event + Result 型別 + to_serializable)
├── test_registry_phase8.py      8 tests(fire / fire_pre_tool_use 聚合 / fire_ups 聚合 /
│                                         unregister / 例外 swallow)
├── test_config_manager.py       9 tests(shell + webhook + matcher + abort 路徑 + web_only)
└── test_frontmatter.py          4 tests(register_frontmatter_hooks)
tests/unit/skills/
└── test_loader.py               8 tests(load_skills_dir / find_skill / last-wins / builtin)
tests/unit/plugins/
└── test_loader.py               10 tests(discover / enable / disable / load_all_plugins /
                                          web_only / mcp_servers / skill_dirs)

修改既有:
tests/unit/hooks/test_registry.py         "pre_tool_use" → "PreToolUse" 等(Phase 8 改 PascalCase)
tests/unit/core/test_tool_execution.py    同上
tests/unit/tools/test_skill_tool.py       test_no_dir → 改驗 fallback 到 builtin
```

---

## 設計決策

### 1. 8 種 hook event,event.type 用 PascalCase 字串

對應 spec `HookEventName` Literal:

```
PreToolUse / PostToolUse / PostToolUseFailure /
UserPromptSubmit / SessionStart / Setup /
SubagentStart / FileChanged
```

Phase 1 用 snake_case(`pre_tool_use`),本 phase **改 PascalCase 對齊 TS spec**。
影響 2 個 Phase 1 測試(已更新)。registry.register("PreToolUse", handler)。

### 2. Event 雙視圖:in-process callback + serializable

每個 event 是 dataclass,直接拿 callback 用(可訪 `tool` / `ctx` 物件)。
也提供 `event.to_serializable() -> dict` 把物件 ref 拿掉,供:
- shell hook command 用 stdin JSON
- webhook POST body
- log / telemetry

### 3. HookRegistry 雙 API

- **Phase 1 API 留下不動**(`dispatch / pre_tool_use / post_tool_use`),向後相容
- **Phase 8 加**:
  - `fire(event) -> list[Any]` — 跑全部 handler、收 list 回傳、例外 swallow + log
  - `fire_pre_tool_use(event) -> PreToolUseResult` — 聚合 abort / modified_input(後者 wins)
  - `fire_user_prompt_submit(event) -> UserPromptSubmitResult` — 聚合 abort / additional_context(後者 join)
  - `unregister(event_type, callback)` / `count(event_type)`

`tool_execution.run_one_tool` 改用 `fire_pre_tool_use`,因此 PreToolUse hook 現在可:
- 回 `False` → 阻擋(向後相容)
- 回 `PreToolUseResult(abort=True, abort_reason=...)` → 阻擋,有理由
- 回 `PreToolUseResult(modified_input={...})` → 改工具 input

### 4. settings.json hook → shell command + webhook 雙模

`load_hooks_from_settings(settings, registry, web_only=False)`:
- `{"command": "..."}`:subprocess + JSON over stdin/stdout,5s timeout
- `{"webhook": "https://..."}`:httpx POST,可選 HMAC-SHA256 簽名 (`X-Orion-Signature`)
- `web_only=True` → 拒絕 shell command,只允許 webhook(production / 共享環境)

`matcher: {tool_name: ..., user_id: ...}` 簡易過濾。

### 5. Frontmatter hook(skill / plugin 內宣告)

`register_frontmatter_hooks(hooks_list, registry, web_only=False, source=...)`
重用 `_build_handler`,讓 skill 的 frontmatter `hooks:` 欄位、plugin manifest 的
`hooks:` 欄位、settings.json 的 `hooks:` 欄位 走同一條註冊路徑。

### 6. Skill = markdown + YAML frontmatter

`load_skills_dir(directory)` parse 所有 `*.md`,`load_all_skills(extra_dirs=None)`
合併:
1. **builtin**(`be-concise`, `review-diff`)
2. `~/.orion/skills/`(全域,可由 `ORION_SKILLS_DIR` 覆蓋)
3. `.orion/skills/`(專案 cwd)
4. `extra_dirs`(plugin 提供)

**Last-wins**:同名 skill 後者覆蓋前者(對應 TS 設計)。`SkillTool` 改用 loader,
不再硬讀檔。「目錄不存在」不再是錯誤 — fallback 到 builtin。

### 7. Plugin manifest 一鍵接 hook + skill + MCP

`plugin.json` 範例:

```json
{
  "name": "github-tools",
  "version": "0.1.0",
  "skills": ["skills/review-pr.md"],
  "hooks": [{"event": "PostToolUse", "webhook": "https://..."}],
  "mcp_servers": {"github": {"command": "node", "args": ["mcp.js"]}}
}
```

`load_all_plugins(settings, hook_registry=...)` 流程:
1. 掃 builtin + `~/.orion/plugins/*/plugin.json` + `.orion/plugins/*/plugin.json`
2. filter `settings["enabledPlugins"]`
3. 註 hook(透過 `register_frontmatter_hooks`,支援 web_only)
4. 收集 skill_dirs(caller 傳給 `load_all_skills(extra_dirs=...)`)
5. 收集 mcp_servers(namespaced `<plugin>__<server>`,caller 自行 connect)

`enable_plugin / disable_plugin` 寫 `settings["enabledPlugins"]`(in-place + return)。

### 8. SubagentStart 由 parent registry 觸發

AgentTool 拿 `parent_hooks: HookRegistry | None`(child 的 hooks empty,避免重複)。
spawn 子 agent 前 `parent_hooks.fire(SubagentStartEvent(...))` 通知 parent registry。

### 9. FileChanged 觸發點

`tool_execution.run_one_tool`,當 `tool_name in ("Write", "Edit")` 且 `is_error=False` 時,
從 `raw_input["path"]` 取絕對路徑,fire FileChangedEvent(`change_type=created` for Write,
`modified` for Edit)。

---

## 關鍵 trace 範例

**PreToolUse hook 改 input + 阻擋 — settings.json 範例:**

```json
{
  "hooks": {
    "PreToolUse": [
      {
        "command": "scripts/lint-edit.sh",
        "matcher": {"tool_name": "Edit"},
        "timeout_seconds": 3
      }
    ]
  }
}
```

`scripts/lint-edit.sh` 從 stdin 讀 event JSON,根據 path 決定:
- 印 `{"abort": true, "abort_reason": "lint failed"}` → 阻擋 Edit
- 印 `{"modified_input": {...}}` → 改 Edit input(例:auto-format old_string)
- 印空 → 放行

**UserPromptSubmit hook 注入 context:**

```json
{
  "hooks": {
    "UserPromptSubmit": [
      {"webhook": "https://my-rag.example/inject"}
    ]
  }
}
```

webhook 收到 prompt + session_id,從 RAG retrieve 相關文件,回:

```json
{"additional_context": "[Relevant docs]\n- Doc A: ...\n- Doc B: ..."}
```

→ append 到 system prompt 後再進 query_loop。

---

## Verification

```bash
cd orion-agent/api/

make check
# → ruff All checks passed!
# → mypy --strict: 121 files, 0 issues
# → pytest: 400 passed, 0 skipped(15s)
```

---

## Phase 8 故意先不做(都已開新 phase plan)

| 項目 | 留給 |
|---|---|
| Plugin Marketplace(curated registry + signature 驗證) | Phase 8c(`docs/phases/22-plugin-marketplace.md`) |
| Plugin 從 git URL 安裝 | Phase 8c |
| Plugin 沙盒(限制 hook 能做什麼) | Phase 8c |
| Hot reload skill / hook | Phase 9+ |
| Hook DSL(yaml-based 條件) | 不做(simple shell + webhook 夠用) |
| Plugin 互相依賴解析 | Phase 9+ |
| Skill parameters 進 SkillTool input schema(動態 Pydantic) | Phase 9+ |

---

## 風險與已緩解

| 風險 | 緩解 |
|---|---|
| Phase 1 hook 名稱 snake_case 改 PascalCase | 既有 4 個測試已更新 |
| Yield + return + dynamic import 在 async generator 觸發 hang | 把 `Terminal` import 提到 module top(避免 inner import 與 generator state 衝突) |
| Shell hook 卡死 | 每筆 5s timeout(可由 `timeout_seconds` 覆蓋) |
| Webhook 失敗影響主流程 | timeout + try/except,失敗回 None(不擋) |
| Frontmatter parse 錯誤 | log warning + skip,不擋整個 dir |
| Skill name 衝突 | last-wins(對應 TS 設計) |
| Plugin 來源不可信 | `web_only=True` 拒絕 shell command,只允許 webhook |

---

## Tests 摘要

| Suite | 數量 | 說明 |
|---|---|---|
| Phase 0–7 既有 | 347 | 全綠不動(2 Docker test 現以 DOCKER_HOST 跑) |
| **Phase 8 hooks** | 30 | events / registry / config_manager / frontmatter |
| **Phase 8 skills** | 8 | loader / builtin |
| **Phase 8 plugins** | 10 | discover / load_all_plugins / enable / disable |
| 修改既有(對齊 PascalCase) | 5 | 通過 |
| **總計** | **400** | mypy --strict + ruff 全綠 |

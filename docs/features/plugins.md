# Plugins

第三方寫 Python code 擴充 orion-agent — 加新 tool / 新 hook / 新 system prompt block。

**實作位置**:`packages/orion-sdk/src/orion_sdk/plugins/`

## Plugin 是什麼

Python package with `[project.entry-points."orion_sdk.plugins"]` block:

```toml
# my-plugin/pyproject.toml
[project]
name = "orion-jira-integration"

[project.entry-points."orion_sdk.plugins"]
jira = "orion_jira_integration:plugin_entry"
```

```python
# my_orion_plugin/__init__.py
from orion_sdk.plugins import PluginEntry, ToolDefinition

def plugin_entry() -> PluginEntry:
    return PluginEntry(
        name="jira",
        version="1.0.0",
        tools=[JiraSearchTool(), JiraCreateIssueTool()],
        system_prompt_block="When user mentions Jira, use jira__* tools.",
        hooks={"PreToolUse": [my_log_hook]},
    )
```

## 載入

SDK startup 時 `importlib.metadata.entry_points(group="orion_sdk.plugins")` 自動 discover + load all。
`ORION_PLUGINS_DIR=/path/to/plugins` env 可指定額外目錄(dev / sandbox)。

## 跟 Skills 的差別

| | Skill | Plugin |
|---|---|---|
| 形式 | Markdown | Python code |
| 能加 | system prompt fragment | tool + hook + prompt block |
| 安裝 | 拷貝 `.md` 進 `~/.orion/skills/` | `pip install` |
| 安全性 | 信任 prompt content(prompt injection 風險) | 完全信任 — Python code 想做什麼都行 |

要新 capability 寫 plugin;要改 LLM 行為寫 skill。

## 設計取捨

- **Entry points 不 path-based**:正規 Python 機制,user `pip install` 直接生效。比掃 `~/.orion/plugins/` 目錄優雅。
- **單一 namespace**:All plugins 用 `orion_sdk.plugins` group — 跨 plugin 衝突由 plugin 自己負責(tool name 加 prefix 避撞)

## 限制 / 已知問題

- **沒 sandbox**:plugin 是 Python code,可以做任何事(包括 `os.system`)。User 安裝前要看 source。
- **No semver enforcement**:plugin 不檢查跟 SDK 的版本兼容性(API 變化 plugin 可能 break)
- **跨 host UI 不一致**:plugin 加的 tool 在 CLI 直接可用;Cowork UI 要重啟 sidecar 才看見

## 未來方向

- **Plugin marketplace**:Cowork Settings → Plugins 瀏覽 + 一鍵安裝(走 PyPI 後台)
- **Capability declaration**:plugin 宣告需要哪些權限(網路 / 檔案系統 / 子 process),user 同意後才載入
- **Sandboxed plugins**:用 WASM 或 subprocess 隔離,limit blast radius

## 看完繼續

- [tools.md](./tools.md) — Tool 介面(plugin 寫 tool 要對齊)
- [skills.md](./skills.md) — 兩種擴充方式比較
- [hooks.md](./hooks.md) — Plugin 可注 hook

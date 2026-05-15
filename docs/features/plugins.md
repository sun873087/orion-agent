# Plugins

第三方寫 Python code 擴充 orion-agent — 加新 tool / 新 hook / 新 skill。

**實作位置**:`packages/orion-sdk/src/orion_sdk/plugins/`

## Plugin bundle 格式

```
~/.orion/plugins/<plugin-id>/
├── plugin.json         # 註冊內容(name, entry, version, ...)
├── <package>/          # Python module
│   ├── __init__.py
│   ├── tools/
│   └── hooks.py
└── skills/             # 可選:plugin 內附 skill
    └── <name>/SKILL.md
```

`plugin.json` 範例:

```json
{
  "id": "my-tool-pack",
  "name": "My tool pack",
  "version": "0.1.0",
  "entry": "my_plugin.entry:register",
  "permissions": ["read-files", "shell"]
}
```

`entry` 函式被 `PluginManager` 呼叫,plugin 用 SDK 暴露的 register API 加 tool / hook。

## 載入 layer(同 skills)

- `bundled` — 套件附 plugin(尚無)
- `~/.orion/plugins/` — admin
- `<cwd>/.orion/plugins/` — project
- `~/.orion/users/<uid>/plugins/` — user

## Plugin marketplace(未實作)

Web chat 場景需要 curated registry + 簽名驗證。設計見 [`../roadmap/plans/8c-plugin-marketplace.md`](../roadmap/plans/8c-plugin-marketplace.md)。

## 安全考量

Plugin 跑 Python code → 沒有 sandbox。**Plugin 應視為可信代碼**:

- CLI:user 自己安裝,自己負責
- Web chat:**禁止 user 上傳 plugin**,只允許 admin 預先安裝的 curated 列表

## 跟 MCP server 差異

| | MCP server | Plugin |
|---|---|---|
| 寫法 | 外部 process(任何語言) | 同 process Python module |
| 跨語言 | ✅ | ❌(Python only) |
| 性能 | RPC overhead | 直接呼叫 |
| 隔離 | 進程隔離 + permission | 同進程,完全信任 |
| 安裝 | `mcp.json` 設 transport | `plugin.json` + Python package |

新工具優先寫 MCP server(隔離 + 跨語言);只有需要深度 SDK 整合才走 plugin。

## 限制

- Plugin entry 拋例外會炸 orion(沒有 retry)
- 版本兼容性靠 plugin 自己 pin SDK 版本
- 沒有 hot reload(改 plugin 要重啟)

## 相關

- [hooks.md](./hooks.md) — plugin 通常會註冊 hooks
- [mcp.md](./mcp.md) — 跨語言擴充
- [skills.md](./skills.md) — 不寫 code 的擴充

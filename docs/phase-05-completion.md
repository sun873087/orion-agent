# Phase 5 — MCP Integration 完工記錄

**完成日期**:2026-05-07
**Spec doc**:`/Users/yuan-sencheng/Desktop/claude-code-source-main/docs/phases/05-mcp-integration.md`
**狀態**:✅ make check 全綠(274 tests),已備好 MCP CLI 接口(實際 server demo 須 npx 環境)

---

## 交付清單

```
src/orion_agent/mcp/                     [全新,9 檔]
├── __init__.py
├── config.py                  StdioMcpConfig + HttpMcpConfig + load_mcp_config(三路徑優先序)
├── transports.py              open_transport(stdio via mcp SDK;http stub)
├── client.py                  McpClient(async with → connect/list_tools/call_tool/cleanup)
├── manager.py                 McpManager(集中多 server lifecycle + 個別失敗隔離)
├── tool_wrapper.py            McpToolWrapper(JSON Schema → Pydantic + 命名 mcp__<srv>__<tool>)
├── schema_to_pydantic.py      動態建模(扁平 string/integer/number/boolean/array of string)
├── large_output.py            25K token 門檻 + 持久化(接 storage/mcp_output)
├── elicitation.py             stub(Phase 5b)
└── oauth.py                   stub(本機 OAuth 延後;web OAuth Phase 6/7)

修改既有檔(5 檔):
├── prompt/dynamic_sections.py        加 mcp_instructions_section
├── prompt/assembler.py               fetch_parts 接 mcp_manager
├── core/conversation.py              mcp_manager 欄位 + send() 合併 manager.tools
├── storage/mcp_output.py             從 stub 升成真實實作(persist / load / b64)
├── main.py                           --mcp-config / --no-mcp + AsyncExitStack 管理 manager
└── pyproject.toml                    加 mcp>=1.0
```

### Tests(全新,7 檔,40 案例)

```
tests/unit/mcp/
├── test_config.py                    7 tests(優先順序、合併、損壞 JSON、unknown type)
├── test_schema_to_pydantic.py        10 tests(基本型別、陣列、nested fallback、extra forbid)
├── test_tool_wrapper.py              8 tests(命名、annotations 推 safety、Tool Protocol、call 流程)
├── test_large_output.py              5 tests(threshold、寫檔、preview + jq hint、filename safe)
├── test_mcp_output_storage.py        5 tests(persist+load、meta sidecar、unknown type、sanitize)
└── test_manager.py                   4 tests(空 config、tools 載入、單 server 失敗不擋其他、summary)
```

---

## 驗證結果

| 檢查 | 結果 |
|---|---|
| `ruff check` | ✅ |
| `mypy --strict` | ✅(73 → 84 source files) |
| `pytest tests/unit/` | ✅ **274 passed**(234 → 274,+40) |

### CLI 介面已就緒

```bash
# 1. 寫 ~/.orion/mcp.json
cat > ~/.orion/mcp.json <<EOF
{
  "mcpServers": {
    "fs": {
      "type": "stdio",
      "command": "npx",
      "args": ["-y", "@modelcontextprotocol/server-filesystem", "/tmp"]
    }
  }
}
EOF

# 2. 跑 — 自動載入 mcp__fs__list_directory 等工具
make run-anthropic ARGS="List files in /tmp via the MCP filesystem server"

# 3. 暫時 disable
make run-anthropic ARGS="..." -- --no-mcp

# 4. 顯式指定 config
uv run orion --mcp-config /path/to/mcp.json "..."
```

### system prompt 含 `# MCP servers connected` 段

當有 server 連線成功,system prompt 動態段會列出:
```
# MCP servers connected

- **fs** (3 tools)

Tools from these servers are prefixed `mcp__<server>__<tool>`...
```

模型看見後會用 `mcp__fs__list_directory` 等工具。

---

## 與 spec doc 的差異

| 項目 | spec | 實作 | 為何 |
|---|---|---|---|
| 模組命名 | `claude_agent_py.mcp` | `orion_agent.mcp` | 沿用 Phase 0 |
| `mcp` SDK 是否用 | spec 用 | ✅ 用(thin protocol wrapper,非 agent framework)| 符合 user 規則 |
| stdio transport | ✅ | ✅(透過 mcp SDK 的 `stdio_client`) | 主流 |
| HTTP transport | spec 預期 | stub | mcp SDK 已支援 streamable_http,Phase 5 留 stub 待測 |
| SSE / InProcess | spec 範圍 | ❌ | Phase 5b — 罕用 |
| 本機 OAuth callback | spec 提及 | stub | 多數 MCP server(filesystem / git)不需 OAuth;真需要的 server(GitHub / Slack)在 web 模式更合理 |
| Server-side OAuth | spec 「web chat」段 | ❌ | Phase 6 / 7(需 FastAPI + secureStorage) |
| Elicitation(-32042)| spec 提 Phase 5b | stub | 罕用 |
| `_meta['anthropic/alwaysLoad']` | spec 提及 | ❌ | Phase 8 plugin/skill |
| Deferred MCP tool 動態載入 | spec 提及 | ❌ | 全載入即可,scope 外 |

---

## 實作中發現的細節 / 坑

### 1. `mcp` Python SDK 帶很多依賴

裝 `mcp>=1.0` 順帶引入 `starlette`、`uvicorn`、`sse-starlette`、`anyio`、`httpx-sse` 等。
~10 個 transitive deps。但每個都是 protocol 層必要,沒辦法瘦身。Phase 6 用 FastAPI 時這些
其實也派得上(starlette 是 FastAPI 底層)。

### 2. McpToolWrapper 不能用 `@dataclass`

Tool Protocol 要求 instance attributes(`name`, `description`, `input_schema`),且
`is_concurrency_safe(input)` 是 method。寫成 plain class 比 dataclass 自然。

### 3. is_concurrency_safe 邏輯:destructive 優先

順序重要:**先看 destructiveHint=True → unsafe**,再看 readOnlyHint=True → safe。
測試 `test_destructive_overrides_safe` 鎖住此行為(避免 reorder 後 silent regression)。

### 4. 動態 Pydantic model 的 `Optional` field

Pydantic v2 用 `field_type | None` 表達 optional:
```python
field_type = field_type | None  # str | None
default = None
```

mypy strict 對 `field_type` 變數型別歧義:可能是 `type` 或 `UnionType`。
**解法**:用 `field_type: Any` 標注,放棄精確型別追蹤(此處純動態)。

### 5. McpManager 的個別 server failure 隔離

`McpClient.__aenter__` 失敗不該炸整個 manager(其他 server 還能用)。
解法:`McpManager.__aenter__` 內 for 迴圈 try/except,失敗的記到 `connection_errors`,
成功的繼續加入 `_clients` / `_tools`。`AsyncExitStack` 只 register 成功的,cleanup 安全。

### 6. mcp.json 路徑優先順序

`load_mcp_config` 順序(後者覆蓋前者同 server name):
1. `~/.orion/mcp.json`(global)
2. `<cwd>/.orion/mcp.json`(per-project)
3. CLI `--mcp-config <path>`(顯式)

跟 Phase 4 instructions.md 對齊。

### 7. 大結果處理 — Phase 2 + Phase 5 兩層

- Phase 2 第 2 層(`storage/tool_result.py`):**所有**工具結果 ≥ 100KB byte 持久化
- Phase 5(`mcp/large_output.py`):MCP 結果走 25K *token* (~100KB chars),JSON 序列化保留 schema

兩者**獨立**:Phase 5 持久化的是「raw MCP result dict 的 JSON 形式」(供 jq 查 schema);
Phase 2 持久化的是「最終文字內容」。

---

## Phase 5 鋪好的基礎

| 後續 phase 將用到 | 使用情況 |
|---|---|
| Phase 6(FastAPI multi-user)| `oauth.py` 中 `start_web_oauth_flow` 接 secureStorage;`/mcp/oauth/start` API endpoint |
| Phase 7(production + Postgres)| `mcp_token:<user_id>:<server>` key 進 secureStorage |
| Phase 8(hooks / plugins)| `_meta['anthropic/alwaysLoad']` 整合 Skill 系統 |
| Phase 10(performance)| MCP 圖片自動壓縮、tool 結果 cache、ToolSearch deferred load |

## 衍生的新 phase plan

無 — Phase 5 觀察到的全部進範圍。

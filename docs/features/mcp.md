# MCP integration

orion-sdk 是 [Model Context Protocol](https://modelcontextprotocol.io) client — 連外部 MCP server,把 server 提供的 tools 動態 wrap 成 SDK `Tool` 介面塞進 agent。

**實作位置**:`packages/orion-sdk/src/orion_sdk/mcp/`

## 配置

`mcp.json` 兩個位置(先 user 後 project,後者覆蓋):

- `~/.orion/mcp.json` — 全使用者共用 server
- `<cwd>/.orion/mcp.json` — per-project

格式範例:

```json
{
  "mcpServers": {
    "filesystem": {
      "transport": "stdio",
      "command": "npx",
      "args": ["-y", "@modelcontextprotocol/server-filesystem", "/path"]
    },
    "github": {
      "transport": "sse",
      "url": "https://api.example.com/mcp",
      "oauth": {"client_id": "..."}
    }
  }
}
```

CLI 額外可 `--mcp-config <path>` 指定第三個位置,優先級最高。

## 支援的 4 種 transport

| Transport | 用途 |
|---|---|
| `stdio` | spawn 本機 process,stdin/stdout 通訊(常見) |
| `http` | streamable HTTP |
| `sse` | Server-Sent Events |
| `websocket` | WS bi-directional |

## 流程

1. `McpManager` 啟動 → 讀 `mcp.json` → 用 `async with` 並行 connect 所有 servers
2. 每個 server 回報自己有哪些 tools / resources / prompts
3. SDK 把每個 server tool wrap 成 `Tool` instance,name 帶 server prefix:`<server>:<tool>`(避免衝突)
4. agent run 時 wrap 後的 tool 跟內建工具混在 `Conversation.tools` 一起
5. Tool 被呼叫 → 透過 transport 送 request 到 server → result 包成 `ToolResultMessage` yield

`McpManager.connection_errors` 紀錄失敗的 server(不影響其他 server 正常工作)。

## OAuth(SSE / HTTP transport)

- Client 連 server 時若收到 401 + WWW-Authenticate → 觸發 OAuth flow
- 開瀏覽器到 server 的 authorize URL,callback 回本機 listener port
- Token 用 `keyring` 存 OS keychain(macOS Keychain / Windows Credential Manager / Linux secret service)
- WebUI 模式:OAuth 走 server-side flow(`apps/orion-chat/api/routes/oauth.py`)

## 為何 wrap 成 `Tool` 而非另立分類

設計選擇:agent 不該知道工具來源是 builtin、MCP server、還是 plugin。Tool Protocol 統一,permission policy、sandbox、event 流都一視同仁。

## 設定 server 範例

詳見 [mcp.json schema 範例](https://modelcontextprotocol.io/quickstart)。常見:

```json
{
  "mcpServers": {
    "git": {
      "transport": "stdio",
      "command": "uvx",
      "args": ["mcp-server-git"]
    },
    "puppeteer": {
      "transport": "stdio",
      "command": "npx",
      "args": ["-y", "@modelcontextprotocol/server-puppeteer"]
    }
  }
}
```

## 限制

- Server 啟動失敗只 log,不 retry(可重啟程序)
- Stdio server 死掉沒自動重啟 — 後續 phase 加 supervisor
- Tool name 衝突走 prefix,但 LLM 看到的工具列表多了會 burn tokens

## 相關

- [tools.md](./tools.md) — Tool Protocol
- [`../architecture/design-decisions.md`](../architecture/design-decisions.md) — 為何用 MCP 而非自訂 plugin protocol

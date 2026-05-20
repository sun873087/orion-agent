# MCP integration

orion-sdk 是 [Model Context Protocol](https://modelcontextprotocol.io) client — 連外部
MCP server,把 server 提供的 tools 動態 wrap 成 SDK `Tool` 介面塞進 agent。

**實作位置**:`packages/orion-sdk/src/orion_sdk/mcp/`

## 4 種 transport

| Transport | 用途 |
|---|---|
| **stdio** | 跑 subprocess,經 stdin/stdout JSON-RPC(MCP 預設)|
| **SSE** | HTTP Server-Sent Events(MCP 過渡用)|
| **streamable HTTP** | MCP 新標準(替代 SSE)|
| **WebSocket** | 雙向 stream(較少用,但有 server 用)|

OAuth 支援:transport 是 SSE / streamable / WS 時可走 OAuth 流程(MCP 2025-06 spec)— 認證 cache 存 keychain。

## 設定

`~/.orion/mcp.json`:

```json
{
  "mcpServers": {
    "github": {
      "type": "stdio",
      "command": "npx",
      "args": ["-y", "@modelcontextprotocol/server-github"],
      "env": { "GITHUB_PERSONAL_ACCESS_TOKEN": "ghp_..." }
    },
    "linear": {
      "type": "streamable",
      "url": "https://mcp.linear.app/sse",
      "headers": { "Authorization": "Bearer ${LINEAR_TOKEN}" }
    },
    "fs-custom": {
      "type": "stdio",
      "command": "python",
      "args": ["-m", "my_mcp_server"],
      "cwd": "/path/to/server"
    }
  }
}
```

`${ENV_VAR}` 自動展開。

## Tool 命名

MCP server 註冊到 SDK 後,tool name 帶 prefix:`mcp__<server>__<tool>`。例:

- `mcp__github__create_pull_request`
- `mcp__linear__create_issue`

LLM 看到的是這個帶 prefix 的 name,工具是 MCP server 提供的 schema。

## Lifecycle

```
SDK start
    ▼
MCP manager 連所有 servers(parallel)
    ├─ stdio:spawn subprocess
    ├─ SSE/HTTP/WS:open connection + handshake
    │
    ▼
List tools(每 server `tools/list`)→ wrap into SDK Tool spec
    ▼
Inject tool list 進 system prompt(LLM 看到 mcp__<server>__<tool>)
    ▼
LLM call mcp__... → SDK route 到對應 server → relay arg → server response → relay back

SDK shutdown
    ▼
Close all server connections
```

## OAuth flow

對 SSE / streamable / WS server,首次連用 OAuth 2.1 + PKCE:

1. SDK 收 server `WWW-Authenticate: Bearer` challenge
2. Open browser → user 認證 → callback to local port
3. Token 存 keychain(`mcp:<server>` key)
4. 後續 request 帶 access_token

`mcp.json` 不放 OAuth token,只放 server URL。

## 設計取捨

- **Per-server lifecycle**:一個 server 掛掉不影響其他(parallel connect + per-server retry)
- **Tool prefix `mcp__<server>__`**:user 可以一眼分 SDK builtin 跟 MCP 外掛
- **Schema 信任 server**:MCP server 給的 JSON Schema 直接 forward 給 LLM,不重 validate(否則跨 server 維護累)

## 限制 / 已知問題

- **stdio subprocess 多 → 啟動慢**:cold start 5 個 server 約 3-5s
- **MCP server crash 不自動 restart**:目前 retry 一次,fail 後該 server 的 tools 全 dropped
- **No tool versioning**:server 升級改 schema,跨 session transcript replay 會 fail

## 未來方向

- **Tool sampling**:LLM 想 server 跑時才連(lazy),不必 startup 全連
- **MCP server marketplace**:Cowork Settings 內瀏覽 / 一鍵安裝 official servers
- **Multi-server tool conflict**:兩 server 提供同名 tool → 目前 last-wins,要 explicit conflict resolution
- **Supervisor resume**:server crash 自動 spawn + recover state

## 看完繼續

- [`../architecture/runtime-layout.md`](../architecture/runtime-layout.md) — `~/.orion/mcp.json` 位置
- [tools.md](./tools.md) — Tool 介面(MCP tools wrap into 同介面)
- [skills.md](./skills.md) — Skill / MCP 都擴 agent 能力,差別?

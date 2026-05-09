# Phase 5:MCP Integration(MCP 整合)

## 速覽

- **預計時程**:2-3 週
- **前置 Phase**:Phase 1(Tool 介面)+ Phase 4(`mcp_instructions` system prompt section)
- **後續 Phase**:Phase 8(hook)— skill 與 MCP 整合;Phase 9(telemetry)— MCP latency 追蹤
- **主要交付物**:
  - 整合 mcp Python SDK
  - 4 種 transport(stdio / SSE / StreamableHTTP / InProcess)
  - 動態 tool 包裝(讀 `annotations.readOnlyHint`)
  - MCP OAuth flow + callback port
  - Elicitation handler(server 反問 user)

## ⚠️ Web Chat 場景調整(產品 curated MCP + server-side OAuth)

> **TS 原設計**(CLI per-user):每個 user 在 `settings.json` / `.mcp.json` 自己設 MCP server 名單,OAuth flow 開本機瀏覽器 + localhost callback port。
>
> **Web chat 改為**:
> - **產品決定接哪些 MCP server**(GitHub / Slack / Notion 等),user 不直接配置
> - **Server-side OAuth flow**:user 從 web app 點「Connect GitHub」→ 跳到 GitHub OAuth → callback 到你的 `https://api.example.com/oauth/callback` → token 加密存(用 [Phase 14 secureStorage](./14-distribution-sync.md))
> - 本 phase 的 `mcp/oauth.py` callback port 邏輯**改寫**為 web OAuth(下方 § 5.5b)
> - 進階:user 自己接 MCP server(per-user MCP)留給 v2,初期不做
>
> Phase 5 大多數內容(transports / tool wrapping / 大結果處理)**不變**。

## 1. 目標與動機

Phase 1-4 的工具都是內建寫死。Phase 5 加上**動態接外部 MCP server**,讓使用者可以自帶工具:

```
無 MCP:只能用 10 個內建工具
有 MCP:接 Slack / GitHub / Linear / Filesystem / 任何第三方 MCP server
        → 動態載入幾百個工具
```

**對應 docs**:
- [docs/04 §4c](../04-cloud-integration.md) MCP Client(4 transport 對比)
- [docs/10 §3](../10-tool-concurrency.md) MCP 工具的並發策略(`readOnlyHint`)
- [docs/11 §9](../11-tools-catalog.md) MCP 工具動態載入

完成本 phase 後,你的 agent 變得**真正可擴展** — 任何符合 MCP 協議的 server 都能接。

## 2. TS 源檔映射

| Python 模組 | 對應 TS 源檔 | 行數 | 注意事項 |
|---|---|---|---|
| `src/mcp/client.py` | `src/services/mcp/client.ts` | 大 | 主 client,含 transformMCPResult、processMCPResult |
| `src/mcp/transports/stdio.py` | `src/services/mcp/transports/` | — | spawn 子程序 |
| `src/mcp/transports/sse.py` | 同上 | — | Server-Sent Events |
| `src/mcp/transports/http.py` | 同上 | — | StreamableHTTP |
| `src/mcp/transports/inprocess.py` | 同上 | — | 同行程 in-memory |
| `src/mcp/config.py` | `src/services/mcp/config.ts` | — | 從 settings 讀 server 列表 |
| `src/mcp/oauth.py` | `src/services/mcp/oauth/` | — | OAuth callback port |
| `src/mcp/elicitation.py` | `src/services/mcp/elicitation/` | — | server 反問 user(-32042) |
| `src/mcp/tool_wrapper.py` | `src/services/mcp/client.ts:1768` | — | 動態包裝成 Tool 介面 |
| `src/mcp/large_output.py` | `src/utils/mcpValidation.ts` + `mcpOutputStorage.ts` | — | 第 1 層大結果處理(對應 docs/09) |

## 3. 任務拆解

### Week 1:基礎 + stdio transport

- [ ] 1.1 加入依賴:`mcp` Python SDK(官方)
- [ ] 1.2 `mcp/config.py`:從 settings.json / `.mcp.json` 讀 server 列表
- [ ] 1.3 `mcp/client.py`:`MCPClient` class 骨架
- [ ] 1.4 `mcp/transports/stdio.py`:用 `asyncio.create_subprocess_exec` spawn
- [ ] 1.5 `list_tools` / `list_resources` / `list_prompts` 整合
- [ ] 1.6 測試:接一個 minimal MCP server(echo tool)

### Week 2:Tool 包裝 + 大結果處理 + 其他 transport

- [ ] 2.1 `mcp/tool_wrapper.py`:`wrap_mcp_tool` 把 MCP tool 包成 `Tool` Protocol
- [ ] 2.2 `is_concurrency_safe = annotations.readOnlyHint`(對應 docs/10 §3)
- [ ] 2.3 `mcp/large_output.py`:第 1 層大結果處理(`processMCPResult`)
- [ ] 2.4 `getLargeOutputInstructions` + schema 推導(`inferCompactSchema`)
- [ ] 2.5 `mcp/transports/sse.py` 與 `http.py` 與 `inprocess.py`(基於 mcp SDK)
- [ ] 2.6 整合到 Phase 1 的 Tools registry(動態注入)

### Week 3:OAuth + Elicitation + 收尾

- [ ] 3.1 `mcp/oauth.py`:本機 callback port 監聽 + 開瀏覽器
- [ ] 3.2 token refresh + 過期處理
- [ ] 3.3 `mcp/elicitation.py`:處理 -32042 error(URL 反問)
- [ ] 3.4 整合到 Phase 4 的 system prompt:`mcp_instructions` 動態 section(`DANGEROUS_uncached`)
- [ ] 3.5 整合測試:接一個真實 MCP server(filesystem 或 fetch)
- [ ] 3.6 寫 Phase 5 心得

## 4. 模組架構與檔案

```
src/claude_agent_py/
├── mcp/
│   ├── __init__.py
│   ├── client.py                      # ◀ NEW MCPClient
│   ├── config.py                      # ◀ NEW server 設定載入
│   ├── tool_wrapper.py                # ◀ NEW 動態包裝
│   ├── large_output.py                # ◀ NEW 第 1 層持久化
│   ├── oauth.py                       # ◀ NEW callback port
│   ├── elicitation.py                 # ◀ NEW URL 反問
│   └── transports/
│       ├── __init__.py
│       ├── stdio.py
│       ├── sse.py
│       ├── http.py
│       └── inprocess.py
│
└── prompt/
    └── system_prompt.py               # ◀ 擴充:加 mcp_instructions section
```

## 5. Python Skeleton

### 5.1 `mcp/config.py`

```python
"""MCP server 設定載入。對應 TS services/mcp/config.ts。"""
from __future__ import annotations
from dataclasses import dataclass
from pathlib import Path
from typing import Literal
import json


@dataclass
class StdioServerConfig:
    name: str
    command: str
    args: list[str] = None
    env: dict[str, str] = None
    type: Literal["stdio"] = "stdio"


@dataclass
class HttpServerConfig:
    name: str
    url: str
    headers: dict[str, str] = None
    type: Literal["sse", "http"] = "http"


@dataclass
class InProcessServerConfig:
    name: str
    handler_module: str  # e.g. "claude_agent_py.builtin_mcp.foo"
    type: Literal["inprocess"] = "inprocess"


ServerConfig = StdioServerConfig | HttpServerConfig | InProcessServerConfig


def load_mcp_config(path: Path) -> list[ServerConfig]:
    """從 .mcp.json / settings.json 讀 server 列表。"""
    if not path.exists():
        return []

    data = json.loads(path.read_text())
    servers = data.get("mcpServers", {})
    result = []
    for name, conf in servers.items():
        t = conf.get("type", "stdio")
        if t == "stdio":
            result.append(StdioServerConfig(
                name=name,
                command=conf["command"],
                args=conf.get("args", []),
                env=conf.get("env", {}),
            ))
        elif t in ("sse", "http"):
            result.append(HttpServerConfig(
                name=name, url=conf["url"],
                headers=conf.get("headers", {}), type=t,
            ))
        elif t == "inprocess":
            result.append(InProcessServerConfig(
                name=name, handler_module=conf["handler_module"],
            ))
    return result
```

### 5.2 `mcp/client.py`

```python
"""MCPClient — 主整合層。對應 TS services/mcp/client.ts。"""
from __future__ import annotations
from dataclasses import dataclass
from typing import Any

from mcp import ClientSession, StdioServerParameters
from mcp.client.stdio import stdio_client

from claude_agent_py.mcp.config import ServerConfig, StdioServerConfig
from claude_agent_py.core.tool import Tool
from claude_agent_py.mcp.tool_wrapper import wrap_mcp_tool


@dataclass
class ConnectedMCPServer:
    name: str
    session: ClientSession
    tools: list[dict]  # 從 list_tools 取得的原始定義
    instructions: str | None
    config: ServerConfig


class MCPClient:
    """整合 mcp Python SDK,管理多個 server 連線。"""

    def __init__(self):
        self.connected: dict[str, ConnectedMCPServer] = {}

    async def connect(self, config: ServerConfig) -> ConnectedMCPServer:
        """連線並列舉 tools/resources/prompts。"""
        if isinstance(config, StdioServerConfig):
            session = await self._connect_stdio(config)
        else:
            raise NotImplementedError(f"transport {config.type} not implemented yet")

        # 列舉
        tools_response = await session.list_tools()
        tools = [t.model_dump() for t in tools_response.tools]

        # MCP server 可選提供 instructions
        instructions = getattr(session, "instructions", None)

        connected = ConnectedMCPServer(
            name=config.name,
            session=session,
            tools=tools,
            instructions=instructions,
            config=config,
        )
        self.connected[config.name] = connected
        return connected

    async def _connect_stdio(self, config: StdioServerConfig) -> ClientSession:
        """spawn 子程序作為 MCP server。"""
        params = StdioServerParameters(
            command=config.command,
            args=config.args or [],
            env=config.env or None,
        )
        # 用 mcp SDK 的 stdio_client
        # 注意:實作上要管理 lifecycle(關閉子程序)
        ...

    def all_tools(self) -> list[Tool]:
        """把所有連線 server 的 tools 包成 Tool 介面。"""
        result = []
        for server in self.connected.values():
            for tool_def in server.tools:
                wrapped = wrap_mcp_tool(server, tool_def)
                result.append(wrapped)
        return result

    async def close_all(self) -> None:
        """關所有連線。"""
        for server in self.connected.values():
            try:
                await server.session.close()
            except Exception:
                pass
        self.connected.clear()
```

### 5.3 `mcp/tool_wrapper.py`(關鍵:讀 annotations)

```python
"""把 MCP tool 包成 Claude Agent Tool 介面。

對應 TS services/mcp/client.ts:1768。

關鍵:isConcurrencySafe = tool.annotations.readOnlyHint ?? False
       isReadOnly       = 同上
       isDestructive    = tool.annotations.destructiveHint ?? False
"""
from __future__ import annotations
from typing import AsyncIterator
from pydantic import BaseModel, create_model

from claude_agent_py.core.tool import Tool, ToolInput, ToolEvent, TextEvent, ErrorEvent
from claude_agent_py.core.state import AgentContext


def build_mcp_tool_name(server_name: str, tool_name: str) -> str:
    """模型看到的名稱:mcp__<server>__<tool>。"""
    sanitized = server_name.replace("-", "_")
    return f"mcp__{sanitized}__{tool_name}"


def wrap_mcp_tool(server, tool_def: dict) -> Tool:
    """動態建立 Tool wrapper。"""

    full_name = build_mcp_tool_name(server.name, tool_def["name"])
    annotations = tool_def.get("annotations") or {}

    # 從 inputSchema 動態建 Pydantic model
    # 簡單做法:用 dict 對應 → Pydantic 動態建構
    input_schema_dict = tool_def.get("inputSchema", {"type": "object"})
    DynamicInput = _build_dynamic_input(tool_def["name"], input_schema_dict)

    class WrappedTool:
        name = full_name
        description = tool_def.get("description", "")
        input_schema = DynamicInput

        # 對應 docs/10 §3 的關鍵設計:
        def is_concurrency_safe(self, input: BaseModel) -> bool:
            return annotations.get("readOnlyHint", False)

        def is_read_only(self, input: BaseModel) -> bool:
            return annotations.get("readOnlyHint", False)

        def is_destructive(self, input: BaseModel) -> bool:
            return annotations.get("destructiveHint", False)

        def is_open_world(self, input: BaseModel) -> bool:
            return annotations.get("openWorldHint", False)

        async def call(
            self,
            input: BaseModel,
            ctx: AgentContext,
        ) -> AsyncIterator[ToolEvent]:
            from claude_agent_py.mcp.large_output import process_mcp_result

            try:
                # 透過 mcp SDK 呼叫
                result = await server.session.call_tool(
                    name=tool_def["name"],
                    arguments=input.model_dump(),
                )
            except Exception as e:
                yield ErrorEvent(message=f"MCP error: {e}")
                return

            # 大結果處理(第 1 層,對應 docs/09)
            processed = await process_mcp_result(
                result, tool=tool_def["name"], server=server.name, ctx=ctx,
            )
            yield TextEvent(text=str(processed))

    return WrappedTool()


def _build_dynamic_input(tool_name: str, schema: dict) -> type[BaseModel]:
    """從 JSON Schema 動態建 Pydantic model。

    簡化版:只處理 type=object + properties。
    """
    # 實際做法用 pydantic.create_model
    # 或更穩的方式:用 datamodel-code-generator
    properties = schema.get("properties", {})
    required = set(schema.get("required", []))

    fields = {}
    for prop_name, prop_schema in properties.items():
        prop_type = _json_type_to_python(prop_schema.get("type", "string"))
        default = ... if prop_name in required else None
        fields[prop_name] = (prop_type, default)

    return create_model(f"{tool_name}Input", **fields)


def _json_type_to_python(t: str) -> type:
    return {
        "string": str,
        "number": float,
        "integer": int,
        "boolean": bool,
        "array": list,
        "object": dict,
    }.get(t, str)
```

### 5.4 `mcp/large_output.py`(對應 docs/09 第 1 層)

```python
"""MCP 大結果處理。對應 TS utils/mcpValidation.ts + mcpOutputStorage.ts。

第 1 層:25K tokens 門檻 → 寫檔 + 給模型詳細讀檔指引(含 schema 推導 + jq 範例)。
"""
from __future__ import annotations
import os
import json
from pathlib import Path
from typing import Any

from claude_agent_py.storage.paths import get_tool_results_dir


DEFAULT_MAX_MCP_OUTPUT_TOKENS = 25_000
BYTES_PER_TOKEN = 4
DEFAULT_MAX_MCP_OUTPUT_BYTES = DEFAULT_MAX_MCP_OUTPUT_TOKENS * BYTES_PER_TOKEN


def get_max_mcp_output_tokens() -> int:
    """對應 TS getMaxMcpOutputTokens。env > 預設。"""
    env = os.environ.get("MAX_MCP_OUTPUT_TOKENS")
    if env:
        try:
            return int(env)
        except ValueError:
            pass
    return DEFAULT_MAX_MCP_OUTPUT_TOKENS


def estimate_size(content: Any) -> int:
    """rough 估算 token 數。"""
    if isinstance(content, str):
        return len(content) // BYTES_PER_TOKEN
    return len(json.dumps(content)) // BYTES_PER_TOKEN


def infer_compact_schema(value: Any, depth: int = 2) -> str:
    """從值推 type signature(供 jq 用)。對應 TS inferCompactSchema。

    例:{title: string, items: [{id: number, name: string}]}
    """
    if value is None:
        return "null"
    if isinstance(value, list):
        if not value:
            return "[]"
        return f"[{infer_compact_schema(value[0], depth - 1)}]"
    if isinstance(value, dict):
        if depth <= 0:
            return "{...}"
        entries = list(value.items())[:10]
        props = [f"{k}: {infer_compact_schema(v, depth - 1)}" for k, v in entries]
        suffix = ", ..." if len(value) > 10 else ""
        return "{" + ", ".join(props) + suffix + "}"
    return type(value).__name__


def get_large_output_instructions(
    filepath: Path,
    content_length: int,
    schema: str,
) -> str:
    """強制指引模型分塊讀。對應 TS getLargeOutputInstructions。"""
    return f"""Error: result ({content_length:,} characters) exceeds maximum allowed tokens.
Output has been saved to {filepath}
Format: JSON with schema: {schema}
Use offset and limit parameters to read specific portions of the file,
search within it for specific content, and jq to make structured queries.

REQUIREMENTS FOR SUMMARIZATION/ANALYSIS/REVIEW:
- You MUST read the content from the file at {filepath} in sequential chunks
  until 100% of the content has been read.
- Before producing ANY summary or analysis, you MUST explicitly describe what
  portion of the content you have read.
- ***If you did not read the entire content, you MUST explicitly state this.***
"""


async def process_mcp_result(
    result: Any,
    *,
    tool: str,
    server: str,
    ctx,
) -> str | Any:
    """第 1 層處理。對應 TS processMCPResult。"""
    # 提取 content
    if hasattr(result, "content"):
        content = result.content
    elif isinstance(result, dict):
        content = result.get("content", result)
    else:
        content = result

    # IDE server 不送模型
    if server == "ide":
        return content

    size_est = estimate_size(content)
    max_tokens = get_max_mcp_output_tokens()
    if size_est <= max_tokens:
        return content  # 小,直接返

    # env 強制截斷模式
    if os.environ.get("ENABLE_MCP_LARGE_OUTPUT_FILES") == "false":
        return _truncate_text(content, max_tokens * BYTES_PER_TOKEN)

    # 含圖片:走截斷不持久化
    if _contains_images(content):
        return _truncate_text(content, max_tokens * BYTES_PER_TOKEN)

    # 主路徑:寫檔 + 給指引
    timestamp = int(__import__("time").time() * 1000)
    persist_id = f"mcp-{server}-{tool}-{timestamp}"
    content_str = (
        json.dumps(content, ensure_ascii=False, indent=2)
        if not isinstance(content, str) else content
    )
    filepath = get_tool_results_dir(ctx.session_id) / f"{persist_id}.json"
    filepath.write_text(content_str, encoding="utf-8")

    schema = infer_compact_schema(content)
    return get_large_output_instructions(filepath, len(content_str), schema)


def _contains_images(content: Any) -> bool:
    if not isinstance(content, list):
        return False
    return any(
        isinstance(b, dict) and b.get("type") == "image" for b in content
    )


def _truncate_text(content: Any, max_chars: int) -> str:
    s = content if isinstance(content, str) else json.dumps(content)
    if len(s) <= max_chars:
        return s
    warning = (
        f"\n\n[OUTPUT TRUNCATED - exceeded {get_max_mcp_output_tokens()} token limit]\n"
        f"If this MCP server provides pagination, use it to retrieve specific portions."
    )
    return s[:max_chars] + warning
```

### 5.5 `mcp/oauth.py`(本機 dev / CLI 模式 — web chat 用 § 5.5b)

```python
"""MCP OAuth flow(本機 dev only)。對應 TS services/mcp/oauth/。

⚠️ Web chat production 不用本檔,改用 § 5.5b 的 server-side flow。

關鍵:本機開個 callback port,瀏覽器跳轉登入後 redirect 回 localhost。
"""
from __future__ import annotations
import asyncio
import webbrowser
from contextlib import asynccontextmanager
from aiohttp import web


class CallbackServer:
    """簡易本機 OAuth callback 監聽器。"""

    def __init__(self, port: int = 0):
        self.port = port
        self.received_code: str | None = None
        self.received_state: str | None = None
        self._done = asyncio.Event()

    async def handle_callback(self, request: web.Request) -> web.Response:
        self.received_code = request.query.get("code")
        self.received_state = request.query.get("state")
        self._done.set()
        return web.Response(text="Authentication complete. You may close this window.")

    @asynccontextmanager
    async def run(self):
        app = web.Application()
        app.router.add_get("/callback", self.handle_callback)
        runner = web.AppRunner(app)
        await runner.setup()
        site = web.TCPSite(runner, "localhost", self.port)
        await site.start()
        self.port = site._server.sockets[0].getsockname()[1]  # 動態 port
        try:
            yield self
        finally:
            await runner.cleanup()


async def perform_oauth(authorize_url: str, expected_state: str) -> str:
    """跑完整 OAuth flow,返回 authorization code。"""
    callback = CallbackServer()
    async with callback.run():
        full_url = f"{authorize_url}&redirect_uri=http://localhost:{callback.port}/callback"
        webbrowser.open(full_url)

        try:
            await asyncio.wait_for(callback._done.wait(), timeout=300)
        except asyncio.TimeoutError:
            raise TimeoutError("OAuth flow timeout")

        if callback.received_state != expected_state:
            raise ValueError("OAuth state mismatch")
        return callback.received_code or ""
```

### 5.5b `mcp/oauth_web.py`(Web chat / SaaS 模式 — 推薦)

```python
"""Server-side OAuth flow for web chat。

流程:
  1. User 在 web app 點「Connect GitHub」
  2. 前端打 POST /mcp/oauth/start { server: 'github' }
  3. 後端產 state(隨機 + user_id 簽名),return authorize_url
  4. 前端跳轉到 authorize_url(GitHub 登入頁)
  5. GitHub redirect 到 https://api.example.com/oauth/callback?code=...&state=...
  6. 後端驗 state、用 code 換 token、加密存(SecureStorage,Phase 14)
  7. 後端回 close-window page,前端 polling 確認連線完成

不需要 localhost callback port。
"""
from __future__ import annotations
import secrets
import hmac
import hashlib
import os
from datetime import datetime, timedelta

from fastapi import APIRouter, Depends, HTTPException, Request
from fastapi.responses import RedirectResponse, HTMLResponse

from claude_agent_py.api.deps import current_user
from claude_agent_py.storage.secure import create_backend


router = APIRouter()
SECRET_KEY = os.environ.get("OAUTH_STATE_SECRET", "change-me").encode()


def _sign_state(user_id: str, server: str) -> str:
    """產含 user_id + server 的簽名 state。"""
    nonce = secrets.token_urlsafe(16)
    timestamp = str(int(datetime.utcnow().timestamp()))
    payload = f"{user_id}:{server}:{nonce}:{timestamp}"
    sig = hmac.new(SECRET_KEY, payload.encode(), hashlib.sha256).hexdigest()
    return f"{payload}:{sig}"


def _verify_state(state: str) -> tuple[str, str] | None:
    """驗證 state,回傳 (user_id, server) 或 None。"""
    try:
        parts = state.split(":")
        if len(parts) != 5:
            return None
        user_id, server, nonce, timestamp, sig = parts
        payload = f"{user_id}:{server}:{nonce}:{timestamp}"
        expected = hmac.new(SECRET_KEY, payload.encode(), hashlib.sha256).hexdigest()
        if not hmac.compare_digest(sig, expected):
            return None
        # 檢查 timestamp 5 分鐘內
        if datetime.utcnow().timestamp() - int(timestamp) > 300:
            return None
        return user_id, server
    except Exception:
        return None


# 各 MCP server 的 OAuth config(產品 curated)
MCP_OAUTH_CONFIG = {
    "github": {
        "authorize_url": "https://github.com/login/oauth/authorize",
        "token_url": "https://github.com/login/oauth/access_token",
        "client_id": os.environ.get("GITHUB_CLIENT_ID"),
        "client_secret": os.environ.get("GITHUB_CLIENT_SECRET"),
        "scopes": ["repo", "read:user"],
    },
    "slack": {
        "authorize_url": "https://slack.com/oauth/v2/authorize",
        # ...
    },
}


@router.post("/oauth/start")
async def oauth_start(server: str, user=Depends(current_user)):
    """前端打這裡開始 OAuth。"""
    config = MCP_OAUTH_CONFIG.get(server)
    if not config:
        raise HTTPException(404, "MCP server not supported")

    state = _sign_state(user.id, server)
    redirect_uri = f"https://api.example.com/oauth/callback"
    authorize_url = (
        f"{config['authorize_url']}"
        f"?client_id={config['client_id']}"
        f"&redirect_uri={redirect_uri}"
        f"&state={state}"
        f"&scope={'+'.join(config['scopes'])}"
    )
    return {"authorize_url": authorize_url}


@router.get("/oauth/callback")
async def oauth_callback(code: str, state: str, request: Request):
    """OAuth provider redirect 回這裡。"""
    verified = _verify_state(state)
    if verified is None:
        raise HTTPException(400, "Invalid OAuth state")
    user_id, server = verified

    config = MCP_OAUTH_CONFIG[server]

    # 用 code 換 token
    import httpx
    async with httpx.AsyncClient() as client:
        response = await client.post(
            config["token_url"],
            data={
                "client_id": config["client_id"],
                "client_secret": config["client_secret"],
                "code": code,
                "redirect_uri": "https://api.example.com/oauth/callback",
            },
            headers={"Accept": "application/json"},
        )
        token_data = response.json()

    access_token = token_data.get("access_token")
    if not access_token:
        raise HTTPException(400, "Failed to get token")

    # 加密存(用 Phase 14 secureStorage)
    secure = create_backend()
    await secure.set(f"mcp_token:{user_id}:{server}", access_token)

    # 回 close-window 頁面
    return HTMLResponse("""
        <html><body>
        <script>window.close();</script>
        Connection complete. You can close this window.
        </body></html>
    """)


@router.get("/oauth/status/{server}")
async def oauth_status(server: str, user=Depends(current_user)):
    """前端 polling 確認連線狀態。"""
    secure = create_backend()
    token = await secure.get(f"mcp_token:{user.id}:{server}")
    return {"connected": token is not None}


# 整合到 MCP client(connect 時讀 token)
async def get_user_mcp_token(user_id: str, server: str) -> str | None:
    secure = create_backend()
    return await secure.get(f"mcp_token:{user_id}:{server}")
```

### 5.6 整合到 system prompt

```python
# prompt/system_prompt.py 擴充:加 mcp_instructions section

from claude_agent_py.prompt.sections import DANGEROUS_uncached_system_prompt_section


def get_mcp_instructions_section(mcp_clients) -> str | None:
    """收集所有 server 的 instructions。"""
    if not mcp_clients:
        return None
    parts = []
    for server in mcp_clients:
        if server.instructions:
            parts.append(f"## {server.name}\n{server.instructions}")
    if not parts:
        return None
    return "# MCP Server Instructions\n\n" + "\n\n".join(parts)


# 加到 dynamic_sections 列表:
DANGEROUS_uncached_system_prompt_section(
    "mcp_instructions",
    lambda: get_mcp_instructions_section(mcp_clients),
    reason="MCP servers connect/disconnect between turns",
)
```

## 6. 設計決策與取捨

### 為何先做 stdio,後做其他 transport?

stdio 是 MCP 最常見、最簡單的:大多數 MCP server 都是本機子程序。實作 stdio 跑通後,其他 transport 換 client class 即可。

### 為何不自己實作 MCP 協議?

直接用 [mcp](https://github.com/modelcontextprotocol/python-sdk) 官方 Python SDK。已經實作:
- 訊息格式 + JSON-RPC
- Initialize handshake
- 工具/資源/prompt 列舉與呼叫
- 錯誤處理

省一兩個月。

### 為何 OAuth 用本機 port?

MCP server 的 OAuth flow 需要 redirect URI。Claude Code 是 CLI,不能用 https://your.app/callback,只能本機 `http://localhost:<port>/callback`。

Phase 7 SaaS 化時改成 web 端 OAuth flow(server 端 redirect)。

### 為何 large output 處理放 MCP 而非通用?

對應 docs/09 §3:MCP 來源不可控、結構化(JSON),需要更嚴閾值(25K vs 100K 通用)+ 更詳細指引(schema、jq、強制分塊)。Phase 5 的 `process_mcp_result` 是第 1 層,Phase 2 的通用持久化是第 2 層,兩者都生效。

### 為何 elicitation 處理 -32042?

MCP server 可能要求 user 開瀏覽器完成某個動作(例:授權、設定)。`-32042` 是 MCP 標準 error code,client 收到後要顯示 URL 給 user,等 user 完成後 retry。

Phase 5 簡化版直接 raise,讓 caller 顯示;完整版 Phase 8 整合 hook。

### Phase 5 故意不做的

| 項目 | 留給哪個 phase |
|---|---|
| `_meta['anthropic/alwaysLoad']` 細節 | Phase 8 plugin/skill 整合時處理 |
| Deferred MCP tool(ToolSearch 動態載入)| 不做,直接全載入 |
| MCP 圖片自動壓縮 | Phase 10 |
| In-process MCP 自寫 server | 範例放最後做即可 |

## 7. 驗收標準

### 自動測試

```bash
pytest tests/mcp/ -v
```

關鍵測試:

- `test_config_load.py`:正確解析三種 transport 的 config
- `test_tool_wrapper.py`:`isConcurrencySafe = readOnlyHint`(各種 annotation 組合)
- `test_dynamic_input_schema.py`:JSON Schema → Pydantic model 轉換正確
- `test_process_mcp_result.py`:小結果通過、大結果寫檔、含圖片走截斷、env disable fallback 截斷
- `test_infer_compact_schema.py`:各種 nested 結構推 schema 正確
- `test_callback_server.py`:OAuth callback 收 code + state 驗證

### 手動驗證

接一個官方 reference MCP server(filesystem):

```bash
# 安裝官方 fs server
npm install -g @modelcontextprotocol/server-filesystem

# 設定 .mcp.json
cat > .mcp.json <<EOF
{
  "mcpServers": {
    "fs": {
      "command": "npx",
      "args": ["-y", "@modelcontextprotocol/server-filesystem", "/tmp"]
    }
  }
}
EOF

python -m claude_agent_py
> "List files in /tmp using the fs server"
```

預期:
- 連線成功
- 模型看到 `mcp__fs__list_directory` 等工具
- 呼叫成功,結果回傳

### 整合驗證

接 2 個 MCP server,並發呼叫多個 read-only MCP 工具,觀察:
- 兩個並發跑(若 readOnlyHint=true)
- system prompt 含 mcp_instructions section
- 大結果寫到 tool-results/mcp-<server>-<tool>-*.json

## 8. 常見踩雷

### 踩雷 1:mcp Python SDK 版本

mcp SDK API 在快速演進,API 不穩定。釘版本:`mcp>=1.0.0` 後檢查 changelog。

### 踩雷 2:子程序沒清乾淨

stdio transport spawn 子程序,程式結束時要 kill。用 `asyncio.create_subprocess_exec` + `try/finally`:

```python
async with stdio_client(params) as (read, write):
    # ...
# 退出時 mcp SDK 會自動清,但實際還是要驗證
```

### 踩雷 3:JSON Schema → Pydantic 動態建構複雜

簡單情境(扁平 properties)易;含 `oneOf` / `$ref` / nested objects 麻煩。建議:

- Phase 5 只支援扁平 type=object
- 進階用 [`datamodel-code-generator`](https://docs.pydantic.dev/latest/integrations/datamodel_code_generator/) 生 code
- 或乾脆不轉 Pydantic,模型 input 用 `dict[str, Any]`(失去 validation)

### 踩雷 4:annotations 是 None

不是所有 MCP server 都宣告 annotations。要 `tool_def.get("annotations") or {}`(`or {}` 處理 `None` 情況)。沒宣告 → 全部預設 False(保守)。

### 踩雷 5:OAuth state 驗證

CSRF 防護。`state` 是隨機字串,callback 收到後要檢查是否 match。Phase 5 簡化版直接 raise on mismatch,別跳過。

### 踩雷 6:大結果寫到 session dir

session dir 隨 session_id 走。MCP 結果寫到 `tool-results/mcp-<server>-<tool>-<ts>.json`,**對應 session 結束**(例如 GC 清理)會影響後續 resume。要記入 transcript:

```python
session_storage.record({
    "kind": "mcp_persisted",
    "filepath": str(filepath),
    "tool_use_id": tool_use_id,
})
```

### 踩雷 7:MCP server instructions 太長

某些 server 的 instructions 上千字。`mcp_instructions_section` 要有上限(類似 MEMORY.md 的 25 KB cap),不然把 system prompt 撐爆。

## 9. 參考資料

### docs/01-11

- [docs/04 §4c](../04-cloud-integration.md) — MCP Client 4 種 transport
- [docs/10 §3](../10-tool-concurrency.md) — MCP 工具的 isConcurrencySafe = readOnlyHint
- [docs/11 §9](../11-tools-catalog.md) — MCP 工具動態載入

### TS 源檔

- `src/services/mcp/client.ts` — 整檔(主邏輯)
- `src/services/mcp/client.ts:1768` — wrap_mcp_tool 對應位置
- `src/services/mcp/client.ts:2720` — processMCPResult
- `src/utils/mcpValidation.ts` — 大結果截斷邏輯
- `src/utils/mcpOutputStorage.ts` — 持久化邏輯

### 外部資源

- [MCP Specification](https://modelcontextprotocol.io/specification)
- [mcp Python SDK](https://github.com/modelcontextprotocol/python-sdk)
- [MCP Inspector](https://github.com/modelcontextprotocol/inspector) — 測試 MCP server 工具
- [Anthropic MCP docs](https://docs.anthropic.com/en/docs/build-with-claude/mcp)

## 完成檢查表

- [ ] stdio transport 跑通
- [ ] SSE / HTTP / InProcess 至少 stub
- [ ] Tool wrapping(`readOnlyHint` 正確讀)
- [ ] 大結果第 1 層處理(寫檔 + 指引 + schema)
- [ ] OAuth flow 跑通(至少一個需要 OAuth 的 server)
- [ ] mcp_instructions 加入 system prompt(`DANGEROUS_uncached`)
- [ ] 接到至少 2 個真實 MCP server 跑通(filesystem + 一個你選的)
- [ ] 寫 Phase 5 心得

完成後進入 [Phase 6:FastAPI Layer](./06-fastapi-layer.md)。

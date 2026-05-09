# Phase 6:FastAPI Layer(HTTP / WebSocket 層)

## 速覽

- **預計時程**:2-3 週
- **前置 Phase**:Phase 1(`Conversation` 可呼叫)+ Phase 2(transcript 持久化)
- **後續 Phase**:Phase 7(Production)會把 in-memory state 換成 Postgres+Redis
- **主要交付物**:
  - WebSocket `/chat/stream`(雙向,支援工具 ask 互動)
  - REST `/chat/sessions` CRUD
  - 統一 event schema(SDKMessage 序列化)
  - JWT auth + middleware
  - 前端 chat skeleton(React + WebSocket client)

## 1. 目標與動機

Phase 1-5 都是 CLI 模式。Phase 6 把 agent 包成 **HTTP service**,讓任何前端可消費:

```
CLI 模式:python -m claude_agent_py "prompt"  ← 一個 process 一個 user
HTTP 模式:多個 client 同時連 → 多 conversations 並存
```

**對應 docs**:無直接對應(Claude Code 是 CLI,Phase 6 是新增 SaaS 化層)
參考:[docs/04](../04-cloud-integration.md) 雲端整合 — Bridge / Remote 章節有些通訊模式可借鑑

完成本 phase 後,你的 agent 變成可被前端消費的服務。

## 2. TS 源檔映射

| Python 模組 | 對應 TS 源檔 | 注意事項 |
|---|---|---|
| `src/api/app.py` | (無) | FastAPI app |
| `src/api/routes/chat.py` | (無) | WebSocket /chat/stream |
| `src/api/routes/sessions.py` | (無) | REST CRUD |
| `src/api/routes/auth.py` | (無) | JWT |
| `src/api/event_schema.py` | `src/entrypoints/agentSdkTypes.js` SDKMessage 部分 | 序列化 schema |
| `src/api/session_manager.py` | (無) | per-user session 管理 |
| `src/api/permissions.py` | `src/hooks/useCanUseTool.tsx` 三決策 | 改成 WebSocket 互動模式 |
| `frontend/` | (無)| React skeleton |

## 3. 任務拆解

### Week 1:基礎 + REST

- [ ] 1.1 加入依賴:`fastapi`、`uvicorn[standard]`、`pyjwt`、`websockets`
- [ ] 1.2 `api/app.py`:FastAPI app 骨架 + middleware
- [ ] 1.3 `api/auth.py`:JWT validate dependency
- [ ] 1.4 `api/routes/sessions.py`:CRUD `/sessions`(create / get / list / delete)
- [ ] 1.5 `api/session_manager.py`:in-memory session map(Phase 7 換 Postgres)
- [ ] 1.6 OpenAPI / Swagger docs 自動產生
- [ ] 1.7 簡單 health check `/healthz`

### Week 2:WebSocket /chat/stream

- [ ] 2.1 `api/event_schema.py`:統一 event 型別(`AssistantTextEvent` / `ToolUseEvent` / `ToolResultEvent` / `PermissionAskEvent` / ...)
- [ ] 2.2 `api/routes/chat.py`:WebSocket endpoint
- [ ] 2.3 訊息協議:client → server `{type: "user_message", content: "..."}`、`{type: "permission_decision", ...}`
- [ ] 2.4 訊息協議:server → client 上面 events
- [ ] 2.5 整合 `Conversation`:每 yield SDKMessage → 序列化送 WebSocket
- [ ] 2.6 `api/permissions.py`:`make_can_use_tool_for_websocket`(透過 ws round-trip 問 user)— **`always_allow` 寫回 settings 的邏輯見 [Phase 13](./13-resilience.md) `permissions/persistence.py`**

### Week 3:前端 skeleton + 整合

- [ ] 3.1 `frontend/`:vite + react + tailwind
- [ ] 3.2 WebSocket client(`/chat/stream`)
- [ ] 3.3 訊息 list UI(訊息泡泡 + tool use 卡片 + permission 對話框)
- [ ] 3.4 流式渲染(逐字顯示 streaming text)
- [ ] 3.5 Permission ask UI(Allow/Deny/Always Allow 按鈕)
- [ ] 3.6 端到端測試(前端 ↔ FastAPI ↔ Conversation ↔ Anthropic API)
- [ ] 3.7 `services/notifier.py`:推送通知整合(對應 TS `services/notifier.ts` 156 行)
   - 桌面 notification(用 `plyer` 跨平台)
   - Web push(用 `pywebpush` Web Push protocol)
   - WebSocket `notification` event 推前端 toast
- [ ] 3.8 `services/away_summary.py`:user 離線後回來摘要(對應 TS `services/awaySummary.ts` 74 行)
   - WebSocket reconnect 觸發
   - 用 sideQuery + Haiku 摘要離開期間 agent 工作
- [ ] 3.7 寫 Phase 6 心得

## 4. 模組架構與檔案

```
src/claude_agent_py/
└── api/
    ├── __init__.py
    ├── app.py                         # ◀ NEW FastAPI app
    ├── deps.py                        # ◀ NEW DI dependencies
    ├── event_schema.py                # ◀ NEW 統一 event 型別
    ├── session_manager.py             # ◀ NEW per-user sessions
    ├── permissions.py                 # ◀ NEW ws-based canUseTool
    └── routes/
        ├── __init__.py
        ├── chat.py                    # ◀ NEW WebSocket /chat/stream
        ├── sessions.py                # ◀ NEW REST CRUD
        ├── auth.py                    # ◀ NEW JWT login
        └── health.py                  # ◀ NEW /healthz

frontend/                              # ◀ NEW(獨立子專案)
├── package.json
├── vite.config.ts
└── src/
    ├── App.tsx
    ├── components/
    │   ├── ChatView.tsx
    │   ├── MessageList.tsx
    │   ├── MessageBubble.tsx
    │   ├── ToolUseCard.tsx
    │   └── PermissionDialog.tsx
    └── hooks/
        └── useWebSocket.ts
```

## 5. Python Skeleton

### 5.1 `api/app.py`

```python
"""FastAPI app 主入口。"""
from __future__ import annotations
from contextlib import asynccontextmanager
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from claude_agent_py.api.routes import chat, sessions, auth, health
from claude_agent_py.api.session_manager import SessionManager


@asynccontextmanager
async def lifespan(app: FastAPI):
    """startup / shutdown hook。"""
    app.state.session_manager = SessionManager()
    yield
    await app.state.session_manager.close_all()


def create_app() -> FastAPI:
    app = FastAPI(
        title="Claude Agent API",
        version="0.1.0",
        lifespan=lifespan,
    )

    # CORS(前端跨網域)
    app.add_middleware(
        CORSMiddleware,
        allow_origins=["*"],  # Phase 7 改 specific origins
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )

    # routes
    app.include_router(health.router)
    app.include_router(auth.router, prefix="/auth")
    app.include_router(sessions.router, prefix="/sessions")
    app.include_router(chat.router, prefix="/chat")

    return app


app = create_app()
```

### 5.2 `api/event_schema.py`(統一 event)

```python
"""WebSocket 雙向訊息協議。"""
from __future__ import annotations
from typing import Literal, Annotated
from pydantic import BaseModel, Field


# === Client → Server ===

class UserMessageEvent(BaseModel):
    type: Literal["user_message"] = "user_message"
    content: str


class PermissionDecisionEvent(BaseModel):
    type: Literal["permission_decision"] = "permission_decision"
    request_id: str
    decision: Literal["allow", "deny", "always_allow"]


class CancelEvent(BaseModel):
    type: Literal["cancel"] = "cancel"


ClientEvent = Annotated[
    UserMessageEvent | PermissionDecisionEvent | CancelEvent,
    Field(discriminator="type"),
]


# === Server → Client ===

class AssistantTextEvent(BaseModel):
    type: Literal["assistant_text"] = "assistant_text"
    text: str
    delta: bool = False  # streaming chunk


class ToolUseEvent(BaseModel):
    type: Literal["tool_use"] = "tool_use"
    tool_use_id: str
    tool_name: str
    input: dict


class ToolResultEvent(BaseModel):
    type: Literal["tool_result"] = "tool_result"
    tool_use_id: str
    content: str
    is_error: bool = False


class PermissionAskEvent(BaseModel):
    type: Literal["permission_ask"] = "permission_ask"
    request_id: str
    tool_name: str
    input: dict
    description: str


class ToolProgressEvent(BaseModel):
    type: Literal["tool_progress"] = "tool_progress"
    tool_use_id: str
    data: dict


class ErrorEvent(BaseModel):
    type: Literal["error"] = "error"
    message: str


class TerminalEvent(BaseModel):
    type: Literal["terminal"] = "terminal"
    reason: str


ServerEvent = Annotated[
    AssistantTextEvent | ToolUseEvent | ToolResultEvent
    | PermissionAskEvent | ToolProgressEvent | ErrorEvent | TerminalEvent,
    Field(discriminator="type"),
]
```

### 5.3 `api/routes/chat.py`(WebSocket)

```python
"""WebSocket /chat/stream。"""
from __future__ import annotations
import asyncio
import json
from uuid import UUID
from fastapi import APIRouter, WebSocket, WebSocketDisconnect, Depends

from claude_agent_py.api.deps import current_user, get_session_manager
from claude_agent_py.api.event_schema import (
    ClientEvent, UserMessageEvent, PermissionDecisionEvent,
    AssistantTextEvent, ToolUseEvent, TerminalEvent, ErrorEvent,
)
from claude_agent_py.api.permissions import make_can_use_tool_for_websocket
from claude_agent_py.api.session_manager import SessionManager


router = APIRouter()


@router.websocket("/stream/{session_id}")
async def chat_stream(
    websocket: WebSocket,
    session_id: UUID,
    user=Depends(current_user),
    session_manager: SessionManager = Depends(get_session_manager),
):
    """雙向 WebSocket。client 送 user_message / permission_decision,
    server 送 assistant_text / tool_use / permission_ask / terminal。
    """
    await websocket.accept()

    try:
        # 取或建立 conversation
        conv = await session_manager.get_or_create(user.id, session_id)
    except Exception as e:
        await websocket.send_json({"type": "error", "message": str(e)})
        await websocket.close()
        return

    # 開兩個 task:讀 client 訊息 + 送 server 訊息
    pending_permission_decisions: dict[str, asyncio.Future] = {}

    async def reader_task():
        """讀 client 送來的訊息。"""
        try:
            while True:
                raw = await websocket.receive_text()
                msg = json.loads(raw)
                event = ClientEvent.model_validate(msg)

                if isinstance(event, UserMessageEvent):
                    # 觸發新 turn
                    await processor_queue.put(event.content)
                elif isinstance(event, PermissionDecisionEvent):
                    fut = pending_permission_decisions.pop(event.request_id, None)
                    if fut and not fut.done():
                        fut.set_result(event.decision)
        except WebSocketDisconnect:
            await processor_queue.put(None)  # 結束信號

    processor_queue: asyncio.Queue = asyncio.Queue()

    # 讓 conversation 用 ws-based canUseTool
    conv.can_use_tool = make_can_use_tool_for_websocket(
        websocket, pending_permission_decisions,
    )

    async with asyncio.TaskGroup() as tg:
        tg.create_task(reader_task())

        while True:
            prompt = await processor_queue.get()
            if prompt is None:
                break

            try:
                # Phase 11 整合後改用 conv.submit_raw_input(prompt) 走 input pipeline
                async for msg in conv.submit_message(prompt):
                    # 把 SDKMessage 序列化成 ServerEvent 送 ws
                    event = _message_to_event(msg)
                    if event is not None:
                        await websocket.send_text(event.model_dump_json())

                # 終止
                await websocket.send_text(
                    TerminalEvent(reason="natural_stop").model_dump_json()
                )
            except Exception as e:
                await websocket.send_text(
                    ErrorEvent(message=str(e)).model_dump_json()
                )


def _message_to_event(msg) -> AssistantTextEvent | ToolUseEvent | None:
    """把 Conversation yield 的 Message 轉成 WebSocket event。"""
    # 依 msg.role / content 結構轉
    if msg.role == "assistant" and isinstance(msg.content, str):
        return AssistantTextEvent(text=msg.content)
    # tool_use / tool_result 等其他類型
    ...
    return None
```

### 5.4 `api/permissions.py`(WebSocket-based canUseTool)

```python
"""透過 WebSocket 互動式問 user 是否允許工具。"""
from __future__ import annotations
import asyncio
from uuid import uuid4
from fastapi import WebSocket

from claude_agent_py.api.event_schema import PermissionAskEvent
from claude_agent_py.permissions.decisions import CanUseToolFn, PermissionDecision


def make_can_use_tool_for_websocket(
    ws: WebSocket,
    pending: dict[str, asyncio.Future],
    *,
    timeout: float = 60.0,
) -> CanUseToolFn:
    """產生 canUseTool 函式,工具觸發時推 ws 給 user 決定。"""

    async def can_use(tool, input, ctx, tool_use_id) -> PermissionDecision:
        # 簡單 policy:read-only 直接 allow,其他問 user
        if tool.is_read_only(input):
            return "allow"

        request_id = str(uuid4())
        future: asyncio.Future = asyncio.get_event_loop().create_future()
        pending[request_id] = future

        await ws.send_text(
            PermissionAskEvent(
                request_id=request_id,
                tool_name=tool.name,
                input=input.model_dump(),
                description=f"Allow {tool.name} to run?",
            ).model_dump_json()
        )

        try:
            decision = await asyncio.wait_for(future, timeout=timeout)
            return decision
        except asyncio.TimeoutError:
            pending.pop(request_id, None)
            return "deny"

    return can_use
```

### 5.5 `api/session_manager.py`

```python
"""Per-user session manager。Phase 6 用 in-memory,Phase 7 換 Postgres。"""
from __future__ import annotations
from uuid import UUID
import anyio

from claude_agent_py.core.conversation import Conversation
from claude_agent_py.core.state import AgentContext


class SessionManager:
    def __init__(self):
        self._sessions: dict[tuple[str, UUID], Conversation] = {}
        self._lock = anyio.Lock()

    async def get_or_create(
        self,
        user_id: str,
        session_id: UUID,
    ) -> Conversation:
        async with self._lock:
            key = (user_id, session_id)
            if key not in self._sessions:
                ctx = AgentContext(session_id=session_id)
                # Phase 7 改:從 DB 載入舊 transcript 並 resume
                self._sessions[key] = Conversation(ctx=ctx, ...)
            return self._sessions[key]

    async def delete(self, user_id: str, session_id: UUID) -> None:
        async with self._lock:
            self._sessions.pop((user_id, session_id), None)

    async def close_all(self) -> None:
        async with self._lock:
            self._sessions.clear()
```

### 5.6 `api/routes/sessions.py`(REST CRUD)

```python
"""Session CRUD。"""
from __future__ import annotations
from uuid import UUID, uuid4
from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel

from claude_agent_py.api.deps import current_user, get_session_manager


router = APIRouter()


class SessionCreate(BaseModel):
    title: str | None = None


class SessionResponse(BaseModel):
    id: UUID
    user_id: str
    title: str | None


@router.post("", response_model=SessionResponse)
async def create_session(
    body: SessionCreate,
    user=Depends(current_user),
    session_manager=Depends(get_session_manager),
):
    session_id = uuid4()
    await session_manager.get_or_create(user.id, session_id)
    return SessionResponse(id=session_id, user_id=user.id, title=body.title)


@router.get("/{session_id}", response_model=SessionResponse)
async def get_session(
    session_id: UUID,
    user=Depends(current_user),
):
    # Phase 7 從 DB 查
    return SessionResponse(id=session_id, user_id=user.id, title=None)


@router.delete("/{session_id}")
async def delete_session(
    session_id: UUID,
    user=Depends(current_user),
    session_manager=Depends(get_session_manager),
):
    await session_manager.delete(user.id, session_id)
    return {"deleted": True}
```

### 5.7 `api/routes/auth.py`(JWT)

```python
"""JWT 簡易實作。Phase 7 換 OAuth + refresh token 等。"""
from __future__ import annotations
import os
from datetime import datetime, timedelta
from fastapi import APIRouter, HTTPException
from pydantic import BaseModel
import jwt


router = APIRouter()
JWT_SECRET = os.environ.get("JWT_SECRET", "dev-secret-change-me")
JWT_ALGORITHM = "HS256"


class LoginRequest(BaseModel):
    username: str
    password: str


class TokenResponse(BaseModel):
    access_token: str
    token_type: str = "bearer"


@router.post("/login", response_model=TokenResponse)
async def login(req: LoginRequest):
    # Phase 6 dev mode:任何 username 都通過
    # Phase 7 整合真實 user DB
    token = jwt.encode(
        {
            "sub": req.username,
            "exp": datetime.utcnow() + timedelta(hours=24),
        },
        JWT_SECRET,
        algorithm=JWT_ALGORITHM,
    )
    return TokenResponse(access_token=token)
```

### 5.8 `api/deps.py`

```python
"""DI dependencies。"""
from __future__ import annotations
from dataclasses import dataclass
from fastapi import Depends, HTTPException, Request
from fastapi.security import OAuth2PasswordBearer
import jwt

from claude_agent_py.api.session_manager import SessionManager


oauth2 = OAuth2PasswordBearer(tokenUrl="/auth/login")


@dataclass
class CurrentUser:
    id: str


async def current_user(token: str = Depends(oauth2)) -> CurrentUser:
    from claude_agent_py.api.routes.auth import JWT_SECRET, JWT_ALGORITHM
    try:
        payload = jwt.decode(token, JWT_SECRET, algorithms=[JWT_ALGORITHM])
        return CurrentUser(id=payload["sub"])
    except jwt.PyJWTError:
        raise HTTPException(401, "invalid token")


def get_session_manager(request: Request) -> SessionManager:
    return request.app.state.session_manager
```

### 5.9 前端 skeleton(片段)

```typescript
// frontend/src/hooks/useWebSocket.ts
import { useEffect, useRef, useState } from 'react'

export function useChatWebSocket(sessionId: string, token: string) {
  const wsRef = useRef<WebSocket | null>(null)
  const [events, setEvents] = useState<ServerEvent[]>([])
  const [connected, setConnected] = useState(false)

  useEffect(() => {
    const ws = new WebSocket(
      `ws://localhost:8000/chat/stream/${sessionId}?token=${token}`
    )
    ws.onopen = () => setConnected(true)
    ws.onmessage = (e) => {
      const event = JSON.parse(e.data) as ServerEvent
      setEvents((prev) => [...prev, event])
    }
    ws.onclose = () => setConnected(false)
    wsRef.current = ws
    return () => ws.close()
  }, [sessionId, token])

  const send = (msg: ClientEvent) => {
    wsRef.current?.send(JSON.stringify(msg))
  }

  return { events, connected, send }
}
```

```typescript
// frontend/src/components/ChatView.tsx
import { useChatWebSocket } from '../hooks/useWebSocket'
import { useState } from 'react'

export function ChatView({ sessionId, token }: Props) {
  const { events, connected, send } = useChatWebSocket(sessionId, token)
  const [input, setInput] = useState('')

  const handleSend = () => {
    send({ type: 'user_message', content: input })
    setInput('')
  }

  return (
    <div className="flex flex-col h-screen">
      <MessageList events={events} onPermissionDecision={...} />
      <div className="p-4 border-t">
        <input
          value={input}
          onChange={(e) => setInput(e.target.value)}
          onKeyDown={(e) => e.key === 'Enter' && handleSend()}
        />
      </div>
    </div>
  )
}
```

## 6. 設計決策與取捨

### 為何 WebSocket 而非 SSE?

- **雙向**:工具權限對話需要 server 主動問 + client 回答
- **保持單一連線**:每個 conversation 一個 ws,訊息有序
- **連線狀態管理**:client 知道何時斷線

SSE 是單向 server → client,不適合互動式 ask。

替代方案:長 polling + REST 也行但複雜很多。

### 為何 in-memory session manager?

Phase 6 重點是「跑通協議」,不是 production 化。Phase 7 才換 Postgres + Redis。但**介面設計時就考慮**,Phase 7 換實作只動 `SessionManager` class。

### 為何 read-only 工具直接 allow?

簡化 demo:`Read` / `Grep` / `WebFetch` 等不會破壞東西的工具直接放行。

Production(Phase 7)應該:
- 由 user policy 決定預設(strict / lenient)
- 含 `allowedTools` / `disabledTools` 設定
- 對 MCP tool 看 server 信任度

### 為何 permission ask 用 timeout?

User 可能離開電腦不回應。60 秒 timeout → 自動 deny,釋放工具執行。Production 應加「等待中」UI 狀態,讓 user 知道 agent 在等他。

### 為何前端用 React 而非 vanilla JS?

純偏好。但建議:
- React + tailwind:生態最大
- Vue / Svelte 也都行
- 純 vanilla 對這種 streaming UI 寫起來累

### Phase 6 故意不做的

| 項目 | 留給哪個 phase |
|---|---|
| Postgres / Redis 持久化 | Phase 7 |
| Per-user quota / rate limit | Phase 7 |
| Multi-tenant 隔離 | Phase 7 |
| 工具沙盒 | Phase 7 |
| 前端 production 化(打包、CDN) | Phase 7+ |
| OAuth(Google/GitHub login) | Phase 7+ |

## 7. 驗收標準

### 自動測試

```bash
pytest tests/api/ -v
```

關鍵測試:

- `test_jwt_auth.py`:有效 token 通過、過期 token 拒絕、無 token 拒絕
- `test_session_crud.py`:建/查/刪 session
- `test_websocket_chat.py`:用 `httpx.AsyncClient` 模擬 ws,送訊息 + 收 events
- `test_permission_ws.py`:工具觸發 ask → mock client 回 allow → 工具執行

### 手動驗證

```bash
# 啟動 server
uvicorn claude_agent_py.api.app:app --reload --port 8000

# 啟動前端
cd frontend && npm run dev
# 開瀏覽器 localhost:5173

# 登入(任何 username 都通)、新建 session、輸入 prompt
# 觀察:
#   - 模型 streaming 文字逐字出
#   - 觸發工具時跳 PermissionDialog
#   - Allow → 工具執行 → 結果顯示
```

### 整合驗證

跑一個完整對話:
```
User: 幫我看 /tmp 下的 .py 檔
→ Agent 想呼叫 Glob → permission_ask 推前端
→ User 點 Allow → Glob 執行
→ 結果展示
→ Agent yield assistant_text "找到 N 個檔案..."
→ Terminal
```

整個流程從前端視覺確認順暢。

## 8. 常見踩雷

### 踩雷 1:WebSocket reconnect 邏輯

連線斷開(網路、瀏覽器 tab 隱藏)→ client 要 reconnect。session 狀態保留(用同 session_id),events 不要重複(server 端用 last_event_id 機制 / client 端 dedup)。

Phase 6 簡化:斷了直接結束 conversation(in-memory 都丟)。Phase 7 改成可 resume。

### 踩雷 2:Async generator + WebSocket 送訊息順序

`Conversation.submit_message` yield 訊息,要按順序送 ws。多個並發 yield(streaming text + tool result)可能交錯。要 `asyncio.Queue` 做 fan-in:

```python
queue = asyncio.Queue()
async def yield_to_queue(...):
    async for msg in conv.submit_message(prompt):
        await queue.put(msg)

while True:
    msg = await queue.get()
    await ws.send(...)
```

### 踩雷 3:TaskGroup 與 WebSocketDisconnect

`asyncio.TaskGroup` 內任一 task 拋例外 → 整個 TaskGroup 取消。`WebSocketDisconnect` 可能在 reader_task 拋出,要正確處理(不是錯誤,是正常斷線)。

```python
try:
    async with asyncio.TaskGroup() as tg:
        ...
except* WebSocketDisconnect:
    pass  # 正常斷線
```

### 踩雷 4:JSON 序列化 datetime / UUID

Pydantic v2 `model_dump_json()` 自動處理。但若 mix 用 `json.dumps(msg.dict())` 會 crash。一律用 `model_dump_json()` 或 `model_dump(mode="json")`。

### 踩雷 5:CORS 錯誤

前端 dev server `localhost:5173` 連 backend `localhost:8000` 有 CORS。FastAPI middleware 加 `allow_origins=["*"]`(dev mode)或具體 origin(production)。

### 踩雷 6:Permission timeout 後再收到 decision

Future 已 timeout 但 client 還是送了 decision → 找不到 pending。silently drop:

```python
fut = pending.pop(request_id, None)
if fut and not fut.done():
    fut.set_result(...)
```

### 踩雷 7:OAuth2PasswordBearer 與 WebSocket

WebSocket 不走 HTTP header,JWT 通常在 query string(`?token=...`)。FastAPI `Depends(oauth2)` 不直接支援 ws,要自寫:

```python
@router.websocket("/stream/{sid}")
async def chat(websocket: WebSocket, sid: UUID, token: str):
    user = decode_jwt(token)  # 自己處理
    ...
```

## 9. 參考資料

### docs/01-11

- [docs/04](../04-cloud-integration.md) — Bridge / Remote 通訊模式參考

### TS 源檔(借鑑用,非直接 port)

- `src/bridge/bridgeApi.ts` — HTTP 通訊模式
- `src/remote/SessionsWebSocket.ts` — WebSocket 重連、訊息序列化
- `src/entrypoints/agentSdkTypes.js` — SDKMessage 結構

### 外部資源

- [FastAPI WebSocket](https://fastapi.tiangolo.com/advanced/websockets/)
- [Pydantic discriminated unions](https://docs.pydantic.dev/latest/concepts/unions/#discriminated-unions)
- [PyJWT](https://pyjwt.readthedocs.io/)
- [React + WebSocket](https://react.dev/reference/react/useEffect)

## 完成檢查表

- [ ] FastAPI app + middleware + routes
- [ ] JWT auth 跑通
- [ ] Session CRUD
- [ ] WebSocket /chat/stream 雙向訊息協議
- [ ] Permission ask 互動式 round-trip
- [ ] 前端 skeleton 可消費 events
- [ ] 端到端對話跑通(前端 → ws → conversation → anthropic → 回前端)
- [ ] 寫 Phase 6 心得

完成後進入 [Phase 7:Sandbox + Production](./07-sandbox-production.md)。

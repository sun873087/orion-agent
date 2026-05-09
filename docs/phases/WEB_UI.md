# 測試用 Web Chat 介面規劃

對 18 份 phase 文件的補充。Phase 6 有提一個簡短 React skeleton,但**開發過程**中你需要的測試 UI **不止一個版本** — 從 Phase 0 的「能 console.log」到 Phase 11+ 的「完整聊天介面」**漸進式建構**。

## 三階段測試 UI

```
Phase 0-2:Stage 1 — 單檔 HTML(快速驗證 streaming + tool call)
                        ↓
Phase 3-5:        (繼續用 Stage 1,加幾個 button 測 memory/MCP)
                        ↓
Phase 6:    Stage 2 — React + WebSocket 完整骨架(取代 Stage 1)
                        ↓
Phase 7-15:Stage 3 — 補功能(memory sidebar / cost / settings / file upload / 多 session)
```

每階段對應「**剛好夠用**」的 UI,不要過度工程。

---

## Stage 1:單檔 HTML 測試頁(Phase 0-2)

**目的**:驗證 backend agent loop 跑得起來。**不需 React、不需 build tool**。一個 HTML 檔開瀏覽器就能用。

### 何時用

- Phase 0 跑通第一個工具(FileReadTool)
- Phase 1 寫完 query loop,測多輪對話 + 工具呼叫
- Phase 2 測 transcript / resume

### 完整檔案:`tools/test-ui.html`

```html
<!DOCTYPE html>
<html>
<head>
<meta charset="utf-8">
<title>Claude Agent Dev Test</title>
<style>
  body { font-family: monospace; max-width: 900px; margin: 20px auto; padding: 20px; }
  #messages { background: #f5f5f5; padding: 12px; height: 500px;
              overflow-y: auto; border: 1px solid #ccc; }
  .user { color: #0066cc; }
  .assistant { color: #333; }
  .tool-use { color: #888; background: #eef; padding: 4px 8px; margin: 4px 0;
              border-left: 3px solid #66f; font-size: 12px; }
  .tool-result { color: #555; background: #efe; padding: 4px 8px;
                 border-left: 3px solid #6f6; font-size: 12px;
                 white-space: pre-wrap; max-height: 200px; overflow-y: auto; }
  .permission { background: #fee; padding: 8px; margin: 4px 0;
                border: 2px solid #f66; border-radius: 4px; }
  .error { color: #c00; }
  #prompt { width: 100%; padding: 8px; font-family: monospace; }
  button { padding: 8px 16px; margin-right: 4px; }
</style>
</head>
<body>

<h1>Claude Agent Dev Test (Stage 1)</h1>
<p>Backend: <input id="endpoint" value="http://localhost:8000" /></p>
<p>Session: <input id="sessionId" placeholder="(auto-created)" /></p>

<div id="messages"></div>

<p>
  <textarea id="prompt" rows="3" placeholder="Type prompt..."></textarea>
</p>
<p>
  <button onclick="send()">Send</button>
  <button onclick="clearChat()">Clear</button>
  <button onclick="newSession()">New Session</button>
</p>

<script>
let ws = null;
let pendingPermissions = {};

function append(html, cls) {
  const div = document.createElement('div');
  div.className = cls;
  div.innerHTML = html;
  document.getElementById('messages').appendChild(div);
  div.scrollIntoView();
}

async function newSession() {
  const r = await fetch(endpoint.value + '/sessions', { method: 'POST' });
  const data = await r.json();
  document.getElementById('sessionId').value = data.id;
  clearChat();
  connect();
}

function clearChat() {
  document.getElementById('messages').innerHTML = '';
}

function connect() {
  if (ws) ws.close();
  const sid = document.getElementById('sessionId').value;
  if (!sid) return;
  const wsUrl = endpoint.value.replace('http', 'ws') + '/chat/stream/' + sid;
  ws = new WebSocket(wsUrl);
  ws.onmessage = (e) => handleEvent(JSON.parse(e.data));
  ws.onerror = (e) => append('[WS error]', 'error');
}

function handleEvent(ev) {
  switch (ev.type) {
    case 'assistant_text':
      append('<b class="assistant">[assistant]</b> ' +
             escapeHtml(ev.text), 'assistant');
      break;
    case 'tool_use':
      append('🔧 <b>' + ev.tool_name + '</b>(' +
             escapeHtml(JSON.stringify(ev.input)) + ')', 'tool-use');
      break;
    case 'tool_result':
      append('<b>↳</b> ' + escapeHtml(
        typeof ev.content === 'string' ? ev.content : JSON.stringify(ev.content)
      ).slice(0, 500) + (ev.content?.length > 500 ? '...' : ''),
      'tool-result');
      break;
    case 'permission_ask':
      const pid = ev.request_id;
      pendingPermissions[pid] = true;
      const html = `🔐 Allow <b>${ev.tool_name}</b>?
        <pre>${escapeHtml(JSON.stringify(ev.input, null, 2))}</pre>
        <button onclick="answerPermission('${pid}', 'allow')">Allow</button>
        <button onclick="answerPermission('${pid}', 'always_allow')">Always</button>
        <button onclick="answerPermission('${pid}', 'deny')">Deny</button>`;
      append(html, 'permission');
      break;
    case 'tool_progress':
      append('⏳ ' + escapeHtml(JSON.stringify(ev.data)), 'tool-use');
      break;
    case 'error':
      append('❌ ' + escapeHtml(ev.message), 'error');
      break;
    case 'terminal':
      append('━━━ done (' + ev.reason + ') ━━━', 'tool-use');
      break;
  }
}

function answerPermission(requestId, decision) {
  ws.send(JSON.stringify({
    type: 'permission_decision',
    request_id: requestId,
    decision: decision,
  }));
}

function send() {
  const text = document.getElementById('prompt').value.trim();
  if (!text || !ws) return;
  append('<b class="user">[user]</b> ' + escapeHtml(text), 'user');
  ws.send(JSON.stringify({ type: 'user_message', content: text }));
  document.getElementById('prompt').value = '';
}

function escapeHtml(s) {
  return String(s).replace(/[&<>]/g, c => ({'&':'&amp;','<':'&lt;','>':'&gt;'})[c]);
}

document.getElementById('prompt').addEventListener('keydown', (e) => {
  if (e.key === 'Enter' && (e.ctrlKey || e.metaKey)) send();
});

// Auto-connect on load
window.addEventListener('load', () => {
  if (document.getElementById('sessionId').value) connect();
});
</script>

</body>
</html>
```

### 使用方式

```bash
# 1. 啟 backend
uvicorn claude_agent_py.api.app:app --reload --port 8000

# 2. 開 HTML(直接 file:// 即可,不需 server)
open tools/test-ui.html

# 3. 點 "New Session" → 開始
```

### Stage 1 涵蓋的測試場景

✅ Streaming 文字逐字顯示(透過 ws.onmessage 即時 append)
✅ Tool use 卡片(綠色背景區分工具)
✅ Tool result 顯示(可滾動,大結果截斷)
✅ Permission ask 互動(三選一按鈕)
✅ Tool progress 進度
✅ Terminal 終止訊號
✅ 換 session

❌ 不涵蓋:檔案上傳、memory 管理、cost 顯示、漂亮 UI、多 session 並存

---

## Stage 2:React + WebSocket 骨架(Phase 6 起)

**目的**:Phase 6 完成 FastAPI WebSocket 後,有像樣的聊天介面測試。

### 何時用

- Phase 6 跑通 WebSocket
- Phase 7 production 化(多 user 連線)
- Phase 8-10 加工具 / hook(需要看 tool use cards 樣式)

### 技術選型

```
框架:Vite + React 18 + TypeScript
樣式:Tailwind CSS(快、不寫 CSS)
狀態:Zustand 或 React Context(避免 Redux 複雜)
WebSocket:原生 WebSocket API + custom hook
Markdown 渲染:react-markdown
程式碼 highlight:shiki / highlight.js
```

### 專案結構

```
frontend/
├── package.json
├── vite.config.ts
├── tailwind.config.js
├── index.html
└── src/
    ├── main.tsx
    ├── App.tsx
    ├── api/
    │   ├── client.ts          # fetch wrapper
    │   └── auth.ts             # JWT 管理
    ├── hooks/
    │   ├── useWebSocket.ts     # ws connection
    │   └── useSession.ts        # session state
    ├── store/
    │   ├── conversation.ts     # current chat state
    │   └── settings.ts         # user settings
    ├── components/
    │   ├── ChatView.tsx        # 主要 chat 畫面
    │   ├── MessageList.tsx     # 訊息列表
    │   ├── MessageBubble.tsx   # 單一訊息
    │   ├── ToolUseCard.tsx     # 工具呼叫卡
    │   ├── ToolResultCard.tsx  # 工具結果
    │   ├── PermissionDialog.tsx # 權限對話
    │   ├── InputBox.tsx         # 輸入框
    │   ├── Sidebar.tsx          # 側欄(session list)
    │   └── ModelSelector.tsx    # 模型切換
    └── types/
        └── events.ts            # 事件型別(對應 Phase 6 event_schema)
```

### 關鍵元件:`useWebSocket` hook

```typescript
import { useEffect, useRef, useState, useCallback } from 'react'
import type { ServerEvent, ClientEvent } from '../types/events'

export function useWebSocket(sessionId: string, token: string) {
  const wsRef = useRef<WebSocket | null>(null)
  const [events, setEvents] = useState<ServerEvent[]>([])
  const [connected, setConnected] = useState(false)
  const [pendingPermissions, setPendingPermissions] = useState<Record<string, ServerEvent>>({})

  useEffect(() => {
    if (!sessionId || !token) return

    const url = `${import.meta.env.VITE_WS_URL}/chat/stream/${sessionId}?token=${token}`
    const ws = new WebSocket(url)

    ws.onopen = () => setConnected(true)
    ws.onclose = () => setConnected(false)
    ws.onmessage = (e) => {
      const event = JSON.parse(e.data) as ServerEvent
      setEvents(prev => [...prev, event])

      // permission ask 進 pending
      if (event.type === 'permission_ask') {
        setPendingPermissions(prev => ({ ...prev, [event.request_id]: event }))
      }
    }

    wsRef.current = ws
    return () => ws.close()
  }, [sessionId, token])

  const send = useCallback((msg: ClientEvent) => {
    wsRef.current?.send(JSON.stringify(msg))
  }, [])

  const answerPermission = useCallback(
    (requestId: string, decision: 'allow' | 'deny' | 'always_allow') => {
      send({ type: 'permission_decision', request_id: requestId, decision })
      setPendingPermissions(prev => {
        const { [requestId]: _, ...rest } = prev
        return rest
      })
    },
    [send],
  )

  return { events, connected, send, pendingPermissions, answerPermission }
}
```

### `MessageList` 組件

```typescript
import { ServerEvent } from '../types/events'
import { MessageBubble } from './MessageBubble'
import { ToolUseCard } from './ToolUseCard'
import { ToolResultCard } from './ToolResultCard'
import { PermissionDialog } from './PermissionDialog'

interface Props {
  events: ServerEvent[]
  pendingPermissions: Record<string, ServerEvent>
  onPermissionDecision: (id: string, decision: string) => void
}

export function MessageList({ events, pendingPermissions, onPermissionDecision }: Props) {
  return (
    <div className="flex-1 overflow-y-auto p-4 space-y-2">
      {events.map((ev, i) => {
        switch (ev.type) {
          case 'assistant_text':
            return <MessageBubble key={i} role="assistant" text={ev.text} />
          case 'tool_use':
            return <ToolUseCard key={i} event={ev} />
          case 'tool_result':
            return <ToolResultCard key={i} event={ev} />
          case 'permission_ask':
            // 已處理過的 ask 不顯示對話框,只顯示卡片
            if (!pendingPermissions[ev.request_id]) {
              return <ToolUseCard key={i} event={{...ev, type: 'tool_use'}} />
            }
            return null
          case 'terminal':
            return (
              <div key={i} className="text-center text-gray-400 text-sm py-2">
                ━━━ {ev.reason} ━━━
              </div>
            )
          case 'error':
            return (
              <div key={i} className="bg-red-50 text-red-700 p-3 rounded">
                ❌ {ev.message}
              </div>
            )
          default:
            return null
        }
      })}

      {/* 所有 pending permissions floats 在底部 */}
      {Object.values(pendingPermissions).map(ev => (
        <PermissionDialog
          key={ev.request_id}
          event={ev}
          onDecide={(d) => onPermissionDecision(ev.request_id, d)}
        />
      ))}
    </div>
  )
}
```

### `ToolUseCard` 組件(展示工具呼叫)

```typescript
export function ToolUseCard({ event }: { event: ToolUseEvent }) {
  return (
    <div className="bg-blue-50 border-l-4 border-blue-400 p-3 rounded text-sm">
      <div className="flex items-center gap-2 font-semibold">
        🔧 {event.tool_name}
      </div>
      <pre className="mt-1 text-xs text-gray-700 overflow-x-auto">
        {JSON.stringify(event.input, null, 2)}
      </pre>
    </div>
  )
}
```

### `PermissionDialog` 組件

```typescript
export function PermissionDialog({ event, onDecide }: Props) {
  return (
    <div className="bg-yellow-50 border-2 border-yellow-400 p-4 rounded-lg">
      <h3 className="font-semibold mb-2">🔐 Allow {event.tool_name}?</h3>
      <pre className="text-xs bg-white p-2 rounded border mb-3 overflow-x-auto">
        {JSON.stringify(event.input, null, 2)}
      </pre>
      <div className="flex gap-2">
        <button
          className="px-4 py-1 bg-green-500 text-white rounded hover:bg-green-600"
          onClick={() => onDecide('allow')}>Allow</button>
        <button
          className="px-4 py-1 bg-blue-500 text-white rounded hover:bg-blue-600"
          onClick={() => onDecide('always_allow')}>Always</button>
        <button
          className="px-4 py-1 bg-red-500 text-white rounded hover:bg-red-600"
          onClick={() => onDecide('deny')}>Deny</button>
      </div>
    </div>
  )
}
```

### Stage 2 涵蓋範圍

✅ Stage 1 全部
✅ 漂亮聊天 UI(訊息泡泡、自動 scroll)
✅ Markdown 渲染(模型回 ```code``` 自動 highlight)
✅ 多 session 切換(sidebar)
✅ 模型切換 dropdown
✅ Connection status 指示

❌ 還不涵蓋:檔案上傳、memory sidebar、cost 顯示、settings UI

---

## Stage 3:完整功能 UI(Phase 11+)

**目的**:測試 Phase 11+ 的進階功能。

### 何時用

- Phase 11 完成 input pipeline → 加檔案上傳
- Phase 13 完成 custom instructions → 加 settings UI
- Phase 14 完成 secureStorage → MCP OAuth 連接介面
- Phase 9 cost tracker → 用量側欄

### 補加組件清單

#### 1. 檔案上傳區(Phase 11)

```typescript
// components/FileUpload.tsx
export function FileUpload({ onFiles }: { onFiles: (files: UploadedFile[]) => void }) {
  const handleDrop = async (e: React.DragEvent) => {
    e.preventDefault()
    const files = Array.from(e.dataTransfer.files)
    const uploaded = await Promise.all(files.map(uploadFile))
    onFiles(uploaded)
  }

  return (
    <div
      onDragOver={(e) => e.preventDefault()}
      onDrop={handleDrop}
      className="border-2 border-dashed border-gray-300 rounded p-4 text-center"
    >
      Drop files here or <input type="file" multiple onChange={...} />
    </div>
  )
}

async function uploadFile(file: File): Promise<UploadedFile> {
  const form = new FormData()
  form.append('file', file)
  const r = await fetch('/uploads', { method: 'POST', body: form })
  return r.json()  // { id, filename, mime, size }
}
```

#### 2. Memory Sidebar(Phase 3 web chat 版)

```typescript
// components/MemorySidebar.tsx
export function MemorySidebar({ userId }: { userId: string }) {
  const [memories, setMemories] = useState<Memory[]>([])

  useEffect(() => {
    fetch(`/users/${userId}/memories`)
      .then(r => r.json())
      .then(setMemories)
  }, [userId])

  return (
    <div className="w-80 border-l overflow-y-auto p-3">
      <h3 className="font-bold mb-3">Memory</h3>
      {memories.map(m => (
        <div key={m.id} className="mb-2 p-2 bg-gray-50 rounded">
          <div className="flex items-center justify-between">
            <span className="text-xs px-2 py-0.5 bg-blue-100 rounded">
              {m.type}
            </span>
            <button onClick={() => deleteMemory(m.id)}>×</button>
          </div>
          <div className="font-semibold mt-1">{m.name}</div>
          <div className="text-sm text-gray-600">{m.description}</div>
        </div>
      ))}
    </div>
  )
}
```

#### 3. Cost 顯示(Phase 9)

```typescript
// components/CostBadge.tsx
export function CostBadge({ sessionId }: { sessionId: string }) {
  const [cost, setCost] = useState<CostSummary | null>(null)

  useEffect(() => {
    const interval = setInterval(async () => {
      const r = await fetch(`/sessions/${sessionId}/cost`)
      setCost(await r.json())
    }, 5000)
    return () => clearInterval(interval)
  }, [sessionId])

  if (!cost) return null
  return (
    <div className="text-xs text-gray-500">
      ${cost.total_cost_usd.toFixed(4)} • {(cost.cache_hit_ratio * 100).toFixed(0)}% cache hit
    </div>
  )
}
```

#### 4. Custom Instructions(Phase 13 web chat 版)

```typescript
// components/CustomInstructionsPanel.tsx
export function CustomInstructionsPanel({ sessionId }: Props) {
  const [conv, setConv] = useState('')
  const [user, setUser] = useState('')

  // 載入
  useEffect(() => {
    fetch('/me/custom-instructions').then(r => r.json()).then(d => setUser(d.text))
    fetch(`/sessions/${sessionId}/custom-instructions`).then(r => r.json()).then(d => setConv(d.text))
  }, [sessionId])

  const save = async () => {
    await fetch('/me/custom-instructions', {
      method: 'PUT',
      body: JSON.stringify({ instructions: user }),
    })
    await fetch(`/sessions/${sessionId}/custom-instructions`, {
      method: 'PUT',
      body: JSON.stringify({ instructions: conv }),
    })
  }

  return (
    <div className="p-4 space-y-4">
      <div>
        <h3 className="font-bold">About you (per-user)</h3>
        <textarea value={user} onChange={(e) => setUser(e.target.value)}
          className="w-full h-32 border rounded p-2" />
      </div>
      <div>
        <h3 className="font-bold">This conversation context</h3>
        <textarea value={conv} onChange={(e) => setConv(e.target.value)}
          className="w-full h-32 border rounded p-2" />
      </div>
      <button onClick={save} className="px-4 py-2 bg-blue-500 text-white rounded">
        Save
      </button>
    </div>
  )
}
```

#### 5. MCP Connections(Phase 5 server-side OAuth)

```typescript
// components/McpConnections.tsx
export function McpConnections() {
  const servers = ['github', 'slack', 'notion']
  const [statuses, setStatuses] = useState<Record<string, boolean>>({})

  useEffect(() => {
    Promise.all(servers.map(s =>
      fetch(`/oauth/status/${s}`).then(r => r.json()).then(d => [s, d.connected])
    )).then(arr => setStatuses(Object.fromEntries(arr)))
  }, [])

  const connect = async (server: string) => {
    const r = await fetch('/oauth/start', {
      method: 'POST',
      body: JSON.stringify({ server }),
    })
    const { authorize_url } = await r.json()
    const popup = window.open(authorize_url, 'oauth', 'width=600,height=700')
    // polling
    const poll = setInterval(async () => {
      const status = await fetch(`/oauth/status/${server}`).then(r => r.json())
      if (status.connected) {
        setStatuses(prev => ({ ...prev, [server]: true }))
        clearInterval(poll)
        popup?.close()
      }
    }, 2000)
  }

  return (
    <div className="p-4 space-y-2">
      <h3 className="font-bold">Integrations</h3>
      {servers.map(s => (
        <div key={s} className="flex items-center justify-between p-2 border rounded">
          <span>{s}</span>
          {statuses[s] ? (
            <span className="text-green-600">✓ Connected</span>
          ) : (
            <button onClick={() => connect(s)} className="text-blue-500">
              Connect
            </button>
          )}
        </div>
      ))}
    </div>
  )
}
```

---

## 完整 Stage 3 layout

```
┌──────────────────────────────────────────────────────────────┐
│ Header:logo / model selector / cost / user menu              │
├──────────┬───────────────────────────────────┬───────────────┤
│          │                                   │                │
│ Sidebar  │      ChatView                     │  Right sidebar │
│          │                                   │                │
│ ▸ New    │  ┌─ Message list ──────────────┐ │  Memory        │
│   Chat   │  │ User: ...                   │ │  ─ user_role  │
│          │  │ Assistant: ...              │ │  ─ feedback   │
│ Sessions:│  │ 🔧 Tool: Read(...)         │ │  ─ project    │
│ ─ chat 1│  │ ↳ result                    │ │                │
│ ─ chat 2│  │ 🔐 Permission ask ...       │ │  Connections   │
│ ─ chat 3│  └────────────────────────────┘ │  ─ GitHub ✓    │
│          │                                   │  ─ Slack       │
│ Settings │  ┌─ Input + uploads ────────┐    │                │
│ Cost:$x │  │ [drop files]              │    │  Custom Inst   │
│          │  │ [Type message...]      📤│    │  [edit]        │
│          │  └──────────────────────────┘    │                │
└──────────┴───────────────────────────────────┴───────────────┘
```

---

## 各 Phase 對應該用哪個 Stage?

| Phase | 推薦 UI | 為何 |
|---|---|---|
| **0** Foundation | Stage 1 | 跑通基礎,簡單夠用 |
| **1** Agent Loop | Stage 1 | 主要驗證 streaming + 工具,單檔 HTML 足夠 |
| **2** Storage | Stage 1 + curl | resume / transcript 用 curl 看 DB,UI 不變 |
| **3** Memory | Stage 1 | 加幾個 button 測 memory 寫 / 讀 |
| **4** System Prompt | Stage 1 | 純後端事,UI 不變 |
| **5** MCP | Stage 1 + curl | OAuth 用 curl 測,工具呼叫 UI 顯示 |
| **6** FastAPI | **Stage 2** | 開始用 React |
| **7** Sandbox | Stage 2 | 工具執行卡片渲染 |
| **8** Hooks/Skills/Plugins | Stage 2 + plugin debug page | 加 plugin 列表 UI |
| **9** Telemetry | Stage 2 + dashboard | 用 Grafana,UI 加 cost badge |
| **10** Tools | Stage 2 | 工具種類多,卡片要更精緻 |
| **11** Input | **Stage 3** | 檔案上傳要 UI |
| **12** Internal | Stage 2-3 | Plan mode 需要 approve UI |
| **13** Resilience | Stage 3 | Custom Instructions UI |
| **14** Distribution | Stage 3 | Settings panel + MCP connect 流程 |
| **15** Multi-Agent | Stage 3 | 多 agent 並行視覺化(coordinator workers / swarm 對話) |

---

## 推薦的具體建構順序

```
Week 1(Phase 0-1):
  ✓ test-ui.html(50 行)→ 開發中當 console 用

Phase 6 完成時:
  ✓ vite create + Stage 2 骨架(2-3 天)
  ✓ ChatView / MessageList / 4 個 Card 元件
  ✓ useWebSocket hook
  → 取代 test-ui.html

Phase 11 完成時:
  ✓ FileUpload 元件(半天)
  ✓ Memory sidebar(半天)
  ✓ CostBadge(2 小時)

Phase 13-14 完成時:
  ✓ CustomInstructions / McpConnections panel(各 1 天)
  ✓ Settings page(2-3 天)

Phase 15 完成時:
  ✓ Coordinator workers visualization
    (用 react-flow 畫 leader → workers DAG)
```

---

## 設計取捨

### 為何 Stage 1 不直接用 React?

Phase 0-2 重點是**驗證 backend 邏輯正確**。React 工程鏈(Vite + npm install + tsc)會分散注意力。單檔 HTML 開瀏覽器即可測,改 UI 直接 reload。**避免過早工程化**。

### 為何 Stage 2 不一上來就做完整 UI?

Phase 6 你還在改 WebSocket 協議。完整 UI 寫完後 Phase 11 加 file upload 又要改 InputBox。**漸進式建構,跟著 phase 走**。

### 為何用 Tailwind 而非 Material UI / Chakra?

- Tailwind:utility 直接寫 className,不需要 component lib lock-in
- Material / Chakra:好看但 bundle 大、改 theme 麻煩
- 測試用 UI 不需要設計系統

production 換 Material 也容易(class names 重寫,不動結構)。

### 為何不直接用 OpenAssistant / LibreChat?

那些是 ChatGPT-clone,有自己的 backend 假設。你的 backend 是 Phase 6 設計的特殊 schema(permission ask / tool progress / terminal events 等)。客製成本不低。**自己寫 react 元件 1-2 週就有可用版本**。

### 為何 permission ask 浮動式而非 modal?

Modal 會阻擋 UI(user 不能滾上去看 context)。**inline 顯示在訊息流中** + sticky footer 提示,讓 user 邊看 context 邊決定。

對應 Claude Code 桌面版的設計。

---

## 部署建議

### Dev 環境

```
backend(localhost:8000)+ frontend(localhost:5173 vite dev)
```

CORS 在 FastAPI 加 `allow_origins=["http://localhost:5173"]`。

### Production

```
frontend → 靜態檔(build 後 npm run build → dist/)
        → CDN / S3 / Vercel / Netlify

backend → K8s(Phase 7c,見 `plan/7c-helm-chart.md`)

兩者透過 https://api.example.com / https://chat.example.com
```

或同 domain(避免 CORS):

```
https://example.com/      → frontend(static files via nginx)
https://example.com/api/  → FastAPI(reverse proxy)
https://example.com/ws/   → WebSocket(reverse proxy with sticky session)
```

---

## 需要的 endpoint 列表(對應現有 Phase)

### Stage 1 / 2 用到

| Endpoint | Phase | 用途 |
|---|---|---|
| `POST /sessions` | 6 | 建 session |
| `GET /sessions/{id}` | 6 | session 詳情 |
| `DELETE /sessions/{id}` | 6 | 刪 session |
| `WS /chat/stream/{id}` | 6 | 主對話 |
| `POST /auth/login` | 6 | JWT |

### Stage 3 額外需要

| Endpoint | Phase | 用途 |
|---|---|---|
| `POST /uploads` | 11 | 檔案上傳 |
| `GET /uploads/{id}` | 11 | 預覽 |
| `GET /me/memories` | 3 | memory 列表 |
| `DELETE /memories/{id}` | 3 | 刪 memory |
| `GET /sessions/{id}/cost` | 9 | 用量 |
| `GET /me/custom-instructions` | 13 | per-user inst |
| `PUT /me/custom-instructions` | 13 | 更新 |
| `GET /sessions/{id}/custom-instructions` | 13 | per-conv inst |
| `PUT /sessions/{id}/custom-instructions` | 13 | 更新 |
| `POST /oauth/start` | 5(web) | MCP 連接 |
| `GET /oauth/status/{server}` | 5(web) | 連線狀態 |
| `GET /me/settings` | 14 | 全部 settings |
| `PUT /me/settings/{key}` | 14 | 更新 setting |

這些大多在 phase docs 裡列過,WEB_UI 整合對照供前端開發查表。

---

## 一句話總結

**測試 UI 漸進式建構:Phase 0-2 用單檔 HTML(50 行,即用)→ Phase 6 起用 React + Tailwind 骨架(漂亮聊天介面)→ Phase 11+ 補 FileUpload / Memory sidebar / Cost / CustomInstructions / MCP connections — 跟著 phase 進度長,不要過早工程化,production 部署用 CDN + 同 domain reverse proxy 避免 CORS。**

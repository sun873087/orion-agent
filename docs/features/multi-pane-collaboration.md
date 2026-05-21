# Multi-pane collaboration

Cowork 的 multi-agent 工作台 — 一個視窗內並排 N 個 pane,各 pane 一條獨立
session / persona / model,彼此可透過 `AskPane` 工具互查 transcript。受 tmux 啟發。

**實作位置**:
- Backend:`apps/orion-cowork/sidecar/src/orion_cowork_sidecar/storage.py` + `handlers.py`
- SDK Tool:`packages/orion-sdk/src/orion_sdk/tools/special/ask_pane.py`
- Skill:`packages/orion-sdk/src/orion_sdk/skills/bundled/ask-pane/SKILL.md`
- Renderer:`apps/orion-cowork/renderer/src/components/{MultiPaneView,NewCollaborationModal,AddPaneModal}.tsx`

## 概念

| 元素 | 是什麼 |
|---|---|
| **Collaboration** | 一個多 pane 的 window;有名字、可選 workspace_dir / project_id / budget_usd_cap |
| **Pane** | Collab 內一個 session,有 `pane_name`(`@xxx`)+ `pane_role`(researcher / coder / reviewer / doc-writer / custom)+ `pane_position`(layout JSON) |
| **AskPane tool** | LLM 在 pane A 透過此工具查 pane B 最近 transcript + 跑到哪一步 + partial output |

每 pane 各自獨立 conversation / context window;**cross-pane 知識只走顯式 tool**,
不 ambient inject 對方訊息進自己 context。

## Data model

兩張關鍵表:

### `cowork_collaborations`(新表)

```sql
CREATE TABLE cowork_collaborations (
    id TEXT PRIMARY KEY,
    name TEXT NOT NULL,
    workspace_dir TEXT,
    project_id TEXT,
    budget_usd_cap REAL,
    created_at REAL NOT NULL,
    updated_at REAL NOT NULL
)
```

### `cowork_session_ext`(擴 4 column)

```sql
collaboration_id TEXT       -- FK to cowork_collaborations.id, NULL = 不在 collab
pane_name TEXT              -- @backend / @reviewer / 同 collab 內唯一
pane_role TEXT              -- researcher / coder / reviewer / doc-writer / custom
pane_position TEXT          -- JSON {row,col,w,h,minimized},layout 還原用
```

外加 index `cowork_session_ext_collab_idx ON (collaboration_id)`,反查同 collab 所有 panes 用。

**Schema migration**:`storage._ensure_cowork_ext_tables` 啟動時跑 `ALTER TABLE ADD COLUMN`(try/except 容錯,既有 DB 自動補上)。

## RPC

| Method | 行為 |
|---|---|
| `collaboration.create` | name / workspace_dir? / project_id? / budget_usd_cap? → 新 collab |
| `collaboration.list` | 列所有 collabs(含 panes 簡略表) |
| `collaboration.get` | by id 拿單 collab 的 detail + panes |
| `collaboration.delete` | 刪 collab 容器(成員 session 釋放成獨立 session,不刪) |
| `collaboration.add_pane` | 把 session 綁進 collab,設 pane_name / role / position;同 collab 內 pane_name 不可重複 |
| `collaboration.remove_pane` | session 從 collab 釋放(session 本身保留) |
| `collaboration.update_pane_position` | layout 改動時持久化 |
| `collaboration.cost_summary` | 加總 collab 內所有 session 的 input/output tokens + per-pane cost_usd(用 model catalog 算) |

## AskPane tool

**Tool name**:`AskPane`(SDK builtin,host-injected callback)。
**自動 inject 條件**:session 屬於某 collab(`_build_conversation` 偵測 `collaboration_id !== NULL`)。
**System prompt 自動 inject**:同 collab 內其他 panes 的 `@name` + role 清單,LLM 才知道自己是誰、旁邊有誰。

### Input

```json
{
  "pane_name": "@reviewer",
  "question": "did you finalize the API contract?",  // optional, informational
  "n_recent_messages": 8  // 1-50
}
```

### Output(host callback 回傳)

```json
{
  "status": "idle | running | done | not_found | error",
  "pane_name": "@reviewer",
  "pane_role": "reviewer",
  "current_action": "streaming response..." | null,
  "transcript_excerpt": [
    { "role": "user", "text": "..." },
    { "role": "assistant", "text": "..." }
  ],
  "partial_output": "...mid-stream text..." | null
}
```

### 設計取捨

- **非阻塞** — A 不會等 B 跑完,B `running` 時 A 拿 partial + status flag,LLM 自己決定要不要等
- **DB-only** — 純讀 target session 的 messages 表,不去叫對方 sidecar 跑 turn,B 多慢都不影響
- **Self-query 拒絕** — pane A query 自己 → `status=error`,訊息「cannot AskPane against yourself」
- **Cross-collab 拒絕** — requester 不在這 collab → `status=not_found`(防偽造)

### Status semantics

| status | 何時 | 怎麼用 |
|---|---|---|
| `idle` | pane 存在但無 messages | 報給 user;建議等對方先動或自己 send prompt 給對方 |
| `running` | `session_id` 在 `Handlers._aborts`(in-flight) | 看 `partial_output` 是否堪用;不堪用時告知 user 等 |
| `done` | 沒 in-flight + 有 messages | 直接整合 transcript_excerpt |
| `not_found` | collab 內沒這 pane_name | 拼字錯;檢查 system prompt 的 roster |
| `error` | 其他失敗(self-query / 跨 collab) | 把訊息 surface 給 user |

## UI 流程(Renderer)

### Sidebar 三 tab IA

```
+ 新對話
─────────────────────────
[ 對話 ] [ 專案 ] [ 協作 ]   ← 互斥,只渲染一個 section
─────────────────────────
... (section content)
─────────────────────────
... (session list,filter 依 tab)
```

| Tab | Section content | Session list filter |
|---|---|---|
| 對話 | 「個人對話」標題 | `project_id IS NULL AND collaboration_id IS NULL` |
| 專案 | Projects list + 「+」新專案 | `project_id IS NOT NULL`(進 project 後 narrow 到那個) |
| 協作 | Collaborations list + 「+」新協作 | `collaboration_id IS NOT NULL`(進 collab 後 narrow 到那個) |

切 tab 自動關掉開著的 collab(`openCollaboration(null)`)。切「對話」也清 `activeProjectId`。

### MultiPaneView

當 `currentCollaborationId !== null` → App.tsx 換成這個 view 取代 single MessageList。

```
┌─ Collab name · N panes · $X.XXXX     [ + 加 pane ] [ ✕ 關閉 ] ┐
├──────────────────────────────────────────────────────────────┤
│  ● @backend (Opus, $0.45)  X │ ● @reviewer (Haiku, $0.10)  X │
│ ┌────────────────────────────┼────────────────────────────┐ │
│ │ messages...                │ messages...                │ │
│ │ ...                        │ ...                        │ │
│ └────────────────────────────┴────────────────────────────┘ │
└──────────────────────────────────────────────────────────────┘
  ↑ react-resizable-panels 拖拉縮放
```

- 點 pane → `activeCollabPaneIndex` 切焦點 + 全域 `sessionId` 同步該 pane 的 session
- 下方共用 `InputBox` 送到焦點 pane
- 狀態燈:綠=active focus / 黃=busy(in-flight) / 灰=idle
- Pane header X → `collaboration.remove_pane`(該 pane session 釋放,collab 仍在)
- Top X → `openCollaboration(null)` 退回單視圖(collab 仍存在)

### 建立 / 加 pane 流程

1. **新協作**:Sidebar 「協作」tab → 「+」→ `NewCollaborationModal`(name 必填,workspace_dir / budget_usd_cap 選填)→ 建後自動開啟
2. **加 pane**:MultiPaneView header / 空狀態「+」→ `AddPaneModal` → 填 `@name` + role + provider/model → 自動 `conversation.create` 然後 `collaboration.add_pane`
3. **刪 collab**:Sidebar collab row hover → 🗑 → confirm → `collaboration.delete`(成員 session 釋放,不刪)

### @ mention 在 collab pane 內

InputBox `@` 弹出選單:collab 中時 panes 排上面(`@reviewer` 之類)+ workspace files 排下面,fuzzy match 過濾。三種顯式前綴(power-user):
- `@skill:<name>` → 只 skill
- `@pane:<name>` → 只 pane
- `@file:<path>` → 只 file

選 pane 後寫 `@<paneName>` literal 進 textarea(LLM 看到 `@xxx` 字面,system prompt 內 roster 教它對應誰)。

## 互斥邏輯

| 動作 | 自動副作用 |
|---|---|
| 切「對話」tab | `activeProjectId=null` + `openCollaboration(null)` |
| 切「專案」tab | `openCollaboration(null)` |
| 切「協作」tab | 不動 project state(collab view 蓋過去) |
| 點 collab → 開啟 | project section 內 row 全 dim(`!inCollab` 條件) |
| 關閉 collab(X) | `activeProjectId` 復原,project section 重亮起 |

## 設計取捨

- **Collab 跟 Project 是不同 entity**:概念上重疊(都「一組 session + workspace」),但因 view-mode 完全不同(單 session vs multi-pane),拆兩張表 + 兩個 sidebar tab 比起塞同一張可讀
- **`@<paneName>` 是字面值不是 attachment**:LLM 看到 `@reviewer` 文字 + system prompt 內 roster,知道誰是誰即可
- **不做主動推播 cross-pane**:Pane B 完成 → 沒 push 給 A,A 想知道要自己呼 AskPane。避免 N 個 pane 互發 notification 變雜訊
- **每 pane 獨立 context**:不共享 LLM context(否則 N 倍 token),只共享 workspace 檔案
- **Optimistic concurrency on shared files**:沿用 SDK `file_state_cache` 機制,A Edit 後 B 再 Edit 同檔會觸發 stale check + LLM 重 Read
- **同檔不做 file lock**:lock owner 跑慢全 blocked,體驗糟。Optimistic 失敗重試 < pessimistic block

## 限制 / 已知問題

- **沒 cross-pane 主動推播**:pane B 完成不會通知 A,A 要主動呼 AskPane 查
- **同檔協作只 optimistic**:同時 Edit 同檔同段是 last-write-wins;LLM 自己 recover
- **Mid-stream partial output 可能不完整**:running pane 的 `partial_output` 是當下 stream 到的內容,持續變,A 看到的是 snapshot
- **Pane 數沒硬限**:UX 上設計 2-4,但無 schema 強制;5+ pane 桌機看不下去
- **Layout 不持久化跨 reload**:`pane_position` 有存 DB,但 react-resizable-panels 預設不 hydrate,刷頁面回 50/50
- **沒 onboarding**:第一次進「協作」tab 沒提示,user 不知道這是什麼

## 測試

```
apps/orion-cowork/sidecar/tests/test_collaboration_storage.py    14 tests
apps/orion-cowork/sidecar/tests/test_collaboration_e2e.py        10 tests
apps/orion-cowork/sidecar/tests/test_ask_pane_callback.py         8 tests
packages/orion-sdk/tests/unit/tools/special/test_ask_pane.py     10 tests
```

涵蓋:
- Storage CRUD + dedupe by pane_name + delete release semantics + cost summary
- RPC end-to-end(create/get/add_pane/remove_pane/update_position/delete/conflict)
- AskPane callback 各 status(idle / running / done / not_found / self-query reject / cross-collab reject)+ transcript truncation by `n_recent_messages`
- AskPaneTool unit:no-callback / callback success / callback exception / input validation / read-only & concurrency-safe

## 未來方向

- **Cross-pane 主動推播**:pane B 完成 → message_bus 推 A,A 看到 「@B is done」badge
- **Layout 持久化**:`pane_position` 真載入 react-resizable-panels 初始 size
- **Onboarding**:第一次「協作」tab 顯示 4 個 role preset 範例
- **同 workspace 多 pane 衝突解決升級**:Optimistic + 自動 merge 提示 LLM
- **Pane minimization / dock badge**:N>2 pane 桌機塞不下時收成 edge badge
- **跨 LLM provider failover in pane**:pane 用的 model 跑掛 → 自動切備援 provider
- **Replay 整個 collab**:依 timestamp 排序所有 pane 的 messages,複盤協作過程

詳細的未做 vs 不做見 [`../roadmap/multi-pane-collaboration.md`](../roadmap/multi-pane-collaboration.md)。

## 看完繼續

- [cowork.md](./cowork.md) — Cowork 整體
- [tools.md](./tools.md) — 內建工具(含 AskPane)
- [multi-agent.md](./multi-agent.md) — SDK 既有 Coordinator / Swarm(headless 版本,跟此 feature 對比)
- [skills.md](./skills.md) — bundled skills(含 `ask-pane`)
- [`../roadmap/multi-pane-collaboration.md`](../roadmap/multi-pane-collaboration.md) — 設計筆記 + 未實作部分

# Multi-pane collaboration

Cowork 的多 agent 工作台 — 同一視窗並排 N 個 pane,每 pane 一條獨立 session +
model + persona,可互相 query。受 tmux 啟發,讓「多 agent 協作」**全程可見** + **user
隨時介入**(對比 SDK 既有 Coordinator / Swarm 是 headless 跑)。

**實作位置**:
- 後端 SDK:`packages/orion-sdk/src/orion_sdk/{tools/special/ask_pane,roles,skills/bundled/ask-pane}/`
- Sidecar:`apps/orion-cowork/sidecar/src/orion_cowork_sidecar/{storage,handlers,role_handlers}.py`
- Renderer:`apps/orion-cowork/renderer/src/components/{MultiPaneView,NewCollaborationModal,AddPaneModal,settings/RolesSection}.tsx`

---

## 一句話定位

> 多 agent 同畫面、平行跑、看得見彼此、可互相詢問。Pane 間用 markdown role 定義
> 各自定位(researcher / coder / reviewer / ...),透過 `AskPane` 工具非阻塞查
> 對方 transcript。

---

## 適用場景

| 場景 | Pane 配置 |
|---|---|
| **不同模型分工** | Opus 跑硬推理 / Sonnet 寫 code / Haiku 跑 quick review |
| **平行探索** | 同題目 3 個 pane 跑 3 種解法,user 選最好 |
| **對抗式 review** | `@coder` 寫 code、`@reviewer` 即時挑刺、`@coder` 再修 |
| **前後端分工** | A pane 在 `backend/` repo、B pane 在 `frontend/` repo,靠 cross-pane 對齊 API spec |
| **研究 → 實作 → 文件** | `@researcher` 探完 → `@coder` 實作 → `@doc-writer` 寫文件 |

---

## 三大組件

```
┌─────────────────────────────────────────────────────────┐
│ Collaboration(容器)                                    │
│  - 一個視窗、N 個 pane                                  │
│  - 共用 workspace_dir / project_id / budget_usd_cap     │
│                                                         │
│  ┌─────────────────┐ ┌─────────────────┐                │
│  │ Pane(session)  │ │ Pane(session)  │  ...           │
│  │ - @<name>       │ │ - @<name>       │                │
│  │ - role          │ │ - role          │                │
│  │ - 自己 LLM      │ │ - 自己 LLM      │                │
│  │ - 自己 context  │ │ - 自己 context  │                │
│  │ - 自己 cost     │ │ - 自己 cost     │                │
│  └────────┬────────┘ └────────┬────────┘                │
│           │ AskPane 跨 pane query                       │
│           └────────────┬──────┘                         │
│                        ▼                                │
│                  DB (cowork.db)                         │
│                  - 同 collab 內透過 collaboration_id   │
│                    JOIN 找 sibling pane 的 transcript   │
└─────────────────────────────────────────────────────────┘
```

### 1. Collaboration
collab 容器,有名字、可選 workspace、可選預算上限。對應 sidebar「協作」tab。

### 2. Pane
collab 內的一個 session。每 pane 有:
- `pane_name` — `@xxx`,collab 內唯一,LLM 用此名字 reference 別人
- `pane_role` — `researcher` / `coder` / `reviewer` / `doc-writer` / `custom`,或 user 自訂
- `pane_position` — JSON `{row, col, w, h, minimized}`,layout 還原用
- 對應一個獨立 session_id,有自己的 messages / model / context window / 累積 cost

### 3. AskPane tool
非阻塞 cross-pane query。Pane A 對 LLM 說「@reviewer 看過了嗎?」→ LLM 呼
`AskPane(pane_name="@reviewer")` → 拿回對方最近 transcript + status,A 自己決定要不
要等。

---

## 從零跑通典型流程

### Day 1:建立第一個 collab

1. Sidebar 切「協作」tab → 點 `+` 按鈕
2. **NewCollaborationModal** 跳出:
   - **名稱**(必填):e.g. `「重構 query loop」`
   - **共用工作目錄**(選填):點按鈕選資料夾,collab 內所有 pane 預設這目錄
   - **預算上限 USD**(選填):e.g. `5.00`(目前 column 已存但**enforcement 尚未 wire**)
3. 送出 → 自動開啟空 collab,中央顯示「這個協作還沒加入任何 pane」+「+ 加 pane」按鈕

### Day 1.5:加 panes

點「+ 加 pane」→ **AddPaneModal**:
- **Pane 名稱**(`@xxx` 形式)— collab 內唯一
- **角色** — 下拉選單列出當前所有 role(bundled 4 個 + user 自訂),每 role 帶 description
- **Provider + Model** — 預設用 user 全域選的 model,可改
- 送出 → 後台跑兩個 RPC:
  1. `conversation.create` 建新 session
  2. `collaboration.add_pane` 把 session 綁進 collab + 設定 pane_name/role/position

加完兩個 pane 後 → MultiPaneView 顯示兩欄並排:

```
┌─ 重構 query loop · 2 個 pane · $0.0000 · [+ pane] [X] ─────────────────┐
├──────────────────────────────────────────────────────────────────────────┤
│ ● @backend (coder, Opus)  X │ ○ @reviewer (reviewer, Haiku)  X         │
│ ┌─────────────────────────┼─────────────────────────────────────┐       │
│ │ (messages...)           │ (messages...)                       │       │
│ │                         │                                     │       │
│ └─────────────────────────┴─────────────────────────────────────┘       │
└──────────────────────────────────────────────────────────────────────────┘
                ↑ 底下共用 InputBox,送到「焦點 pane」
```

- ● = active focus(綠燈),○ = idle(灰),🟡 = busy(running),🔴 = error
- 點任一 pane 切焦點
- 拖中間直線可改寬度比例(react-resizable-panels)
- 每 pane header 即時顯示:狀態燈 / `@name` / role / model / cost / X(從 collab 移除此 pane)

### Day 1.7:對話 + cross-pane query

點 `@backend` pane 切焦點,在 InputBox 輸入:
```
幫我把 query_loop.py 拆成 3 個 module
```
送出 → `@backend` 開始跑(busy 黃燈),user 切到 `@reviewer` pane 輸入:
```
等 @backend 寫完,你 review 他改了哪些
```
送出 → `@reviewer` 收到後,LLM 會自動呼 `AskPane(pane_name="@backend")` 拿狀態:

```json
{
  "status": "running",
  "pane_name": "@backend",
  "pane_role": "coder",
  "current_action": "streaming response...",
  "transcript_excerpt": [
    { "role": "user", "text": "幫我把 query_loop.py 拆成 3 個 module" },
    { "role": "assistant", "text": "...streaming..." }
  ],
  "partial_output": "我先看當前結構..."
}
```

`@reviewer` 看到 `status=running` 會回 user:「@backend 還在跑,我等他結束再 review」。

`@backend` 結束後 user 在 `@reviewer` 輸入「現在 review 吧」→ AskPane 拿到完整 transcript → 開始批判。

### Day N:跨 sidecar 重啟

- Cost 累積值持久化在 `cowork_session_ext.cum_*` 五個欄位 + 每 send 完寫入
- `_resume_from_db` 載入 conv 時 hydrate stats 回 in-memory
- 重開 collab → 各 pane cost 顯示正確,user 看得到歷史累積

⚠ **Limitation**:在「cost 持久化」commit 之前 send 過的對話沒寫 `cum_*`,hydrate 出 0。要再 send 一輪才會開始累積。

### Day N+:刪除 collab

Sidebar collab row hover → 🗑 → 兩次確認:
1. **第一問**:「確定要刪除協作 X 嗎?」
2. **第二問**(若有 panes):「要把 N 個成員對話也一起刪掉嗎?」
   - **確定** = sessions 全刪(messages / blobs / cum_* 一起清)
   - **取消** = sessions 釋放成個人對話(會出現在「對話」tab)

---

## Data model

### `cowork_collaborations`(新表)
```sql
id TEXT PRIMARY KEY
name TEXT NOT NULL
workspace_dir TEXT
project_id TEXT
budget_usd_cap REAL          -- 已加欄位,enforcement 尚未 wire
created_at REAL NOT NULL
updated_at REAL NOT NULL
```

### `cowork_session_ext`(擴 9 個 columns)
原本只記 workspace / project / starred / plan_mode_* / budget_*;multi-pane
collaboration 加進:

```sql
-- 綁定資訊
collaboration_id TEXT        -- FK to cowork_collaborations.id, NULL = 一般 session
pane_name TEXT               -- @xxx, collab 內唯一
pane_role TEXT               -- researcher / coder / ... / 自訂
pane_position TEXT           -- JSON {row, col, w, h, minimized}

-- Cost 持久化(此 session 累積)
cum_input_tokens INTEGER NOT NULL DEFAULT 0
cum_output_tokens INTEGER NOT NULL DEFAULT 0
cum_cache_read_tokens INTEGER NOT NULL DEFAULT 0
cum_cache_creation_tokens INTEGER NOT NULL DEFAULT 0
cum_turns INTEGER NOT NULL DEFAULT 0
```

Index:`cowork_session_ext_collab_idx ON (collaboration_id)`,反查同 collab 所有 panes 用。

**Migration**:`_ensure_cowork_ext_tables` 啟動時跑 `ALTER TABLE ADD COLUMN`(try/except 容錯),既有 DB 自動補。

---

## RPC API(JSON-RPC)

### Collaboration CRUD
| Method | 行為 | 重要 params |
|---|---|---|
| `collaboration.create` | 建空 collab | `name`(必), `workspace_dir?`, `project_id?`, `budget_usd_cap?` |
| `collaboration.list` | 列所有(含 panes 簡略表) | — |
| `collaboration.get` | by id 拿單 collab detail | `collaboration_id` |
| `collaboration.delete` | 刪 collab(可選刪 sessions) | `collaboration_id`, `delete_sessions?: bool`(預設 false 釋放,true 整批刪) |

### Pane 管理
| Method | 行為 |
|---|---|
| `collaboration.add_pane` | 把 session 綁進 collab,設 pane_name/role/position;同 collab 內 pane_name 不可重複(回 `CONFLICT`) |
| `collaboration.remove_pane` | session 從 collab 釋放 |
| `collaboration.update_pane_position` | layout 改動時持久化 position JSON |

### Cost
| Method | 行為 |
|---|---|
| `collaboration.cost_summary` | 走 in-memory `conv.stats`(自動 resume 從 DB hydrate)+ orion_model.pricing 算 cost,回每 pane + total |

### Role 系統(可動態 CRUD)
| Method | 行為 |
|---|---|
| `role.list` | 列 bundled + user roles。同名 user 覆蓋 bundled,列表只顯一筆(source 標 `user`) |
| `role.get` | 拿單一 role 的 body + frontmatter(含 bundled,以便 GUI 顯預設值供 user 改) |
| `role.write` | **永遠寫到 user 目錄** `~/.orion/users/<u>/roles/<slug>/ROLE.md`。Bundled 檔本身從不被改動 |
| `role.delete` | 刪 user role。Bundled 不可刪(回 `NOT_FOUND`)。刪 user 同名 role 等於「reset 回 bundled 預設」 |

---

## Role 系統(file-based + GUI)

### 概念
每 role 一個 markdown,跟 skills 同一套 pattern,跨 Cowork / CLI / chat-api 共用
`~/.orion/users/<u>/roles/`。

### 檔案結構
```yaml
---
name: data-analyst
description: SQL / pandas 分析師
default_disabled_tools: Bash,Edit,Write
default_permission_mode: ask
---

You are a data-analyst in this collaboration.

Your job is to analyze data — query DBs, run pandas notebooks, produce charts.
You don't write production code or modify files outside of notebooks.

(以下是 LLM 看的 prompt body,append 進 system prompt)
```

### Frontmatter 欄位
- `name`(預設用資料夾名)
- `description`:UI 顯示用一句話
- `default_disabled_tools`:CSV 或 list,建 pane 時自動 disable 這些 tool
- `default_permission_mode`:`ask` / `act`(可選;不設 = 用 user 預設)

### 兩種編輯方式
1. **GUI**(推薦):Settings → 桌面 → 「協作角色」tab
   - List bundled + user 混合 + filter「全部 / 內建 / 我的」(source badge 區分)
   - **Bundled 也直接編** — 點 row 進入 detail 所有欄位皆可改,頂部琥珀色 banner
     提醒「儲存後會建立你的版本(內建版檔案還在,刪你的版本即 reset)」,儲存按鈕顯
     「存成我的版本」
   - **User role** detail 進去直接編,儲存按鈕一般顯「儲存」,可從列表 🗑 刪除
   - 「+ 新角色」建空白(若 name 撞 bundled 顯紅字 ⚠ 提示會覆蓋,允許 submit)
2. **直接編 markdown**:vim `~/.orion/users/cowork-local/roles/<name>/ROLE.md`
   - GUI 跟 markdown 完全 interop,GUI 寫的也是同位置
   - 沒寫 user 版時,bundled 版生效;寫了 user 版,loader 自動 last-wins 用 user

> Bundled markdown 檔本身**從不被改動** — 不論用 GUI 還是 markdown 編輯,所有 user
> 修改都落到 `~/.orion/users/<u>/roles/<name>/ROLE.md`。Reset 機制 = 刪 user 檔
> → loader 回到 bundled。

### 4 個 bundled defaults
| Role | 預設 disabled | 適合 |
|---|---|---|
| `researcher` | Edit, Write, Bash, NotebookEdit | 唯讀調查,Read/Grep/Glob/WebFetch only |
| `coder` | (空) | 實作,可 Edit/Write/Bash 跑 test |
| `reviewer` | Edit, Write, Bash, NotebookEdit | 唯讀批判,只 Read + Grep + AskPane |
| `doc-writer` | Bash, NotebookEdit | 改 markdown(允 Edit/Write),不跑 shell |

### Role 怎麼套用
`_build_conversation` 內偵測 pane 屬於 collab + 有 `pane_role`(非 `custom`):
1. `load_all_roles(user_id=...)` 拿全套 roles
2. 找對應 role
3. **Merge** `role.default_disabled_tools` 進 `disabled_set` → tool list 自動少這些
4. `role.body` append 到 `system_prompt`,放在 `# Your role` 段落

---

## `AskPane` tool

### Spec
```
name: AskPane
input_schema:
  pane_name: string (required)         # @reviewer, 帶不帶 @ 皆可
  question: string | null              # 可選,目前 informational,將來可能 forward
  n_recent_messages: int (1-50)        # 預設 8
```

### Output
```json
{
  "status": "idle | running | done | not_found | error",
  "pane_name": "@reviewer",
  "pane_role": "reviewer",
  "current_action": "streaming response..." | null,
  "transcript_excerpt": [
    {"role": "user", "text": "..."},
    {"role": "assistant", "text": "..."}
  ],
  "partial_output": "...mid-stream text..." | null
}
```

### Status semantics
| status | 何時 | LLM 應怎麼用 |
|---|---|---|
| `idle` | pane 存在但無 messages | 報給 user;建議等對方先動 |
| `running` | target session 在 `Handlers._aborts`(in-flight) | 看 partial 是否堪用;不堪用 → 告訴 user 等 |
| `done` | 沒 in-flight + 有 messages | 直接整合 transcript_excerpt |
| `not_found` | collab 內沒這 pane_name | 拼字錯;查 system prompt 內 roster |
| `error` | self-query / cross-collab | surface 給 user |

### 設計關鍵
- **非阻塞** — A 不等 B 跑完,拿到 partial + status flag 自己決定
- **DB-only** — 純讀 target session 的 messages 表,不去叫對方 sidecar 跑 turn,B 多慢都不影響
- **Self-query 拒絕** — pane A query 自己 → `status=error`
- **Cross-collab 拒絕** — requester 不在這 collab → `status=not_found`(防偽造)
- **Host 注入** — SDK 不直接接 DB,sidecar 在 `_build_conversation` 偵測 collab + 注入
  callback(closure 抓住 collaboration_id + engine)

### Bundled skill `ask-pane`
`packages/orion-sdk/src/orion_sdk/skills/bundled/ask-pane/SKILL.md` — 用 markdown 教
LLM 在何時用 AskPane,各 status 怎麼回應,常見 anti-pattern。Skill 自動載入時 LLM 看
得到。

---

## UI:3-tab Sidebar

```
+ 新對話
──────────────────────────────
[ 對話 ] [ 專案 ] [ 協作 ]      ← 互斥 tab,只渲染一個 section
──────────────────────────────
... (active section)
──────────────────────────────
... (session list, filter 依 tab)
```

| Tab | Section 內容 | Session list filter |
|---|---|---|
| 對話 | 「個人對話」標題 | `project_id IS NULL AND collaboration_id IS NULL` |
| 專案 | Projects list + 「+」 | `project_id IS NOT NULL`(進 project 後 narrow) |
| 協作 | Collaborations list + 「+」 | `collaboration_id IS NOT NULL`(進 collab 後 narrow) |

切「對話」自動清 `activeProjectId` + 關閉開著的 collab。切「專案」/「協作」也都做
合理互斥處理(切「協作」時 project 區域 row 全部去 active 標,避免兩處同時亮)。

---

## @ Mention 在 collab 內

InputBox `@` popup 在 collab pane 內,**panes 排上面 + files 排下面**:

```
┌─ PANES & FILES ──────────────────────────┐
│ 👥 @reviewer       reviewer              │
│ 👥 @backend        coder                 │
├──────────────────────────────────────────┤
│ 📄 src/api.py     1.2 KB                 │
│ 📄 README.md      3.4 KB                 │
└──────────────────────────────────────────┘
↑↓ 切換 · Tab/Enter 選 · Esc 取消
type `@skill:` / `@pane:` / `@file:` for explicit
```

- 選 pane → 寫 `@<paneName>` literal 進 textarea,LLM 看到字面 + system prompt 內 roster 知道對應誰
- 三種顯式前綴(power-user):`@skill:<name>` / `@pane:<name>` / `@file:<path>`
- Non-collab session(個人對話 / 專案)內沒 panes 部分,popup 就只 files(原本行為)

---

## Cost 持久化機制

### 寫入時機
`conversation.send` 結束(finally block):
```python
await storage.persist_session_stats(
    engine, sid,
    input_tokens=conv.stats.input_tokens,
    output_tokens=conv.stats.output_tokens,
    cache_read_tokens=conv.stats.cache_read_tokens,
    cache_creation_tokens=conv.stats.cache_creation_tokens,
    turns=conv.stats.turns,
)
```
UPSERT 進 `cowork_session_ext.cum_*`,覆蓋(cumulative 由 caller 傳完整值,不 +=)。

### 讀取時機
`_resume_from_db` 載入 conv 後立刻 hydrate:
```python
persisted = await storage.get_session_stats(engine, sid)
conv.stats.input_tokens = persisted["input_tokens"]
... # 4 個欄位都拉
```
跨 sidecar restart 後,任何 session 第一次被觸發(send / cost_summary)就會 resume + hydrate,cost 恢復正確值。

### Cost summary 即時刷新
`MultiPaneView` 用兩個機制:
- **Busy state transition 觸發**:`busyKey = sid:B|sid:I|...` 變動就重抓
- **每 5s polling 保險**:LLM 跑著也看到累積上升

---

## 互斥邏輯總表

| 動作 | 自動副作用 |
|---|---|
| 切「對話」tab | `activeProjectId=null` + 關閉 collab |
| 切「專案」tab | 關閉 collab(不動 activeProjectId) |
| 切「協作」tab | 不動 project state(collab view 蓋過去) |
| 點 collab 開啟 | project section row 全 dim(`!inCollab` 條件) |
| 關閉 collab(X) | `activeProjectId` 復原,project section 重亮 |

---

## 設計取捨

| 決定 | 為什麼 |
|---|---|
| **Collab 跟 Project 拆兩張表** | 概念重疊(都「一組 session + workspace」),但 view-mode 完全不同(單 session vs multi-pane),拆兩 entity 比塞同表清楚 |
| **`@<paneName>` 是字面值,不是 attachment** | LLM 看到 `@reviewer` 文字 + system prompt 內 roster,知道誰是誰即可 — 不需要結構化 attachment 機制 |
| **不做主動推播** | Pane B 完成不 push 給 A,A 想知道要自己呼 AskPane。避免 N 個 pane 互發 notification 變雜訊 |
| **每 pane 獨立 context** | 不共享 LLM context(否則 N 倍 token);只共享 workspace 檔案 |
| **Optimistic concurrency on shared files** | 沿用 SDK `file_state_cache`:A Edit 後 B 再 Edit 同檔觸發 stale check + LLM 重 Read |
| **不做 file lock** | Lock owner 跑慢全 blocked,體驗糟。Optimistic 失敗重試比 pessimistic block 好 |
| **Role 跟 Skill 兩個 pattern 但拆檔** | 概念分得開 — Skill 是「LLM 可叫的 tool-like 能力」,Role 是「pane 的人格 + 工具預設」。共用 markdown frontmatter 套路但不同 schema |
| **Role file-based 不 DB** | 跨 host 共用 `~/.orion/`,可手動編、可分享、可 git 版控 |
| **Bundled role 直接可編,儲存自動 clone 到 user** | non-IT user 不該學「同名 user role override」概念。點開 bundled = 直接編,save 自動寫到 user dir,banner 告知。Reset = 刪你的版本。bundled markdown 檔本身永遠不動 |

---

## 限制 / 已知問題

| 項目 | 狀況 |
|---|---|
| **沒 cross-pane 主動推播** | pane B 完成不通知 A;A 要主動呼 AskPane 查 |
| **同檔協作只 optimistic** | 同時 Edit 同檔同段 last-write-wins;LLM 自己 recover |
| **Mid-stream partial output 不完整** | running pane 的 `partial_output` 是當下 stream 到的 snapshot,持續變,A 看到的可能還沒完整 |
| **Pane 數沒硬限** | UX 設計 2-4,無 schema 強制;5+ pane 桌機看不下去 |
| **Layout 不持久化跨 reload** | `pane_position` 有存 DB,但 react-resizable-panels 預設不 hydrate,刷頁面回 50/50 |
| **沒 onboarding** | 第一次進「協作」tab 沒提示,user 不知道這是什麼 — 只看到「+」按鈕 |
| **`budget_usd_cap` 未強制** | column 已加但 enforcement 沒 wire(per-session budget 仍會擋,collab 加總不會) |
| **Cost 跨重啟限制** | 只有「持久化後 send 過」的 session 才有 `cum_*` 值;之前的對話 hydrate 出 0,要再 send 一輪累積 |

---

## 測試覆蓋

```
apps/orion-cowork/sidecar/tests/test_collaboration_storage.py        17 tests
apps/orion-cowork/sidecar/tests/test_collaboration_e2e.py            11 tests
apps/orion-cowork/sidecar/tests/test_ask_pane_callback.py             8 tests
apps/orion-cowork/sidecar/tests/test_role_rpc.py                      9 tests
packages/orion-sdk/tests/unit/tools/special/test_ask_pane.py         10 tests
packages/orion-sdk/tests/unit/roles/test_loader.py                   11 tests
                                                              共 66 tests
```

涵蓋:
- Storage CRUD + dedupe by pane_name + delete release / cascade semantics + cost summary
  + persist/hydrate stats round-trip
- RPC end-to-end:create/get/add_pane/remove_pane/update_position/delete(with /
  without `delete_sessions`)/conflict
- AskPane callback 各 status(idle / running / done / not_found / self-query reject /
  cross-collab reject)+ transcript truncation by `n_recent_messages` + partial output 抓取
- AskPaneTool unit:no-callback / callback success / callback exception / input validation
- Role loader:bundled 4 個 / disabled_tools CSV parse / user override bundled
- Role RPC:list / get / write / delete / bundled 不可刪 / user override bundled

---

## 未來方向

短期(可動)
- **Cost summary live notification**:目前 polling 5s,改 sidecar 主動 push「pane busy
  state changed」事件,UI 立刻 refresh
- **Layout 持久化載入**:`pane_position` 真 hydrate 進 react-resizable-panels initial size
- **`budget_usd_cap` enforcement**:cost_summary 超 cap → 整 collab pause + emit notification

中期
- **Cross-pane 主動推播**(message_bus wire):pane B 完成 → A 收到 `@B done` badge,不用主動
  AskPane
- **Onboarding tour**:第一次進「協作」tab 顯 4 個 role preset 範例 + step-by-step
- **Pane minimization / dock badge**:N>2 桌機塞不下時收成 edge badge
- **Replay 整個 collab**:依 timestamp 排所有 pane 的 messages,複盤協作過程

長期 / 進階
- **跨 LLM provider failover in pane**:pane 用的 model 跑掛 → 自動切備援
- **Same-workspace 自動 merge 提示 LLM**:衝突時不只回 error,還用 LLM 提 diff merge 建議
- **Voice realtime in collab**:Realtime API + pane focus 連動

詳細未做 vs 不做見 [`../roadmap/multi-pane-collaboration.md`](../roadmap/multi-pane-collaboration.md)。

---

## 看完繼續

- [cowork.md](./cowork.md) — Cowork 整體
- [tools.md](./tools.md) — 內建工具(含 AskPane)
- [multi-agent.md](./multi-agent.md) — SDK 既有 Coordinator / Swarm(headless 版本,跟本 feature 對比)
- [skills.md](./skills.md) — bundled skills(含 `ask-pane`)+ Role 共用的 markdown loader pattern
- [`../roadmap/multi-pane-collaboration.md`](../roadmap/multi-pane-collaboration.md) — 設計筆記 + 未實作部分

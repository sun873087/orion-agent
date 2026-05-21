# Multi-pane collaboration — tmux-like 多 agent 協作工作台

把 Cowork 從「一次一個對話」升成「**一個 window 同時跑 N 個 agent,各自 model /
persona / pane,可互相 reference**」。受 tmux 啟發。

> 目前不在實作範圍,設計討論收檔。何時做、做不做,看 Cowork user 真實需求出現再啟動。

---

## 一句話定位

> **多個 agent 在同畫面、平行跑、看得見彼此、可互相詢問。** 跟 SDK 既有 Coordinator /
> Swarm 不同 — 那兩個是後台 headless 跑;這是 **interactive、全程可見、user 隨時介入**
> 的協作 UX。

---

## 想解的場景

| 場景 | Pane 配置 |
|---|---|
| **不同模型分工** | Opus 跑硬推理 / Sonnet 寫 code / Haiku 跑 quick review |
| **平行探索** | 同題目 3 個 pane 跑 3 種解法,user 選最好 |
| **對抗式 review** | A 寫 code、B 是 reviewer 即時挑刺、C 跑測試 |
| **前後端分工** | A 改 backend repo、B 改 frontend repo、靠 cross-pane 對齊 API spec |
| **角色專業化** | researcher / coder / critic / doc-writer 各自人格 system prompt |

---

## 核心設計決策

### 1. 對話記錄:hybrid(per-pane sessions + collaboration 容器)

**N 個 session_id**(每 pane 一個,SDK 既有 schema 不動)+ **1 個 collaboration 容器表**綁起來。

```
sessions / messages (SDK 既有)
─ 每個 pane = 1 個 session_id,各自存自己 transcript

cowork_session_ext (既有,加 3 column)
─ collaboration_id TEXT NULL    ← FK to cowork_collaborations
─ pane_name TEXT NULL           ← @backend-coder
─ pane_role TEXT NULL           ← researcher / coder / reviewer / custom
─ pane_position JSON NULL       ← {row, col, w, h, minimized}

cowork_collaborations (新表)
─ id TEXT PK
─ name TEXT                     ← user 給的協作名稱
─ workspace_dir TEXT NULL       ← window 預設(可被 per-pane override)
─ project_id TEXT NULL
─ created_at REAL
─ budget_usd_cap REAL NULL      ← window 級成本上限
```

**為什麼 hybrid**:
- per-pane session → resume / replay / 拆出單獨 session 全可
- collaboration 容器 → 一鍵還原 layout、cross-pane query 用 JOIN 拿、export 一次撈、sidebar 乾淨

**Sidebar 呈現**:
```
📝 一般 session
└── ...
🤝 Collaboration
└── ▼ 「backend-feature」 ($0.83) ← collaboration
    ├── @backend-coder    (Opus, $0.45)
    ├── @frontend-coder   (Sonnet, $0.28)
    └── @reviewer         (Haiku, $0.10)
```

### 2. Cross-pane query:Skill-based、非阻塞、status flag

新 skill `ask-pane`(不寫死 builtin tool — 留 user 改 prompt / 回傳格式空間)。
**永遠立即回**,絕不 block A 的 user。

```yaml
# Skill: ask-pane
input:
  pane_name: string         # @backend-coder
  question: string | null   # 可選;有就嘗試從 B 的 transcript 找答案

output:
  status: "idle" | "running" | "done" | "error"
  current_action: string    # B 正在做什麼(若 running)
  transcript_excerpt: str   # 最近 N 條 user/assistant message
  partial_output: str       # B 已產出但 stream 還沒結束的內容
```

A 的 LLM 看 status 自己決定行為:
- `done` → 直接用 transcript
- `running` + partial 有用 → 「B 目前進度 X,我先用這個」
- `running` + partial 空 → 「B 還在跑(看起來在讀 codebase),要不要等?」回 user

**不做 `wait=true` 模式**:user 會被卡住,LLM 也容易超時。要等,user 自己手動再問。

**底層查詢**:從目前 pane session_id → 反查 `collaboration_id` → JOIN `cowork_session_ext` 找
`pane_name=X` 的另一個 session → 讀那 session 的 messages 表。**不需要 sidecar
RPC call B**,純 DB 查詢,B 跑得多慢都不影響。

### 3. Workspace:per-pane 設定,同檔走 optimistic concurrency

**per-pane `workspace_dir`,可繼承 window 預設**:

| 場景 | 怎麼設 |
|---|---|
| 後端 + 前端不同 repo | window 不設預設,pane A → `~/code/backend`,pane B → `~/code/frontend` |
| 同 repo 不同 module | window 設 `~/code/myapp`,所有 pane 繼承 |
| 同檔協作 | 同上,搭配下方衝突解決 |

**同檔衝突 → 沿用 SDK 既有 `file_state_cache` 的 optimistic concurrency**:

```
1. Pane A Read → 記 snapshot(mtime + hash)
2. Pane A Edit/Write → 檢查 mtime/hash 是否變了
3. 若變了 → tool 回 error:
   "本檔在你讀取後已被 @paneB 修改,請重 Read 並 reconcile。"
4. A 的 LLM 重 Read + decide(自動 merge / 找 user 確認)
```

**File lock 不做**:lock owner 跑慢 → 全 blocked,體驗糟。**Git worktree 留給 user 進階用法**,不內建。

### 4. Pane 命名:role-based + fallback

| 層級 | 範例 |
|---|---|
| Role preset(必選一) | `researcher` / `coder` / `reviewer` / `doc-writer` / `custom` |
| Pane name(預設等於 role,可改) | `@backend-coder`、`@reviewer` |
| 同名衝突自動加數字 | `@coder` → `@coder-1`、`@coder-2` |
| 純 fallback | `@pane-1`、`@pane-2`(user 沒設 role / name) |

**System prompt 自動帶協作 awareness**:

> "你是這 collaboration 的 `@backend-coder`。其他成員:`@frontend-coder`(寫 React)、`@reviewer`(批判)。你的角色是寫 Python FastAPI 後端。"

### 5. Context 隔離

**每 pane 獨立 context window**,無共享。Cross-pane 知識**只透過顯式 skill 拿**,不
ambient inject — 否則 N pane 互相吵 + N 倍 token。

**例外**:window 開始時對所有 pane inject 一次 system-level 廣播
(「你是 @X,旁邊有 @Y、@Z」),之後不再變。

### 6. UI 密度與配置

**Pane 數**:2-4(超過 4 桌機看不下去)。

| Feature | 怎麼做 |
|---|---|
| **Min/Max** | 最小化收成 edge dock badge:`@name + 狀態燈`(綠 idle / 黃 busy / 紅 error) |
| **拖拉重排** | grid drag-and-drop,layout 存進 `cowork_session_ext.pane_position` |
| **Layout 預設** | 1+1 縱切 / 1+1 橫切 / 2+2 grid / 1+2 T-layout,點圖示一鍵套 |
| **Active focus** | `Cmd-1/2/3/4` 切焦點,輸入框只送目前焦點 pane |
| **Pane header** | `@name | model | token count | cost | 狀態燈` |

### 7. 成本可見度

- **Per-pane header inline**:`$0.12` 即時(現 Cowork session-level 已有,搬上 pane header)
- **Window 標題列加總**:`Collaboration: backend-feature ($0.83 total)`
- **Per-pane budget cap optional**:設了 pane border 變紅警示,超 cap pause 那 pane(不影響其他)
- **Window budget cap optional**:超 cap 全 window pause

---

## SDK 已有 vs 要新寫

### 直接借

| 元件 | 用途 |
|---|---|
| `multi_agent/message_bus.py` | Pane 間 pub/sub 通訊基礎(若要做主動通知 `@A: 我寫完 X` 而非純 query) |
| `multi_agent/agent_summary.py` | 生「兩三句摘要」inject 給 cross-pane query 看 |
| `services/file_state_cache.py` | 同檔衝突偵測(已有 Optimistic concurrency 邏輯) |
| `services/side_query.py` | ask-pane 內部如需 summarize B 的 transcript 走它 |
| `core/Conversation` | per-pane 一個 instance |

### 要新寫

| 項目 | 大致範圍 |
|---|---|
| `cowork_collaborations` 表 + helpers | sidecar storage.py 加 ~80 行 |
| `cowork_session_ext` 加 3 column + migration | 小改 |
| `ask-pane` skill(markdown + 對應 Python helper) | `~/.orion/skills/ask-pane/` 新 skill |
| Renderer split layout 組件 | `react-resizable-panels` 或 `react-mosaic`,~300 行 |
| Sidecar `collaboration.*` RPC | create / list / add_pane / remove_pane / update_layout |
| Window-level cost aggregation | 改 cost manager,query collaboration_id 拿 sum |
| Pane header UI | `@name / model / token / cost / status LED` |
| Role preset + system prompt 注入 | 4-5 個內建 role,各帶 system prompt 段落 |
| i18n keys | 4 locale 各 ~15 keys |

---

## 切片順序

### MVP(最小可行)

**範圍:純 UX,不做 cross-pane query**

1. Renderer 加 split pane layout(2 pane 縱切,先不做巢狀 / 拖拉)
2. Sidecar 開兩條獨立 Conversation(各自 session_id)
3. `cowork_collaborations` 表 + UI binding
4. Pane header(name / model / cost,沒狀態燈先)

**測什麼**:驗證「兩對話並排」UX 是不是 user 想像中那樣,**有沒有真的有用**。可能驗證下來發現純並排已足夠,不需要 cross-pane query — 或者反之,沒 cross-pane 完全沒意義。

### Phase 2:Cross-pane

5. `ask-pane` skill + 對應 DB JOIN 查詢
6. Pane 狀態燈(idle / busy / done)
7. Window-level cost aggregation

### Phase 3:Polish

8. Layout 預設 / 拖拉重排
9. Role preset + system prompt 注入
10. Min/max + edge dock badge
11. 鍵盤切焦點
12. Per-pane / window budget cap

### Phase 4:進階

13. Pane 間主動推播(`message_bus` wire — pane 完成時通知其他)
14. Collaboration template(預設配 3 個 role 一鍵建)
15. Replay 整 collaboration(timestamp 排序,pane name 標籤)

---

## 我會擔心的事

1. **模型沒被訓過協作場景**
   - 兩 pane 都搶著 implement(沒分工)
   - 抄對方答案不思考(echo chamber)
   - 跨 pane 引用時 hallucinate 對方說過 X(其實沒)
   - **緩解**:system prompt 強塞角色定位 + cross-pane query 一定要回真 transcript(不要只給 summary)
2. **Cost 爆炸**:N pane = N 倍 spend。**window-level budget cap 不能少**,user 容易忘。
3. **UI 學習曲線**:tmux 是工程師工具,non-tech user 不會用 split / 切 focus。**首次進入要強 onboarding**(「這是 collaboration 模式,N 個 AI 同時跑」)
4. **debug 變難**:單 pane 跑出怪結果好 debug;3 pane 互相 reference 後出問題,trace「哪一步開始歪」很難
5. **桌機 only**:tmux 在小螢幕完全不行。Mobile companion 沒辦法用這 UX,只能看不能編

---

## 不會做的(明確 out-of-scope)

- **8+ pane**:超過 4 桌機看不下去
- **Pane 巢狀(pane 內再切)**:tmux 有但 99% user 不用
- **Git-like branch / merge**:留給 user 用 git worktree 自己幹
- **跨 user collaboration**(co-edit chat):這是 Cowork 其他 feature 範圍
- **手機 / 平板 multi-pane**:UI 不可能,companion mode 只能 monitor

---

## 何時啟動這個 feature

當下面任一發生:

1. 多 user 反映「想同時跟 N 個 model 對話比較結果」/「想要一個 reviewer 即時看我寫的 code」
2. 既有 SDK Coordinator/Swarm 被認真用,user 抱怨「看不見過程,只能等結果」
3. 公司 / 客戶具體場景(對抗式 dev workflow / 平行 PoC 探索)出現

---

## 看完繼續

- [`README.md`](./README.md) — 主要 roadmap
- [`enterprise-scale.md`](./enterprise-scale.md) — 企業規模(這個 feature 在企業場景特別有價值)
- [`../features/cowork.md`](../features/cowork.md) — Cowork 現況
- [`../features/multi-agent.md`](../features/multi-agent.md) — SDK 既有 multi-agent(Coordinator / Swarm,headless 版本)

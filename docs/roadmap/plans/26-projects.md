# Phase 26:Projects(workspace organization)

## 速覽

- **預計時程**:1-2 週(scope 大,內含 backend + DB + frontend + memory 整合)
- **前置 Phase**:Phase 2(session model)、Phase 3(memory)、Phase 11/19(uploads)、Phase 25(REST + 前端 settings tabs)
- **觸發來源**:user 問「Project 這功能在嗎?那它的 uploads 會在哪?」
  → 確認 orion-agent **目前沒有** Project entity,只有 memory 的 type 標籤同名
  → 對齊 Claude.ai 「Projects」模型(多 session + 共享 knowledge + project-scoped instructions)
- **本文件目的**:把 Project 設計討論定下來放著,等真有需求再開
- **狀態**:📝 spec only,**未實作**

## 1. 為何要做(或不做)

### 不該做的理由(優先評估)

orion-agent 目前架構:
- **session 是頂層**(`~/.orion/sessions/<sid>/` 含 transcript / workspace / file-history)
- **memory 是 per-user 跨 session**(Phase 3 已能滿足「跨 session 共享偏好 / context」)
- **uploads 是 per-user 跨 session**(Phase 19 收攏進 `users/<uid>/uploads/`)

Claude.ai 的 Projects 模型對應的需求(「多個 conversation 共享同一批 knowledge / instructions」),
orion-agent 目前用「instructions(Phase 13)+ memory(Phase 3)+ resume(Phase 2)」拼起來大致夠用。

加 Project 是**多一層 hierarchy**,代價:
- DB schema 多一張表 + sessions FK
- REST 多一組 CRUD
- 前端要設計 project switcher / sidebar
- memory scoping 變複雜(per-user 還是 per-project?還是兩層?)
- file uploads 要決定 scope(見 § 3)
- migration:既有 sessions 怎麼歸 project?「default project」?

**先驗證需求**:user 真的需要「同一批檔案 / instructions 給多個 conversation 共用」嗎?
- 若答案是「instructions 共用」→ Phase 13 已能
- 若答案是「知識庫(file)共用」→ 可用 reference memory(Phase 3 reference type)+ skill bundle
- 若答案是「同事協作同 project」→ 需要 multi-user / team feature(更大的 phase)

**只有「個人想把多 session 視覺上分群 + 各自帶不同 knowledge 集合」這個需求才值得做。**

### 該做的理由(若需求成立)

- session list 平鋪在 N 個情境下會難找(個人 + 工作 + side project 混)
- per-session re-attach 同一批 reference docs 很煩
- 不同 project 的 memory 互相污染(目前 user memory 全 session 共享)

## 2. 設計選項

### 2.1 Disk layout(uploads 該放哪)

#### 選項 A:project 隸屬 user

```
~/.orion/
├── users/<uid>/
│   ├── memory/                          # 既有
│   ├── uploads/                         # Phase 19 既有
│   └── projects/<pid>/
│       ├── instructions.md
│       ├── uploads/                     # project-scoped uploads
│       └── memory/                      # 可選:project-scoped memory
└── sessions/<sid>/                      # 既有,加 project_id metadata
```

✅ 跟 Phase 19 layout 一致延伸
✅ 單機 / 單 user 場景自然
❌ multi-user team 場景擴展性差

#### 選項 B:project 平行 user

```
~/.orion/
├── users/<uid>/...                      # 既有
├── projects/<pid>/                      # 頂層
│   ├── members.json                     # 預留 multi-user
│   ├── instructions.md
│   ├── uploads/
│   └── memory/
└── sessions/<sid>/                      # 加 project_id metadata
```

✅ 擴 multi-user / team 容易
❌ 對單機 / 單 user 過度設計
❌ 需要 access control 邏輯(user X 能看到哪些 project?)

#### 選項 C:upload 中立,project 是 DB 關聯

```
~/.orion/users/<uid>/uploads/<uuid>.ext  # 不變
DB: project_uploads(project_id, upload_id) 關聯表
```

✅ 同 upload 跨 project 引用便宜
✅ 跟 Phase 19 layout 兼容,無 disk 結構變動
❌ instructions / project-scoped memory 仍要找地方(無法純 DB 解決)

### 2.2 推薦組合:**A + C 混合**

- Disk 上:project metadata / instructions 走 A(`users/<uid>/projects/<pid>/`)
- Uploads:走 C(per-user,DB 關聯)
- Memory:project-scoped memory **不做**(初期),user memory 全 session 共享(現況)

理由:
- uploads 內容大、跨 project 引用機會高 → 中立 + 關聯
- instructions / metadata 小、明確屬於某 project → 直接 disk
- memory 加 project scope 會讓 ranker 邏輯翻倍複雜,先放著看需求

## 3. 任務拆解(若要做)

### 3.1 Backend schema

- [ ] DB migration:`projects` table(id, user_id, name, description, instructions, created_at, updated_at)
- [ ] DB migration:`sessions` table 加 `project_id` FK(nullable — 沒歸屬 = "default")
- [ ] DB migration:`project_uploads`(project_id, upload_id, attached_at)

### 3.2 Backend API

- [ ] `api/routes/projects.py`:
  - `GET /me/projects` → list
  - `POST /me/projects` body `{name, description}` → create
  - `GET /me/projects/{pid}` → detail(含 instructions)
  - `PUT /me/projects/{pid}` → update
  - `DELETE /me/projects/{pid}` → delete(sessions 解綁到 default)
  - `POST /me/projects/{pid}/uploads/{upload_id}` → attach
  - `DELETE /me/projects/{pid}/uploads/{upload_id}` → detach
- [ ] `api/routes/sessions.py` 加 `project_id` 欄位到 create / update
- [ ] 改 chat WebSocket:session 啟動時把 project 的 instructions / uploads 注入 prompt context

### 3.3 Frontend

- [ ] Sidebar 加 project switcher(現況 session list 變成「該 project 的 session list」)
- [ ] 「All sessions」/「default」當 fallback view(沒 project_id 的 session 全部歸這)
- [ ] Project settings 頁:name / instructions(reuse Phase 13 IconEditor)/ uploads attach UI
- [ ] new chat 時可選 project(或保留當下選中的 project)

### 3.4 Memory 整合(待定)

- [ ] 評估:project-scoped memory 真有需求嗎?
- [ ] 若要做:`users/<uid>/projects/<pid>/memory/` + ranker 兩層 merge(per-project 優先,user memory 補)
- [ ] 若不做:文件明確說「memory 仍是 per-user 跨 project」

### 3.5 Migration

- [ ] 既有 sessions 沒 project_id → 自動視為 "default project"(顯示用,DB 不必塞)
- [ ] 或:首次升級啟動時建 "Inbox" project 把 orphan sessions 歸進去
- [ ] **避免強迫使用者選邊** — 不用 project 也能正常用

### 3.6 收尾

- [ ] 補測試 + 寫 Phase 26 完工心得
- [ ] 更新 `.env.example`(若有新 env)
- [ ] 更新 docs:Phase 11/19 docstring 註明 project attachment

## 4. 設計決策(待定 / pre-decided)

### 4.1 Project_id 用 UUID 還是 slug?

- UUID:DB-friendly、不撞、不需 escape
- Slug:URL 漂亮(`/projects/my-side-project`)、user 看得懂

**傾向 UUID + 顯示 name**(跟 session 同模式),簡化邏輯。

### 4.2 「Default project」是真 entity 還是虛擬?

- 真 entity:每 user 註冊時自動建 `Default` project,FK 不能 null
- 虛擬:`project_id NULL = default`,UI 顯示「(no project)」或「All」

**傾向虛擬**:減少 migration 痛(既有 sessions 不必回填),DB 更乾淨。

### 4.3 Project instructions 怎麼合進 system prompt?

Phase 13 instructions 是 per-user。Project 也要 instructions → 兩層:
- prompt assembly 順序:base → user instructions → project instructions → session-specific
- 最具體 / 局部的覆蓋更廣的

### 4.4 Sessions 能不能跨 project 移動?

UI 允許「move to project」操作?還是創 session 時鎖死 project?

**傾向允許移動**:session 是 user-owned 資料,project 是分類標籤,移動該便宜。

## 5. 相關 code(改動範圍)

- 新:`orion_agent/storage/project.py` — Project CRUD logic
- 新:`orion_agent/api/routes/projects.py`
- 新:`orion_agent/api/db/models/project.py`(SQLAlchemy model)
- 改:`orion_agent/api/db/models/session.py` 加 `project_id` FK
- 改:`orion_agent/api/routes/sessions.py` 支援 project filter
- 改:`orion_agent/prompt/assembler.py` 注入 project instructions
- 改:`orion_agent/input/upload.py` 支援 project-attached uploads(用 § 2.1 C 方案 DB 關聯)
- 改:`frontend/src/components/Sidebar.tsx` — project switcher
- 新:`frontend/src/components/ProjectSettings.tsx`
- alembic migration:`add_projects_table.py`、`add_project_id_to_sessions.py`、`add_project_uploads.py`

## 6. 風險與緩解

| 風險 | 緩解 |
|---|---|
| 加了一層 hierarchy 但 user 不買單,新增複雜度沒回報 | § 1 「不該做的理由」優先評估;若做,UI 設計成「project 可用可不用」 |
| memory ranker 加 project scope 後變慢 | 初期不做 project memory(§ 2.2);若要做,benchmark 鎖時間 |
| 既有 sessions 強制歸 project,user 抗拒 | 用「虛擬 default」(§ 4.2),不強迫遷移 |
| upload 中立 + DB 關聯 → cleanup 時 orphan upload 找不到 | 配 phase 19 風格做 GC(reference count 歸零就刪 disk) |
| Phase 25 已建 frontend Settings tabs,要再加 Projects tab 還是頂層? | 設計時測 user flow:project 切換頻率高 → 不能埋在 Settings,該頂層 sidebar |

## 7. 什麼時候該真正啟動這 phase?

**觸發訊號**:
1. user(們)抱怨 session list 找不到舊 conversation(管理痛)
2. 同一批 reference 檔被 attach 進多個 conversation 三次以上(複用痛)
3. 想跑「個人 / 工作 / 學習」分群,各自帶不同 instructions

任一條成立才開動。**目前都沒**,先放著。

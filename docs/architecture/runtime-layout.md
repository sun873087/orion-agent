# Runtime layout — orion-agent 的 config / data 在哪

source code 結構見 [`packages.md`](./packages.md)。本文只講 **runtime** 設定 / 資料散落的 4 個位置(+ extra_dirs runtime 注入),後者覆蓋前者(last-wins):

```
1. bundled            ← 套件附,跟著 pip install / uv sync
2. system             ← ~/.orion/                  全 server 共用(admin)
3. project            ← <cwd>/.orion/              專案內(commit 進 repo)
4. user               ← ~/.orion/users/<uid>/      per-tenant
+ extra_dirs          ← runtime 注入(plugin / test)
```

---

## 1. Bundled(套件內)

跟著 `pip install` / `uv install` 一起。**不該人手改**(`git pull` 會被覆蓋,要客製改其他層)。

```
packages/orion-sdk/src/orion_sdk/skills/bundled/
├── README.md                         # 這份文件 + skills 來源說明
└── <skill-name>/SKILL.md             # 12 個內建 skill(be-concise / simplify / loop / goal / agent ...)
```

模組:`orion_sdk.skills.loader._bundled_skills()`。透過 `importlib.resources` 讀,
wheel / zip 安裝也能拿。

---

## 2. System(`~/.orion/`)

**全 server 共用** — admin 級設定,所有 tenant / project 都看得到。

```
~/.orion/
├── settings.json                     # global permission rules / hooks / 偏好
├── instructions.md                   # CLI 模式全域 prompt 注入(取代上游 CLAUDE.md)
├── mcp.json                          # global MCP servers
├── skills/                           # admin 加的 skills(覆蓋 bundled 同名)
│   └── <name>/SKILL.md
├── plugins/                          # admin 安裝的 plugins
│   └── <plugin-id>/plugin.json
├── sessions/                         # 每 conversation 一個子目錄(詳見 § 2a)
│   └── <session-uuid>/
│       ├── transcript.jsonl          # append-only JSONL,所有 events
│       ├── meta.json                 # 可選元資料
│       ├── tool-results/             # 大 tool 輸出持久化(>= 100KB)
│       ├── file-history/             # Edit/Write 寫前快照(Phase 19 LRU 100)
│       └── workspace/                # session-isolated cwd
├── plans/                            # plan mode 寫的計畫檔
├── uploads/                          # ⚠️ legacy(Phase 11 起初位置,Phase 19 之後)
│   └── <user_id>/<upload_id>.<ext>   #     僅 read fallback,新寫已搬到 users/<uid>/uploads/
└── users/                            # per-tenant 子目錄根(下個區段)
    └── <user_id>/...
```

| 路徑 | 模組 | env override |
|---|---|---|
| `~/.orion/skills/` | `skills/loader.py:_system_skills_dir` | `ORION_SKILLS_DIR` |
| `~/.orion/settings.json` | `tools/config/config_tool.py` | `ORION_HOME` |
| `~/.orion/instructions.md` | `prompt/context.py` | — |
| `~/.orion/mcp.json` | `mcp/config.py` | — |
| `~/.orion/plugins/` | `plugins/loader.py:_user_plugins_dir`(誤名,實際 system 級)| `ORION_PLUGINS_DIR` |
| `~/.orion/sessions/` | `storage/session.py`(詳細見 § 2a)| `ORION_SESSIONS_DIR`(整個 sessions root)|
| `~/.orion/plans/` | `tools/special/enter_plan_mode.py` | `ORION_HOME/plans/` |
| `~/.orion/uploads/` (legacy) | `input/upload.py:_legacy_user_uploads_dir` | `ORION_HOME` |

> **誰能寫?** Admin / 部署者(server 跑 process 的 user)。**Web chat tenant 寫不到**(沒對應 REST endpoint)。

---

## 2a. Session 子結構(`~/.orion/sessions/<session-uuid>/`)

每個 conversation 一個獨立 UUID v4 子目錄,所有跟該 conversation 綁定的 state 都收在裡面。session 刪除 = `rm -rf <sid>/` 一次清光。

```
~/.orion/sessions/<session-uuid>/
├── transcript.jsonl              # ★ 所有 events(append-only JSONL,每行一筆)
├── meta.json                     # session 元資料(可選,某些路徑下不寫)
├── tool-results/                 # 大 tool 輸出持久化(第 2 層 budget)
│   └── <tool_use_id>.txt
├── file-history/                 # Edit/Write 寫前快照(undo / 審計)
│   └── <hash16>.snap
└── workspace/                    # session-isolated cwd,模型工具產出落這
    └── ...                       # Bash / Write / Edit 的檔案
```

| 路徑 | 內容 | 模組 |
|---|---|---|
| `transcript.jsonl` | conversation 全部 events,`kind` 欄位分四種(見下表) | `storage/session.py` |
| `meta.json` | session 起始時間、provider、model | `storage/paths.py:SessionPaths.meta` |
| `tool-results/<tool_use_id>.txt` | 大 tool 輸出(>= 100KB)→ 寫檔 + transcript 換成 preview | `storage/tool_result.py` |
| `file-history/<hash>.snap` | Edit/Write 寫檔前舊內容快照;同 hash dedupe;**Phase 19 LRU 預設上限 100** | `storage/file_history.py` |
| `workspace/` | per-session 隔離 cwd;web chat 多 user 同時跑各自的 Bash/Write 不撞;CLI 也吃這個 | `storage/paths.py:SessionPaths.workspace_dir`、`api/routes/sessions.py` |

### transcript.jsonl 的 record kinds

每行一筆 JSON,`kind` 欄位 discriminate(`storage/session.py:87-122`):

| `kind` | 何時寫 | 主要欄位 |
|---|---|---|
| `session-meta` | session 開始 | `session_id` / `started_at` / `provider` / `model` / `system_prompt` |
| `message` | 每則 NormalizedMessage(user / assistant / tool_result) | `role` / `content` |
| `tool-result-replacement` | 第 3 層 budget 把舊 tool result aggregate 後寫的決策 | `tool_use_id` / `replacement` |
| `transition` | query_loop 終結 | `reason` 為 `natural_stop` / `aborted` / `max_turns_reached` / `empty_response` |

### DB messages 表(Phase 27 之後)

當 `ORION_DB_URL` 啟用時(SQLite / Postgres),**訊息 dual-write**:
- 每筆 `record_message` 同時寫進 JSONL **和** `messages` 表(`storage/db/models.py:175`)
- Resume 時 `DbSessionManager` 優先 `fetch_db_messages()` 讀 DB,DB 空才 fallback JSONL
- transitions / replacements **仍只在 JSONL**(尚未做對應 DB 表,Phase 27 範圍限 messages)
- JSONL 即使啟用 DB 仍寫,作為 audit log + transitions/replacements 載體

CLI / in-memory SessionManager 模式無 engine,純走 JSONL — 行為不變。

**resume**(`storage/resume.py`)就是讀整份 JSONL(+ DB messages 若有),把 `state_messages` + `ContentReplacementState` 完全重建,繼續對話。

### GC 與生命週期

| 子目錄 | GC 狀態 |
|---|---|
| `transcript.jsonl` | 無 GC;Phase 20(規劃中)可選 gzip 壓縮 |
| `tool-results/` | **無 GC** — session 完工不自動清,長 session 會堆 |
| `file-history/` | ✅ Phase 19 mtime LRU,`ORION_FILE_HISTORY_MAX_SNAPSHOTS=100` |
| `workspace/` | **無 GC** — 永久留著(模型產出的檔案 user 可能要看);需要手動清 |

session 本身的 GC(整個 `<sid>/` 何時刪)目前**沒做** — 由 user 透過 web chat 「Delete session」按鈕觸發,或 admin 手動 `rm -rf`。

### 環境變數

| 變數 | 預設 | 說明 |
|---|---|---|
| `ORION_SESSIONS_DIR` | `~/.orion/sessions/` | 整個 sessions root 換位置;測試 conftest.py 用 `tmp_path` 隔離 |
| `ORION_FILE_HISTORY_MAX_SNAPSHOTS` | `100` | 每 session 的 `file-history/` 上限(Phase 19);非正整數 fallback 預設 |

---

## 2b. Cowork host(`~/.orion/sessions/cowork.db` + co-located project resources)

Cowork(`apps/orion-cowork/`)是**第三個 host**,跟 CLI / chat-api 並列;以前在獨立 root `~/.orion-cowork/`,Phase 31-G 後統一到 `~/.orion/`,**skills / memory / mcp / users 整套共用** — 一邊裝兩邊都看見。差別只在 **sessions 存法**:

```
~/.orion/
├── sessions/
│   ├── cowork.db                   ★ Cowork 用單一 SQLite(本節)
│   └── <session-uuid>/             既有 CLI / chat-api JSONL pattern(§ 2a)
├── skills/  users/  mcp.json ...   ✅ 共用 — Cowork 跟 CLI 同源
└── blobs/                          ★ Cowork 附件 blob store(content-hash 去重)
```

### 為什麼 Cowork 走 SQLite

CLI / chat-api 走「per-session JSONL 檔」適合單機開發 / 多 tenant server。Cowork 是
**桌面 chat app**,需要做的事 JSONL pattern 不擅長:

- Sidebar 一次列幾百個對話(LIST / COUNT / ORDER BY) → SQL 比逐檔讀快幾百倍
- 跨 session 全文搜尋對話內容 → SQL `LIKE`(未來 FTS5)
- 富 metadata(starred / scheduled_by / project_id / workspace_dir)需要 join / index
- 對話多會議 attachments 的 dedup → content-hash blob store

所以 Cowork 走 **單一 `cowork.db`** + 旁邊的 `blobs/` content-addressed store。

### cowork.db 表結構

詳細 schema 見 [`features/storage.md`](../features/storage.md);摘要:

| 表 | 來源 | 用途 |
|---|---|---|
| `sessions` | SDK 共用 schema | 每個對話一筆(provider / model / created_at) |
| `messages` | SDK 共用 schema | content_json blob,append-only;`metadata_json` 帶 `compacted_out` flag(soft delete) |
| `conversation_metadata` | SDK 共用 schema | title / 自動命名 / per-session 偏好 |
| `cowork_session_ext` | Cowork 擴充 | `workspace_dir` / `project_id` / `scheduled_by_*` / `starred` |
| `cowork_projects` | Cowork 擴充 | 專案定義(name / workspace_dir / custom_instructions) |
| `cowork_prefs` | Cowork 擴充 | KV pairs(default_workspace_dir / user_instructions / disabled_tools 等) |
| `cowork_schedules` | Cowork 擴充 | 排程 + Loop(`target_session_id` NULL = schedule,有值 = loop bound 到既有 session) |

### blob store(`~/.orion/blobs/`)

每個附件圖檔依 SHA-256 取檔名(`<hash>.bin`)。重複貼同一張圖 → 同 hash → 只存一份。
跟 CLI 共用 pool(blob_id 是 hash 不會撞)。message rows 內附件用 `{ type: 'image', blob_id }` ref,讀取時 lazy hydrate。

### Cowork host 跟其他 host 同跑

Cowork 跟 CLI / chat-api 可同時跑(各寫各的 DB):

| Host | sessions 寫到 | skills / memory / mcp |
|---|---|---|
| Cowork | `~/.orion/sessions/cowork.db` | `~/.orion/{skills,users,mcp.json}` |
| CLI | `~/.orion/sessions/<uuid>/transcript.jsonl` | 同上,共用 |
| chat-api(若有 SQLite mode) | `~/.orion/sessions/...db`(視部署) | 同上,共用 |

SQLite 走 WAL 模式 → 同時讀寫不 lock。User 在 Cowork 裝 skill,CLI 立刻看見;反之亦然。

### 環境變數(Cowork-only)

| 變數 | 預設 | 說明 |
|---|---|---|
| `ORION_COWORK_DATA_DIR` | `~/.orion` | 整個 Cowork data root override(e2e / 多實例隔離);內部仍走 `<root>/sessions/cowork.db` |

---

## 3. Project(`<cwd>/.orion/`)

**單一專案**內共用 — 通常 commit 進 git repo,跟程式碼一起 distribute。

```
<your-project>/
└── .orion/
    ├── settings.json                 # 專案級 permission rules / hooks / 偏好(commit)
    ├── settings.local.json           # 個人 dev override(放 .gitignore)
    ├── instructions.md               # 專案 prompt 注入(CLI 模式)
    ├── mcp.json                      # 專案 MCP servers(覆蓋 ~/.orion/mcp.json)
    ├── skills/                       # 專案 skills
    │   └── <name>/SKILL.md
    └── plugins/                      # 專案 plugins
        └── <plugin-id>/plugin.json
```

| 路徑 | 模組 |
|---|---|
| `.orion/skills/` | `skills/loader.py:_project_skills_dir` |
| `.orion/settings.json` | `permissions/persistence.py`(scope=project) |
| `.orion/settings.local.json` | 同上(scope=local) |
| `.orion/instructions.md` | `prompt/context.py` |
| `.orion/mcp.json` | `mcp/config.py` |
| `.orion/plugins/` | `plugins/loader.py:_project_plugins_dir` |

> ⚠️ **Web chat 模式 project 層幾乎沒用**:server 的 cwd 是部署目錄,**所有 tenant 都共用同一個 cwd** —
> 等於變成額外一份 system 級。專案級設計主要服務 **CLI 模式**(orion run / orion serve 從專案目錄起)。

---

## 4. User(`~/.orion/users/<user_id>/`)

**per-tenant 私人空間** — 在多用戶 web chat 場景下,各 tenant 自己的 skills / memory / uploads。

```
~/.orion/users/<user_id>/
├── memory/                           # auto-memory(MEMORY.md + 散件)
│   └── MEMORY.md
├── uploads/                          # web chat 上傳檔(Phase 19 後 canonical 位置)
│   └── <upload_id>.<ext>
└── skills/                           # 自訂 skills(覆蓋 system / bundled 同名)
    └── <name>/SKILL.md
```

| 路徑 | 模組 | env override |
|---|---|---|
| `~/.orion/users/<uid>/memory/` | `memory/paths.py:user_memory_dir` | — |
| `~/.orion/users/<uid>/uploads/` | `input/upload.py:_user_uploads_dir` | `ORION_HOME` |
| `~/.orion/users/<uid>/skills/` | `skills/loader.py:_user_skills_dir` | `ORION_USER_SKILLS_DIR`(整批根目錄) |

> `user_id` 來自 JWT(web chat)或 `--user-id` CLI flag(預設 `default`)。
> path traversal 防護:`/`、`\` → `_`,leading `.` 去掉。

---

## 5. extra_dirs(runtime 注入)

不是磁碟固定位置,是 `load_all_skills(extra_dirs=[...])` runtime 參數。最高優先級。

兩個典型用途:

1. **Plugin** 帶 skill — plugin loader 把 plugin 自帶的 skills dir 注入
2. **測試** 一次性 inject,不污染 env / `~/.orion/`

```python
load_all_skills(
    extra_dirs=[Path("/tmp/test_skills")],   # 測試
    user_id="alice",                         # 載入 alice 的 user dir
)
```

---

## 6. Model proxy(opt-in,Phase 31-X)

跟前 5 個位置不同 — 這是**獨立 process / service**,不是磁碟資料夾。
但 runtime 拓樸有影響,所以列在這。

### Process model

```
不啟 proxy(預設 / fallback):
   每個 host process 直連對應 provider HTTP
   API key 從各 host 的 .env / env 讀

啟 proxy:
   一台機跑 orion-model-proxy(:9090),所有 host 走它
   API key 只放 proxy 那台機,host 端不再需要
```

### Host 端切換

由 env var 控,**code 完全不動**:

| Env | 意義 |
|---|---|
| `ORION_MODEL_PROXY_URL` | Proxy base URL(e.g. `http://127.0.0.1:9090`)— 設了就走 proxy |
| `ORION_MODEL_PROXY_KEY` | Bearer token,跟 proxy server 那邊 `ORION_MODEL_PROXY_KEY` 一致 |

Host 怎麼 dispatch:`orion_model.provider.get_provider()`:

1. `set_test_provider_factory()` 設了 → fake provider(e2e test)
2. **`ORION_MODEL_PROXY_URL` 設了 → `HttpProxyProvider`**
3. 否則直連對應 `AnthropicProvider` / `OpenAIProvider` / `OllamaProvider`

### Proxy 端 env

| Env | 預設 | 用途 |
|---|---|---|
| `ORION_MODEL_PROXY_HOST` | `127.0.0.1` | listen host(對外服務改 `0.0.0.0`) |
| `ORION_MODEL_PROXY_PORT` | `9090` | listen port |
| `ORION_MODEL_PROXY_KEY` | (unset) | 需要的 Bearer token;unset = 不認證(本機 dev) |
| `ANTHROPIC_API_KEY` | — | 上游 provider key,從 host 移到這 |
| `OPENAI_API_KEY` | — | 同上 |
| `OLLAMA_HOST` | `http://127.0.0.1:11434` | Ollama daemon 位置 |

### 部署形態

| 形態 | URL | 適用 |
|---|---|---|
| 本機 sidecar | `http://127.0.0.1:9090` | 單人多 app(`make dev-model-proxy`) |
| 內網 | `http://proxy.lan:9090` | team 共用,多裝置 |
| 雲端 | `https://proxy.example.com` | 跨地理 / 託管(需 nginx + TLS) |

詳見 [`../features/model-proxy.md`](../features/model-proxy.md)。

---

## 跟上游 Claude Code 的差異

| 項目 | 上游 Claude Code | orion-agent |
|---|---|---|
| 基底資料夾名 | `.claude/` | `.orion/`(避免衝突) |
| Project memory 檔 | `CLAUDE.md` / `CLAUDE.local.md` | `instructions.md`(`.orion/` 內) |
| Bundled skills | 17 個 TS 函式 | 12 個 markdown 檔(8 個從上游移植 + 4 個 orion 原有:loop / goal / agent / skillify 等) |
| `commands/` legacy 目錄 | 有 | **無**(Phase 11c 之後評估) |
| `agents/` 自定 agent | 有 | **無**(Phase 24 multi-agent tool 整合時做) |
| Per-user / multi-tenant | 單機假設,沒 user 維度 | `~/.orion/users/<uid>/`(JWT 推) |

---

## 六個位置一句話總結

1. **bundled** = 內建,跟程式走
2. **system**(`~/.orion/`)= 整台機器共用,admin 控
3. **project**(`<cwd>/.orion/`)= 跟 repo 走,團隊共用,**web chat 模式幾乎沒用**
4. **user**(`~/.orion/users/<uid>/`)= 個人,跨 project,**多租戶必用**
5. **extra_dirs**(runtime)= 程式 / plugin 注入,最 dynamic
6. **model proxy**(opt-in service)= API key / cost 集中點,host 端 env 切過去就走

要客製預設行為:
- 全 server 改 → 動 system
- 整個 repo 改 → 動 project + commit
- 自己用 → 動 user

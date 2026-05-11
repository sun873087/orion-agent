# Project Layout — orion-agent 的目錄結構

orion-agent 的 runtime 設定 / 資料散在 4 個地方,**後者覆蓋前者**(last-wins):

```
1. bundled            ← 套件附,跟著 pip install
2. system             ← ~/.orion/                  全 server 共用(admin)
3. project            ← <cwd>/.orion/              專案內(commit 進 repo)
4. user               ← ~/.orion/users/<uid>/      per-tenant
+ extra_dirs          ← runtime 注入(plugin / test)
```

本文逐層列出**每個位置會有什麼**,以及對應的 module / env var。

---

## 1. Bundled(套件內)

跟著 `pip install` / `uv install` 一起。**不該人手改**(`git pull` 會被覆蓋,要客製改其他層)。

```
api/src/orion_agent/skills/bundled/
├── README.md                         # 這份文件 + skills 來源說明
└── <skill-name>/SKILL.md             # 10 個內建 skill(be-concise / simplify / loop ...)
```

模組:`orion_agent.skills.loader._bundled_skills()`。透過 `importlib.resources` 讀,
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
├── sessions/                         # 所有 session 的 transcript
│   └── <session-uuid>/transcript.jsonl
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
| `~/.orion/sessions/` | `storage/session.py` | — |
| `~/.orion/plans/` | `tools/special/enter_plan_mode.py` | `ORION_HOME/plans/` |
| `~/.orion/uploads/` (legacy) | `input/upload.py:_legacy_user_uploads_dir` | `ORION_HOME` |

> **誰能寫?** Admin / 部署者(server 跑 process 的 user)。**Web chat tenant 寫不到**(沒對應 REST endpoint)。

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

## 跟上游 Claude Code 的差異

| 項目 | 上游 Claude Code | orion-agent |
|---|---|---|
| 基底資料夾名 | `.claude/` | `.orion/`(避免衝突) |
| Project memory 檔 | `CLAUDE.md` / `CLAUDE.local.md` | `instructions.md`(`.orion/` 內) |
| Bundled skills | 17 個 TS 函式 | 10 個 markdown 檔(8 個從上游移植 + 2 個 orion 原有) |
| `commands/` legacy 目錄 | 有 | **無**(Phase 11c 之後評估) |
| `agents/` 自定 agent | 有 | **無**(Phase 24 multi-agent tool 整合時做) |
| Per-user / multi-tenant | 單機假設,沒 user 維度 | `~/.orion/users/<uid>/`(JWT 推) |

---

## 五個位置一句話總結

1. **bundled** = 內建,跟程式走
2. **system**(`~/.orion/`)= 整台機器共用,admin 控
3. **project**(`<cwd>/.orion/`)= 跟 repo 走,團隊共用,**web chat 模式幾乎沒用**
4. **user**(`~/.orion/users/<uid>/`)= 個人,跨 project,**多租戶必用**
5. **extra_dirs**(runtime)= 程式 / plugin 注入,最 dynamic

要客製預設行為:
- 全 server 改 → 動 system
- 整個 repo 改 → 動 project + commit
- 自己用 → 動 user

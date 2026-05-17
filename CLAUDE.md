# orion-agent — Claude Code 工作指引

本檔是給 **Claude Code(本 CLI tool)** 看的 project-level 設定,每次在這 repo
啟動會自動讀進 context。User instructions 仍以 `~/.claude/CLAUDE.md` 為準
(用 zh-TW 回覆等全域偏好)。

## 專案是什麼

orion-agent — 模組化 AI agent runtime。3 個 app + 2 個 package,共用 SDK:

```
packages/
├── orion-sdk       Agent loop / tools / skills / memory / MCP / storage 核心
└── orion-model     LLM provider 抽象(Anthropic / OpenAI / etc.)

apps/
├── orion-cli       CLI(終端機 chat,各 tenant 走自己的 sessions/<uuid>/JSONL)
├── orion-chat      Web chat-api(FastAPI + JWT + Postgres-ready,multi-tenant)
└── orion-cowork    桌面 chat app(Electron + React + Python sidecar,SQLite)
```

三個 app 都 `import orion_sdk` 跑 agent loop,差別只在「sessions 怎麼存」
跟「host 整合面」。

## 跑起來(常用命令)

```bash
# Python deps(workspace 模式)
uv sync

# Node deps(只在 Cowork app 下)
cd apps/orion-cowork && pnpm install

# 跑 Cowork(Electron + sidecar)
cd apps/orion-cowork && pnpm dev

# Type check(全 Cowork)
cd apps/orion-cowork && pnpm typecheck

# Python tests
cd packages/orion-sdk && uv run pytest -x -q --ignore=tests/integration
cd apps/orion-cowork/sidecar && uv run pytest -x -q
```

## Runtime 資料位置(Phase 31-G 統一後)

**所有 host 共用 `~/.orion/` root**。skills / memory / mcp.json / users
共用(一邊裝兩邊都看見);sessions 透過子目錄 + 不同檔名隔離:

```
~/.orion/
├── skills/                          ✅ system skills(共用)
├── users/<u>/skills/                ✅ per-user(共用)
├── users/<u>/memory/                ✅ memory(共用)
├── mcp.json                         ✅ global MCP servers(共用)
├── settings.json                    ✅ CLI / chat-api 設定(Cowork 不用)
├── permissions.json                 ✅ global permission rules(共用)
├── sessions/
│   ├── cowork.db                    Cowork SQLite(`cowork_*` 擴充表 + SDK 共用 messages/sessions 表)
│   └── <uuid>/                      CLI / chat-api JSONL pattern(per-session 子目錄)
├── blobs/                           ✅ content-hash blob store(Cowork 附件;CLI 也共用)
└── plans/                           Plan mode 計畫檔
```

詳細見 `docs/architecture/runtime-layout.md`。

## 不要做的事

- **`.env` 不 commit** — API keys 在 `.env`(已 `.gitignore`),覆蓋 git add 時不要把它加進去
- **不改 git config** — 即使是 local repo config(`.git/config`)也先問 user 再動
- **`--no-verify` / `--amend`** — 沒明確要求不要用;hook fail 用新 commit 修
- **直接 push 不確認** — push / force-push / 改 default branch 都是不可撤外部動作,先問
- **過度抽象** — 三行重複 < 早期抽象。Bug fix 不該帶附帶清理,單次操作不該蓋 helper
- **多餘錯誤處理** — 內部 code / framework 保證的不要再 validate,只在系統邊界(user input / 外部 API)做
- **填註解解釋 WHAT** — 變數命名好的話 WHAT 是自明的;只在 **WHY 不顯然** 時寫(隱性 constraint / 微妙 invariant / workaround)

## 風格

### Python
- 用 `from __future__ import annotations`(repo 已預設,保持)
- Type hints 用 PEP 604(`str | None` 不是 `Optional[str]`)
- async-first;file I/O 用 `pathlib.Path`,DB 走 SQLAlchemy async
- 註解語言 zh-TW(跟既有對齊);docstring 同
- Logging 用 stderr(sidecar `print(..., file=sys.stderr)`,別污染 stdio RPC)

### TypeScript / React
- Strict TS — 沒 `any` 偷渡;`unknown` 進 narrow
- Zustand for state,no redux
- Tailwind for styling(主題用 `bg-bg-*` / `text-fg-*` semantic tokens,不直接 hex)
- i18n 4 個 locale:zh-TW / zh-CN / en / ja,加 key 都要 4 處同步
- Electron contextBridge 暴露 API 命名 `xxxApi`(避免撞 Chrome 內建 `window.scheduler` 之類)

### Commit message
- 中文 + 對齊既有風格 `feat(scope): ...` / `fix(...)` / `docs:` / `refactor(...)`
- subject 一行(60-80 字內),body 解 WHY + 主要 trade-off
- Co-Author trailer 用 `Claude Opus 4.7 (1M context) <noreply@anthropic.com>`

## 文件導覽(`docs/`)

| 我要... | 去 |
|---|---|
| 整體拓樸 | `docs/architecture/README.md` |
| 5 個 package 各做什麼 | `docs/architecture/packages.md` |
| 資料 / 設定在哪個目錄 | `docs/architecture/runtime-layout.md` |
| 跑起來 / 跑測試 | `docs/guides/setup.md`、`docs/guides/run-tests.md` |
| 各 feature 設計 | `docs/features/*.md`(`cowork.md` / `tools.md` / `skills.md` / `storage.md` / ...) |
| Roadmap | `docs/roadmap/README.md` |

## 重要架構決策(已凍)

- **3 app 不共用 sessions DB** — Cowork 走 SQLite(`cowork.db`),CLI / chat-api 走 JSONL(`sessions/<uuid>/transcript.jsonl`)或 Postgres;skills / memory / mcp 跨 host 共用 `~/.orion/`
- **Cowork sidecar 只跑 orion-sdk,不走 chat-api** — 本機單機不需要 JWT / HTTP / CORS,走 stdio JSON-RPC 直連
- **Tool 註冊由 host 控** — SDK 只定義 tool spec,執行邏輯 host 透過 callback 注入(`ScheduleCreate` / `LoopCreate` 等)
- **Skill `cowork_visible: false`** — bundled skill 內含 CLI-only 場景(`batch` / `update-config`)在 Cowork popover + Settings UI 隱藏,LLM 仍可載

## Sidecar 連 SDK 的注意點

- Cowork sidecar `__main__.py` **不再 override** `ORION_USERS_DIR` / `ORION_SKILLS_DIR`(Phase 31-G 後)— SDK 預設 `~/.orion/{users,skills}/` 就對齊
- 加新 sidecar feature 涉及 path:用 `storage.data_dir()` 拿 root,sub-path 用 `data_dir() / "..."` 拼接;不要直接寫 `Path.home() / ".orion-cowork"` 之類
- 新加 builtin tool 需要 host 注入 callback:擴 `build_default_tool_set()` 參數 + sidecar `_build_conversation()` 提供 callback

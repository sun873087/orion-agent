# Phase 30:Monorepo 重構 — 核心抽 SDK,衍生四個子產品

## 速覽

- **預計時程**:全職 4-6 週 / 業餘 8-12 週
- **前置 Phase**:Phase 0-29(現有 orion-agent 全部功能)
- **狀態**:📝 spec only,**未實作**
- **觸發來源**:把 `api/src/orion_agent/` 一坨拆成可獨立交付的 SDK + 多個應用,以便:
  - 新增 PC 桌機應用 **Cowork**(Electron + React,單機本地 agent)
  - 把 LLM provider 抽象層 `orion-model` 獨立成可被「沒有 agent loop 的場景」單獨使用的套件
  - 讓 CLI / Chat API / Cowork 三個應用平行存在,各自演化不相互卡

## 1. 目標架構

### 1.1 依賴圖

```
                packages/orion-model/        ← 純 LLM provider 抽象
                  (anthropic / openai / 事件翻譯 / pricing)
                          ▲
                          │ depends on
                          │
                packages/orion-sdk/          ← agent core
                  (Conversation, tools, mcp, sandbox,
                   memory, compact, multi-agent, ...)
                          ▲
                          │ depends on
        ┌─────────────────┼─────────────────┐
        │                 │                 │
   orion-cli         orion-chat/api    orion-cowork
   Typer + stdin    FastAPI + WS+JWT   Electron + sidecar
                         ▲
                         │ HTTP / WS
                         │
                    orion-chat/web
                    Vite + React
```

### 1.2 終態目錄

```
orion-agent/
├── pyproject.toml                    ← uv workspace root(只列 members)
├── package.json                      ← npm workspaces root(僅 TS 子專案)
├── uv.lock                            (統一鎖)
├── packages/
│   ├── orion-model/                  Python — 純 LLM 抽象
│   │   ├── pyproject.toml
│   │   └── src/orion_model/
│   └── orion-sdk/                    Python — agent core,依賴 orion-model
│       ├── pyproject.toml
│       └── src/orion_sdk/
├── apps/
│   ├── orion-cli/                    Python:SDK + Typer + stdin
│   │   ├── pyproject.toml
│   │   └── src/orion_cli/
│   ├── orion-chat/                   "服務型產品"
│   │   ├── api/                      Python:SDK + FastAPI(遠端 client 用)
│   │   │   ├── pyproject.toml
│   │   │   └── src/orion_chat_api/
│   │   ├── web/                      TS:Vite + React(= 舊 frontend/)
│   │   │   ├── package.json
│   │   │   └── src/
│   │   └── shared/                   OpenAPI / WS schema + 生成的 TS types
│   └── orion-cowork/                 "本地桌機產品"
│       ├── package.json              Electron + React
│       ├── electron/                 TS — main process(spawn python sidecar)
│       ├── renderer/                 TS — React UI(獨立重寫)
│       └── sidecar/                  Python — orion-sdk + stdio JSON-RPC adapter
├── deploy/
│   ├── docker-compose.yml
│   ├── Dockerfile.api                改打 apps/orion-chat/api/
│   ├── Dockerfile.sandbox            不動
│   └── README.md
└── docs/
```

## 2. 關鍵設計決策

### 2.1 為何 `orion-model` 要獨立成 package,而不是塞進 `orion-sdk`

- **邊界清楚**:`orion-model` 只認 LLM(anthropic / openai),不認 agent loop / tools / memory
- **可單獨用**:有人只想做 prompt 測試 / benchmark / 純 chatbot,不需要整套 agent runtime
- **依賴單純**:`orion-model` 只要 `anthropic + openai + httpx + pydantic`,不用拖 `sqlalchemy / docker / mcp`
- **強制紀律**:`orion-sdk` 任何模組想 call LLM 都要透過 `orion-model` 的抽象介面,不能繞道直接 import `anthropic` / `openai`,違規由 import-linter / ruff banned-api 階段擋下

### 2.2 為何 Cowork 不走 Chat API,而是直接用 SDK + sidecar

Cowork 是 **PC 本地單機 app** — 單一使用者、單一機器、本機檔案完整存取。Chat API 為「跨網路 / 多使用者」設計的東西(JWT auth、CORS、多 session 管理、HTTP/WS overhead、token rate limit、CSRF 防護)Cowork 一個都不需要。讓 Cowork 走 chat-api 等於要它先打開一個 HTTP server、發 token 給自己、再連回來 — 沒有意義。

**正確對稱**:CLI、Chat API、Cowork 三個是平行的 SDK consumers,各自直接用 SDK:

| 應用 | UI 通道 | 跟 SDK 的關係 |
|---|---|---|
| `orion-cli` | stdin / stdout(終端) | 同進程 import |
| `orion-chat/api` | HTTP / WS(遠端 client) | 同進程 import |
| `orion-cowork` | Electron IPC + 內嵌 sidecar | sidecar 進程 import,透過 stdio JSON-RPC 跟 Electron 通訊 |
| `orion-chat/web` | (不是 SDK consumer) | 透過 HTTP/WS 連 chat-api |

### 2.3 為何不做完整 TS port of SDK

完整 TS port = 重寫 30+ 工具、core 狀態機、sandbox、memory、compact、storage、migrations 一輪,**雙倍維護成本**,每加 feature 都要寫兩次,Python / TS 行為差一點就是 bug。Anthropic 自己 Claude.ai(web)跟 Claude Code(desktop)也沒共用 agent runtime — 它們是獨立 codebase,Claude Code 從第一天就是 TS,沒有 port 問題。我們有 Python 既有資產,**TS 只做 chat-api 的 typed client**(`orion-chat/shared/` 從 OpenAPI 生),不做完整 SDK port。

### 2.4 為何用 uv workspace 而不是拆獨立 repo

- **本機 editable install**:改 SDK 馬上所有 app 吃到,不用每次 pip publish
- **單一 lock file**:`uv.lock` 統一所有 package 版本,不會漂移
- **CI 簡單**:一個 `uv sync` 把整個 workspace 裝好
- **將來要拆獨立 repo**:把資料夾切出去就好,不會卡

### 2.5 migrations 屬於哪一個 package

放 `orion-sdk`。誰用 DB 誰負責 init schema(`orion-chat/api` 啟動時呼叫 `orion_sdk.migrations.upgrade()`)。Cowork sidecar 若需要本地 DB(例如 per-machine session 持久化)也用同一份 schema。

## 3. Phase 拆解(風險由低至高)

| Phase | 名稱 | 預計時程 | 風險 | 連結 |
|---|---|---|---|---|
| **A** | uv workspace 起手 | 0.5 天 | 極低 | [A-uv-workspace.md](./A-uv-workspace.md) |
| **B** | 拆 `orion-model` | 1-2 天 | 極低 | [B-extract-orion-model.md](./B-extract-orion-model.md) |
| **C** | 拆 `orion-sdk` / `orion-cli` / `orion-chat/api` | **1-2 週**(最大一刀) | 中 | [C-split-sdk-cli-chatapi.md](./C-split-sdk-cli-chatapi.md) |
| **D** | 移 web + 共享契約 | 2-3 天 | 低 | [D-move-web.md](./D-move-web.md) |
| **E** | 新建 Cowork(Electron + sidecar) | **1-2 週** | 中(全新東西,但不動現有程式) | [E-cowork-electron-sidecar.md](./E-cowork-electron-sidecar.md) |
| **F** | docker / Makefile / docs 收尾 | 2-3 天 | 低 | [F-cleanup.md](./F-cleanup.md) |

**依賴**:A → B → C → D / E(D, E 可平行)→ F

### 3.1 為何 C 是最大風險

Phase C 要把 `api/src/orion_agent/` 拆三份:
- 核心 modules → `packages/orion-sdk/src/orion_sdk/`
- `main.py` / `commands/` / `input/` → `apps/orion-cli/src/orion_cli/`
- `api/` 子目錄 → `apps/orion-chat/api/src/orion_chat_api/`

**全域 import path 大改名**:`orion_agent.*` → 三個新前綴。tests 同步搬。一不小心就會撞循環依賴或漏改。建議:
1. 先列依賴圖(`grep -r "from orion_agent\." | sort -u`)畫出每個 module 的依賴
2. 一次只搬一層,搬完跑全套 pytest 才動下一層
3. 加 import-linter contract 在 CI 強制單向依賴(SDK 不可 import cli / chat-api / cowork)

## 4. 不在 scope 內

明確**不做**的事,避免 scope 蔓延:

| 範疇 | 為何不做 |
|---|---|
| TS 重寫 agent runtime | 雙倍維護成本,§2.3 已說明 |
| `orion-client-ts`(TS SDK)| 只做 chat-api 的 typed client,放在 `apps/orion-chat/shared/` 自動生成,不獨立成 package |
| Cowork 跟 chat/web 共用 React 元件 | 你已決定 Cowork renderer 完全獨立重寫 |
| 改 chat-api 的 protocol | 既有 WS protocol 保留,frontend / Cowork sidecar 都不依賴它 |
| 改 orion-sdk 內部架構 | 純搬家,不重構;有重構需求另開 phase |
| PyInstaller 打包到一鍵安裝包 | Phase E 跑出 dev mode 即可,production 打包另開 phase |
| K8s / Helm 改動 | Phase 07 / 7c 的部署架構不變(只是 Dockerfile 路徑改) |

## 5. 驗收標準

整個 Phase 30 完成時:

- [ ] `uv sync` 在 repo root 跑完,所有 Python package editable install 成功
- [ ] `npm install` 在 repo root 跑完,所有 TS 子專案裝好
- [ ] `cd packages/orion-model && pytest` 通過(model 套件本身的測試)
- [ ] `cd packages/orion-sdk && pytest` 通過(SDK 全套測試,= 現在 `api/tests/` 的全部)
- [ ] `cd apps/orion-cli && orion run "hello"` 跑得起來,行為跟現在一樣
- [ ] `cd apps/orion-chat/api && orion-chat-api serve` 跑得起來,WS 連得通
- [ ] `cd apps/orion-chat/web && npm run dev` 跑得起來,連 chat-api 對話正常
- [ ] `cd apps/orion-cowork && npm run dev` Electron 開窗,renderer 跟 sidecar 透過 stdio 對話可以跑 agent loop
- [ ] import-linter contract 通過(SDK 不依賴 app 層)
- [ ] `docs/PROJECT_LAYOUT.md` 反映新結構
- [ ] `docs/phases/README.md` 加上 Phase 30 條目

## 6. 風險清單

| 風險 | 嚴重度 | 緩解 |
|---|---|---|
| Phase C import 改名漏網,production 某條路徑炸 | 高 | import-linter + 全套 pytest + 手動跑 `orion run` / `orion serve` / web e2e |
| `orion-sdk` 不小心引到 fastapi / typer(殼洩漏) | 中 | banned-api ruff rule;CI 跑 `python -c "import orion_sdk; print(orion_sdk.__file__)"` 不噴 import error |
| Cowork sidecar stdio 協定設計不良,改 SDK 介面要連動改 | 中 | sidecar 協定文件化(Phase E 的 §3),用 pydantic models 在 sidecar / electron 兩邊同步 |
| uv workspace 跟 hatchling build backend 不合 | 低 | 先在 Phase A 跑通最小例,有問題早發現 |
| docker-compose 路徑沒改全,deploy 炸 | 中 | Phase F 跑一次完整 `docker-compose up` 驗收 |
| 既有 docs(phase-01 ~ 29 completion 報告)裡的 import path 全失效 | 低 | 不主動改舊 docs,新 docs 用新 path;舊 docs 註明「Phase 30 後 import path 改名,參考 PROJECT_LAYOUT.md」 |

## 7. 相關 phases

- Phase 06(FastAPI Layer)— `api/` 子目錄會被搬到 `apps/orion-chat/api/`
- Phase 07(Sandbox + Production)— Dockerfile 路徑要改
- Phase WEB-UI — `frontend/` 會被搬到 `apps/orion-chat/web/`

## 8. 起手式

```bash
# 1. 讀完本 README 對整體方向有概念
# 2. 讀 A-uv-workspace.md,30 分鐘做完 Phase A 驗證 workspace 可行
# 3. B → C → 中間有疑慮停下來討論
# 4. D, E 可平行(不同人做)
# 5. F 收尾
```

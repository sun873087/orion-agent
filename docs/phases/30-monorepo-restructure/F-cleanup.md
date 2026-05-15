# Phase 30-F:收尾(docker / Makefile / docs)

## 速覽

- **預計時程**:2-3 天
- **前置 Phase**:30-C(API 已搬)、30-D(web 已搬)、30-E(Cowork 已建)
- **狀態**:📝 spec only,**未實作**
- **目標**:把 Phase A-E 留下的尾巴清完 — deploy 路徑、Makefile、docs、CI、PROJECT_LAYOUT 全部對齊新結構

## 1. 任務拆解

### 1.1 Deploy / Docker

- [ ] 改 `deploy/Dockerfile.api`:`COPY api/...` 路徑改成 `COPY apps/orion-chat/api/... packages/orion-sdk/... packages/orion-model/...`
- [ ] 用 multi-stage build:第一階段裝 deps,第二階段只 COPY runtime 必要的
- [ ] `deploy/docker-compose.yml` 的 `build.context: ..` 不變,`dockerfile` 路徑不變,但 `WORKDIR` / `CMD` 改成 `apps/orion-chat/api` 跟新 entry
- [ ] CMD 改成 `["orion-chat-api", "serve", "--host", "0.0.0.0", "--port", "8000"]`(用新 entry,不寫死 uvicorn 命令)
- [ ] 新增 `deploy/Dockerfile.web`(可選):web 也可以容器化,production 用 nginx 跑 build artifact
- [ ] `deploy/docker-compose.yml` 加 `web` service(可選)
- [ ] 跑一次 `docker compose -f deploy/docker-compose.yml up --build` 驗證
- [ ] `Dockerfile.sandbox` 通常不用動(它是 sandbox image,跟 host code 無關)

### 1.2 Makefile / 工作流程

- [ ] 刪舊 `api/Makefile`,把命令重寫成 root `Makefile`,各個 sub-project 用 `-w`/`--package` 派發
- [ ] 範例 commands(見 §3)
- [ ] 確認 `make test` / `make lint` / `make typecheck` / `make build` 都能在 root 跑

### 1.3 Docs

- [ ] **重寫 `docs/PROJECT_LAYOUT.md`** — 現有那份只描述 `api/src/orion_agent/`,Phase 30 之後完全變了
- [ ] **更新 `docs/phases/README.md`** — 表格加 Phase 30 條目,roadmap 圖補一個分支
- [ ] **不主動改 `docs/phase-*-completion.md`**(歷史記錄,保留原 path 對讀者反而是線索),但在 `docs/PROJECT_LAYOUT.md` 開頭加一個「Phase 30 重組記錄」section 說明 import path 改名表
- [ ] **加 `docs/IMPORT_PATH_MIGRATION.md`** 一張表:
  - `orion_agent.llm` → `orion_model`
  - `orion_agent.core` → `orion_sdk.core`
  - `orion_agent.tools` → `orion_sdk.tools`
  - ...
  - `orion_agent.api` → `orion_chat_api`
  - `orion_agent.main / commands / input` → `orion_cli.*`
- [ ] 各 sub-project 自己的 README.md 寫使用方式

### 1.4 CI

- [ ] GitHub Actions(若有)workflow 改成 monorepo 模式
- [ ] 一個 workflow,跑 root `uv sync` + `npm install`,再分別跑各 package 的 test / lint
- [ ] 加 `lint-imports` step 強制 import-linter contracts
- [ ] 加 type generation drift check(Phase D 30-D §6)
- [ ] (可選)path-based skip:只動 `apps/orion-chat/web/` 不跑 Python tests

### 1.5 雜項

- [ ] `.gitignore` 確認:`.venv/`、`node_modules/`、`apps/*/node_modules/`、`apps/orion-cowork/sidecar/.venv/`、build artifacts
- [ ] `.env.example`(若有)複製到 root + 每個需要 env 的 app
- [ ] `orion.db`(現在還在 git tracking)— 確認進 `.gitignore`(目前 git status 顯示 modified,應該 untrack)
- [ ] `docs/MANUAL_TESTING.md`、`docs/TROUBLESHOOTING.md`(若內含路徑)— 順手更新
- [ ] 開發者文件 `CONTRIBUTING.md`(若有)更新 setup 步驟

## 2. 新版 Dockerfile.api 骨架

```dockerfile
# orion-chat-api image — multi-stage build for monorepo workspace.
# Build (從 repo root):
#   docker build -f deploy/Dockerfile.api -t orion-chat-api:dev .

FROM python:3.12-slim AS builder

ENV PYTHONUNBUFFERED=1 PIP_NO_CACHE_DIR=1
WORKDIR /app

RUN apt-get update \
    && apt-get install -y --no-install-recommends gcc libffi-dev \
    && rm -rf /var/lib/apt/lists/* \
    && pip install uv

# 把整個 workspace 複進來(uv workspace 不支援只裝部分 member 的 lock)
COPY pyproject.toml uv.lock ./
COPY packages/orion-model ./packages/orion-model
COPY packages/orion-sdk ./packages/orion-sdk
COPY apps/orion-chat/api ./apps/orion-chat/api

# 只裝 orion-chat-api 跟它的傳遞依賴
RUN uv sync --frozen --package orion-chat-api

FROM python:3.12-slim AS runtime

ENV PYTHONUNBUFFERED=1 ORION_LOG_FORMAT=json ORION_DB_AUTO_CREATE=1
WORKDIR /app

COPY --from=builder /app /app
ENV PATH="/app/.venv/bin:$PATH"

EXPOSE 8000
CMD ["orion-chat-api", "serve", "--host", "0.0.0.0", "--port", "8000"]
```

## 3. 新版 root Makefile

```makefile
.PHONY: install test lint typecheck build clean dev-cli dev-api dev-web dev-cowork

install:
	uv sync
	npm install

# ----- 跨 package 測試 / 檢查 -----
test:
	uv run --package orion-model pytest -q
	uv run --package orion-sdk pytest -q
	uv run --package orion-chat-api pytest -q
	uv run --package orion-cli pytest -q
	uv run --package orion-cowork-sidecar pytest -q

lint:
	uv run ruff check .
	uv run lint-imports

typecheck:
	uv run mypy packages apps

# ----- 各 app 的 dev mode -----
dev-cli:
	uv run --package orion-cli orion run "$(PROMPT)"

dev-api:
	uv run --package orion-chat-api orion-chat-api serve --reload --port 8000

dev-web:
	npm run dev -w @orion/chat-web

dev-cowork:
	npm run dev -w @orion/cowork

# ----- 型別契約生成 -----
gen-types:
	npm run gen:types

# ----- 清理 -----
clean:
	rm -rf .venv node_modules
	find . -type d -name __pycache__ -exec rm -rf {} +
	find . -type d -name .pytest_cache -exec rm -rf {} +
```

## 4. 新版 `docs/PROJECT_LAYOUT.md` 結構大綱

把舊版那份(描述 `api/src/orion_agent/` 24 子目錄)整個取代,新版以 workspace 為單位:

```markdown
# Project Layout — orion-agent monorepo

## 1. Top-level

orion-agent/
├── packages/         可重用程式庫(無 entrypoint)
├── apps/             可獨立交付的應用(有 entrypoint)
├── deploy/           Docker / K8s
└── docs/

## 2. packages/

### 2.1 orion-model
LLM provider 抽象層 ...

### 2.2 orion-sdk
Agent runtime,依賴 orion-model ...

## 3. apps/

### 3.1 orion-cli
### 3.2 orion-chat/api
### 3.3 orion-chat/web
### 3.4 orion-cowork

## 4. 依賴規則(import-linter 強制)
... 表 ...

## 5. Runtime data 位置
(保留舊版的 bundled / system / project / user 4 層說明,這部分不變)
```

## 5. `docs/IMPORT_PATH_MIGRATION.md` 範本

```markdown
# Phase 30:import path 改名對照表

| 舊 path(Phase 0-29) | 新 path(Phase 30 後) | 所屬 package |
|---|---|---|
| `orion_agent.llm.*` | `orion_model.*` | orion-model |
| `orion_agent.core.*` | `orion_sdk.core.*` | orion-sdk |
| `orion_agent.tools.*` | `orion_sdk.tools.*` | orion-sdk |
| `orion_agent.mcp.*` | `orion_sdk.mcp.*` | orion-sdk |
| `orion_agent.sandbox.*` | `orion_sdk.sandbox.*` | orion-sdk |
| `orion_agent.prompt.*` | `orion_sdk.prompt.*` | orion-sdk |
| `orion_agent.memory.*` | `orion_sdk.memory.*` | orion-sdk |
| `orion_agent.state.*` | `orion_sdk.state.*` | orion-sdk |
| `orion_agent.storage.*` | `orion_sdk.storage.*` | orion-sdk |
| `orion_agent.compact.*` | `orion_sdk.compact.*` | orion-sdk |
| `orion_agent.recovery.*` | `orion_sdk.recovery.*` | orion-sdk |
| `orion_agent.plan_mode.*` | `orion_sdk.plan_mode.*` | orion-sdk |
| `orion_agent.multi_agent.*` | `orion_sdk.multi_agent.*` | orion-sdk |
| `orion_agent.plugins.*` | `orion_sdk.plugins.*` | orion-sdk |
| `orion_agent.skills.*` | `orion_sdk.skills.*` | orion-sdk |
| `orion_agent.hooks.*` | `orion_sdk.hooks.*` | orion-sdk |
| `orion_agent.output_styles.*` | `orion_sdk.output_styles.*` | orion-sdk |
| `orion_agent.telemetry.*` | `orion_sdk.telemetry.*` | orion-sdk |
| `orion_agent.perf.*` | `orion_sdk.perf.*` | orion-sdk |
| `orion_agent.permissions.*` | `orion_sdk.permissions.*` | orion-sdk |
| `orion_agent.services.*` | `orion_sdk.services.*` | orion-sdk |
| `orion_agent.migrations.*` | `orion_sdk.migrations.*` | orion-sdk |
| `orion_agent.api.*` | `orion_chat_api.*` | orion-chat-api |
| `orion_agent.main` | `orion_cli.__main__` | orion-cli |
| `orion_agent.commands.*` | `orion_cli.commands.*` | orion-cli |
| `orion_agent.input.*` | `orion_cli.input.*` | orion-cli |
```

## 6. 風險與緩解

| 風險 | 嚴重度 | 緩解 |
|---|---|---|
| Dockerfile 路徑改錯,production build 炸 | 高 | Phase F 內必跑一次 `docker compose up --build` 完整驗證 |
| Makefile 命令改完,既有開發者習慣記憶炸 | 低 | `make help` 印新命令列表;在 README 開頭寫遷移 cheatsheet |
| 舊 docs(phase-01 ~ 29)裡的範例 import 全失效 | 低 | 不改舊 docs;在 PROJECT_LAYOUT.md 開頭放遷移表,讀者一查就知道 |
| CI workflow 路徑改沒改全 | 中 | 開 draft PR 先看 CI 跑出來反映實際狀況 |
| `orion.db` SQLite 一直在 git tracking | 低 | `git rm --cached orion.db && echo "*.db" >> .gitignore` |
| `.env` 路徑變了,end users 跟著炸 | 中 | `.env.example` 放 repo root,docker-compose 改 `env_file: ../.env` 對 root |

## 7. 驗收

- [ ] `docker compose -f deploy/docker-compose.yml up --build` 從 repo root 跑得起來
- [ ] `make install && make test && make lint && make typecheck` 全綠
- [ ] `make dev-cli PROMPT="hello"` 跑得起來
- [ ] `make dev-api` 跑得起來
- [ ] `make dev-web` 跑得起來
- [ ] `make dev-cowork` Electron 開窗
- [ ] `docs/PROJECT_LAYOUT.md` 已重寫
- [ ] `docs/IMPORT_PATH_MIGRATION.md` 已建立
- [ ] `docs/phases/README.md` 加上 Phase 30 條目
- [ ] CI workflow 跑通

## 8. 完成後的狀態

整個 Phase 30 收尾。Repo 處於完整 monorepo + multi-app 狀態:

```
orion-agent/
├── pyproject.toml              workspace root
├── package.json                npm workspaces root
├── uv.lock / package-lock.json
├── Makefile                    跨 sub-project 命令
├── packages/
│   ├── orion-model/
│   └── orion-sdk/
├── apps/
│   ├── orion-cli/
│   ├── orion-chat/
│   │   ├── api/
│   │   ├── web/
│   │   ├── shared/
│   │   └── scripts/
│   └── orion-cowork/
│       ├── electron/
│       ├── renderer/
│       └── sidecar/
├── deploy/
│   ├── Dockerfile.api          → 對 apps/orion-chat/api
│   ├── Dockerfile.web          (可選)→ 對 apps/orion-chat/web
│   ├── Dockerfile.sandbox      不變
│   └── docker-compose.yml
└── docs/
    ├── PROJECT_LAYOUT.md       重寫
    ├── IMPORT_PATH_MIGRATION.md ★ 新
    └── phases/
        ├── README.md           加 Phase 30 條目
        └── 30-monorepo-restructure/
            ├── README.md
            ├── A-uv-workspace.md
            ├── B-extract-orion-model.md
            ├── C-split-sdk-cli-chatapi.md
            ├── D-move-web.md
            ├── E-cowork-electron-sidecar.md
            └── F-cleanup.md
```

## 9. Phase 30 全部結束

之後若要進 Cowork production 打包 / TS client SDK / 把 SDK 發 PyPI 等,另開 phase。

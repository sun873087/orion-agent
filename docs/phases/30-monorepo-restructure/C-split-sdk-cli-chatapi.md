# Phase 30-C:拆 `orion-sdk` / `orion-cli` / `orion-chat/api`

## 速覽

- **預計時程**:1-2 週(全職)
- **前置 Phase**:30-A、30-B
- **狀態**:📝 spec only,**未實作**
- **目標**:把 `api/src/orion_agent/` 拆成三個獨立 workspace member,徹底消滅 `orion_agent` 命名空間,改用三個明確命名的新 package

**這是 Phase 30 最大一刀**,動的檔案最多、import 改名範圍最廣。建議在這 phase 期間 freeze 其他 PR,免得 conflict。

## 1. 拆分目標

```
api/src/orion_agent/        現況一坨 24 子模組
    │
    ├──→ packages/orion-sdk/src/orion_sdk/     ← agent core(大部分東西)
    │      ├── core/
    │      ├── tools/
    │      ├── mcp/
    │      ├── sandbox/
    │      ├── prompt/
    │      ├── memory/
    │      ├── state/
    │      ├── storage/
    │      ├── compact/
    │      ├── recovery/
    │      ├── plan_mode/
    │      ├── multi_agent/
    │      ├── plugins/
    │      ├── skills/
    │      ├── hooks/
    │      ├── output_styles/
    │      ├── telemetry/
    │      ├── perf/
    │      ├── permissions/
    │      ├── services/
    │      └── migrations/         ← 跟 SDK(誰用 DB 誰跑)
    │
    ├──→ apps/orion-cli/src/orion_cli/         ← CLI 殼
    │      ├── __main__.py                      ← 原本 main.py
    │      ├── commands/                        ← 原本 commands/
    │      └── input/                           ← 原本 input/(stdin / slash / image upload)
    │
    └──→ apps/orion-chat/api/src/orion_chat_api/   ← Chat API 殼
           ├── app.py
           ├── auth.py
           ├── auth_db.py
           ├── deps.py
           ├── event_schema.py
           ├── routes/
           ├── session_manager.py
           ├── session_manager_db.py
           └── ws_permissions.py
```

## 2. 歸屬決策(誰去哪)

### 2.1 規則

- **不 import 任何 殼相關 module(typer / fastapi / uvicorn / stdin)的 → SDK**
- **import typer / Click / 終端互動的 → orion-cli**
- **import fastapi / uvicorn / starlette / WebSocket / JWT 的 → orion-chat/api**

### 2.2 個別判定

| 現有 `api/src/orion_agent/` 子目錄 | 去處 | 理由 |
|---|---|---|
| `core/` | SDK | Conversation / QueryLoop 是 agent 心臟 |
| `tools/` | SDK | 內建工具集,跟殼無關 |
| `mcp/` | SDK | MCP client,跟殼無關 |
| `sandbox/` | SDK | Docker / local sandbox backend |
| `prompt/` | SDK | system prompt assembler |
| `memory/` | SDK | per-user memory 載入 / 提取 |
| `state/` | SDK | AgentContext / feature flags(注意:`AgentContext` 是 SDK 跟殼共用的進入點)|
| `storage/` | SDK | SQLAlchemy models,DB persistence |
| `compact/` `recovery/` | SDK | 對話壓縮 / 恢復 |
| `plan_mode/` | SDK | Plan mode 狀態機 |
| `multi_agent/` | SDK | Coordinator / Swarm |
| `plugins/` `skills/` `hooks/` | SDK | 擴充機制(plugin / skill / hook event)|
| `output_styles/` | SDK | 輸出風格樣板 |
| `telemetry/` `perf/` | SDK | OpenTelemetry / profiling hooks |
| `permissions/` | SDK | permission policy 抽象 |
| `services/` | SDK | feature flag loader 等 cross-cutting |
| `migrations/` | SDK | alembic 設定 + revisions,SDK 自帶 schema 管理 |
| **`api/`** | **orion-chat/api** | FastAPI 殼 |
| **`commands/`** | **orion-cli** | CLI slash 命令(`/clear` `/help` 等),只 CLI 用 |
| **`input/`** | **orion-cli** | stdin / slash / image upload — 終端輸入處理 |
| **`main.py`** | **orion-cli** | typer app entrypoint |
| `__init__.py` | (刪) | 不再有 `orion_agent` 命名空間 |

### 2.3 灰色地帶

- **`commands/builtin/`**:有些是 CLI 專屬(`/clear`),有些可能 chat-api 也想用(`/help`)。先全部進 `orion-cli`,Phase C 不重構命令分發機制;若 chat-api 將來要支援 slash 命令,再從 cli 抽共用部分。
- **`alembic.ini`**:跟 `migrations/` 一起搬到 `packages/orion-sdk/`,但 chat-api 啟動時要能找到。建議 SDK 提供 `orion_sdk.migrations.upgrade(db_url)` API,讓 chat-api 不用知道 alembic.ini 在哪。

## 3. 任務拆解

### 3.1 準備

- [ ] 在 freeze 期前 merge 所有 in-flight PR
- [ ] 跑全套 pytest 確認 baseline 綠的
- [ ] 用 `grep -rE "^from orion_agent\." api/src/orion_agent/ | cut -d: -f2 | sort -u > /tmp/imports.txt` 產出 import 圖
- [ ] 用 `tools/` 內依賴最多的 module 當風險指標(預期是 `core/conversation.py`)

### 3.2 建立目錄骨架

- [ ] `mkdir -p packages/orion-sdk/src/orion_sdk apps/orion-cli/src/orion_cli apps/orion-chat/api/src/orion_chat_api`
- [ ] 各自寫 `pyproject.toml`(見 §4)
- [ ] root `pyproject.toml` 加入新 members
- [ ] `uv sync` 確認三個空 package editable install 成功

### 3.3 第一批搬移(SDK 大宗,但不動 import path)

- [ ] `git mv` 把 SDK 該收的子目錄全部搬過去
- [ ] 暫時保留 `api/src/orion_agent/__init__.py` 做 re-export(`from orion_sdk import *`)讓 chat-api / cli 還在原處時還能 import — 這只是 sed 一輪的緩衝,Phase C 結束時拆掉
- [ ] 跑 pytest 確認還是綠的(此時所有東西仍指向 `orion_agent.*`,只是檔案位置變了)

### 3.4 改 import path:`orion_agent.X` → `orion_sdk.X`

對非 cli / chat-api 的部分:

```bash
# 列出要改的 module 清單(SDK 收下的子目錄)
modules=(core tools mcp sandbox prompt memory state storage compact recovery \
         plan_mode multi_agent plugins skills hooks output_styles telemetry \
         perf permissions services migrations)

# 對每個 module 改名
for m in "${modules[@]}"; do
  grep -rl "orion_agent\.$m" packages apps api 2>/dev/null | \
    xargs sed -i '' "s/orion_agent\.$m/orion_sdk.$m/g"
done
```

跑 pytest,綠了再進下一步。

### 3.5 搬 orion-cli

- [ ] `git mv api/src/orion_agent/main.py apps/orion-cli/src/orion_cli/__main__.py`
- [ ] `git mv api/src/orion_agent/commands apps/orion-cli/src/orion_cli/commands`
- [ ] `git mv api/src/orion_agent/input apps/orion-cli/src/orion_cli/input`
- [ ] 全域 sed:`orion_agent.commands` → `orion_cli.commands`、`orion_agent.input` → `orion_cli.input`
- [ ] `apps/orion-cli/pyproject.toml` 寫 `[project.scripts]` entry:`orion = "orion_cli.__main__:cli"`
- [ ] `apps/orion-cli/pyproject.toml` 列 dep:`orion-sdk`(workspace)+ `typer` + `python-dotenv`
- [ ] 跑 `uv run --package orion-cli orion --help` 驗證

### 3.6 搬 orion-chat/api

- [ ] `git mv api/src/orion_agent/api apps/orion-chat/api/src/orion_chat_api`
- [ ] 全域 sed:`orion_agent.api` → `orion_chat_api`
- [ ] `apps/orion-chat/api/pyproject.toml` 寫 dep:`orion-sdk` + `fastapi` + `uvicorn[standard]` + `pyjwt` + `bcrypt`
- [ ] 把 `orion serve` 子命令從 cli 拆出 — 兩個選擇:
  - (a) `orion-chat-api serve` 是獨立 entrypoint(`[project.scripts]` 在 chat-api 的 pyproject)
  - (b) cli 透過 `orion serve` 呼叫 chat-api(cli 是 chat-api 的 client) — **不推薦**,違反「cli / chat-api 平行 SDK consumer」原則
- [ ] 採 (a):chat-api 自己有 entry `orion-chat-api = "orion_chat_api.cli:main"`,cli 把 `serve` 命令拿掉
- [ ] 跑 `uv run --package orion-chat-api orion-chat-api serve --port 8000` 驗證

### 3.7 收尾

- [ ] 刪 `api/src/orion_agent/__init__.py` 的 re-export 橋接層
- [ ] 刪空殼 `api/` 目錄(`api/pyproject.toml` / `api/src/orion_agent/` / `api/uv.lock` / `api/Makefile` — 確認沒人 reference 後砍)
- [ ] root `pyproject.toml` 從 `members` 移除 `"api"`
- [ ] 搬 `api/tests/` → 對應的 package(tests 跟著它測的 code 走)
  - 大部分 tests 進 `packages/orion-sdk/tests/`
  - api routes tests 進 `apps/orion-chat/api/tests/`
  - cli 命令 tests 進 `apps/orion-cli/tests/`
- [ ] `api/alembic.ini` → `packages/orion-sdk/alembic.ini`,migrations 跟著走
- [ ] `api/orion.db` → 移到 repo root 或 `.gitignore`(它本來就不該 commit,看 git status 已標記)
- [ ] 更新 import-linter contracts(見 §5)

## 4. 三個新 pyproject.toml

### 4.1 `packages/orion-sdk/pyproject.toml`

```toml
[project]
name = "orion-sdk"
version = "0.1.0"
description = "Agent runtime SDK — Conversation loop, tools, MCP, sandbox, memory."
readme = "README.md"
requires-python = ">=3.11"
license = { text = "MIT" }
dependencies = [
    "orion-model",
    "pydantic>=2.0",
    "anyio>=4.0",
    "structlog>=24.0",
    "python-dotenv>=1.0",
    "httpx>=0.27",
    "beautifulsoup4>=4.12",
    "mcp>=1.0",
    "sqlalchemy[asyncio]>=2.0",
    "alembic>=1.13",
    "asyncpg>=0.29",
    "aiosqlite>=0.19",
    "docker>=7.0",
    "python-frontmatter>=1.1",
    "opentelemetry-api>=1.27",
    "opentelemetry-sdk>=1.27",
    "opentelemetry-exporter-otlp-proto-grpc>=1.27",
    "apscheduler>=3.10",
    "pyinstrument>=4.6",
    "nbformat>=5.10",
    "cryptography>=42.0",
    "keyring>=24.0",
]

[tool.uv.sources]
orion-model = { workspace = true }

[build-system]
requires = ["hatchling"]
build-backend = "hatchling.build"

[tool.hatch.build.targets.wheel]
packages = ["src/orion_sdk"]
```

**禁止依賴(由 import-linter 強制):**
- `typer`、`click` — UI 殼,只 cli 該用
- `fastapi`、`uvicorn`、`starlette` — server 殼,只 chat-api 該用
- `bcrypt`、`pyjwt` — auth 是 chat-api 的事

### 4.2 `apps/orion-cli/pyproject.toml`

```toml
[project]
name = "orion-cli"
version = "0.1.0"
description = "Terminal CLI for orion-sdk — stdin-based agent loop."
requires-python = ">=3.11"
dependencies = [
    "orion-sdk",
    "typer>=0.12",
]

[project.scripts]
orion = "orion_cli.__main__:cli"

[tool.uv.sources]
orion-sdk = { workspace = true }

[build-system]
requires = ["hatchling"]
build-backend = "hatchling.build"

[tool.hatch.build.targets.wheel]
packages = ["src/orion_cli"]
```

### 4.3 `apps/orion-chat/api/pyproject.toml`

```toml
[project]
name = "orion-chat-api"
version = "0.1.0"
description = "FastAPI + WebSocket server exposing orion-sdk to remote clients."
requires-python = ">=3.11"
dependencies = [
    "orion-sdk",
    "fastapi>=0.110,<1.0",
    "uvicorn[standard]>=0.27",
    "pyjwt>=2.8",
    "bcrypt>=4.0",
]

[project.scripts]
orion-chat-api = "orion_chat_api.cli:main"

[tool.uv.sources]
orion-sdk = { workspace = true }

[build-system]
requires = ["hatchling"]
build-backend = "hatchling.build"

[tool.hatch.build.targets.wheel]
packages = ["src/orion_chat_api"]
```

需要在 `orion_chat_api/cli.py` 寫一個極簡 entrypoint(從 `orion serve` 抽出來):

```python
import typer
import uvicorn

app = typer.Typer(add_completion=False)

@app.command()
def serve(host: str = "127.0.0.1", port: int = 8000, reload: bool = False,
          db_url: str | None = None) -> None:
    import os
    if db_url:
        os.environ["ORION_DB_URL"] = db_url
    uvicorn.run("orion_chat_api.app:app", host=host, port=port, reload=reload)

def main() -> None:
    app()
```

## 5. import-linter contracts(必裝)

```toml
[tool.importlinter]
root_packages = ["orion_model", "orion_sdk", "orion_cli", "orion_chat_api"]

[[tool.importlinter.contracts]]
name = "Layer hierarchy"
type = "layers"
layers = [
    "orion_cli | orion_chat_api",   # 同層,互不依賴
    "orion_sdk",
    "orion_model",
]

[[tool.importlinter.contracts]]
name = "SDK must not depend on UI shells"
type = "forbidden"
source_modules = ["orion_sdk", "orion_model"]
forbidden_modules = ["typer", "click", "fastapi", "uvicorn", "starlette"]
```

CI 加 `uv run lint-imports`。

## 6. Tests 搬移策略

`api/tests/` 目前一坨。原則:測什麼跟誰走。

```bash
# 看每個 test file 主要 import 的 module
for f in api/tests/**/*.py; do
  pkg=$(grep -oE "from orion_agent\.[a-z_]+" "$f" | head -1 | cut -d. -f2)
  echo "$pkg  $f"
done | sort
```

- `test_conversation.py`、`test_tools.py`、`test_memory.py` ... → `packages/orion-sdk/tests/`
- `test_api_*.py`、`test_ws_*.py`、`test_auth.py` → `apps/orion-chat/api/tests/`
- `test_main.py`(CLI 入口)、`test_commands.py` → `apps/orion-cli/tests/`

整合測試(跨 SDK + chat-api)留在 `apps/orion-chat/api/tests/integration/`。

## 7. 風險與緩解

| 風險 | 嚴重度 | 緩解 |
|---|---|---|
| sed 改 import 漏 | 高 | 每個 sub-step 跑 pytest;最後再加 `python -c "import X"` 列每個 module |
| 循環依賴突然冒出來 | 中 | import-linter contract 在每個 sub-step 後跑;違規早抓 |
| chat-api 跟 cli 共用了某 helper(在 `api/` 或 `commands/` 裡) | 中 | 該 helper 應該屬於 SDK;Phase C 內判斷,搬到 SDK |
| alembic 找不到 migrations dir | 中 | `orion_sdk/migrations/env.py` 用 `importlib.resources` 找,別寫硬路徑 |
| `models.json` / skills bundle / 其他資料檔搬位置後 `importlib.resources` 抓不到 | 中 | hatchling 的 `[tool.hatch.build.targets.wheel].include` 補上資料檔 |
| `orion.db`(SQLite)在 api/ 下,搬走後 connection string 失效 | 低 | 把 `orion.db` 改用 `~/.orion/orion.db` 或環境變數,不該綁專案目錄 |
| WS protocol 在 chat-api,frontend / cowork 都用,Phase C 改 import 後 schema 路徑變了 | 中 | Phase D 才動 frontend;chat-api 內部 import 改名不影響 wire protocol |

## 8. 驗收

- [ ] `uv sync` 通
- [ ] `uv run lint-imports` 通
- [ ] `uv run --package orion-sdk pytest -q` 通
- [ ] `uv run --package orion-chat-api pytest -q` 通
- [ ] `uv run --package orion-cli pytest -q` 通
- [ ] `uv run --package orion-cli orion run "hello"` 跑得起來,行為跟現在一樣
- [ ] `uv run --package orion-chat-api orion-chat-api serve --port 8000` 跑得起來,WS 連得通
- [ ] 既有 frontend 連 chat-api 對話正常(此時 frontend 還沒搬,在原處)
- [ ] `api/` 目錄整個消失
- [ ] `from orion_agent` 在 repo 內 grep 不到任何結果

## 9. 完成後的狀態

```
orion-agent/
├── pyproject.toml              ← members: packages/*, apps/orion-cli, apps/orion-chat/api
├── uv.lock
├── packages/
│   ├── orion-model/            (Phase B)
│   └── orion-sdk/              ★ 新
│       ├── pyproject.toml
│       ├── alembic.ini
│       └── src/orion_sdk/      ← 從 orion_agent 24 子目錄搬來,少掉 api/commands/input/main.py
├── apps/
│   ├── orion-cli/              ★ 新
│   │   ├── pyproject.toml
│   │   ├── src/orion_cli/
│   │   │   ├── __main__.py     ← 原 main.py
│   │   │   ├── commands/
│   │   │   └── input/
│   │   └── tests/
│   └── orion-chat/
│       └── api/                ★ 新
│           ├── pyproject.toml
│           ├── src/orion_chat_api/
│           │   ├── app.py
│           │   ├── cli.py      ← 新增,serve entrypoint
│           │   ├── auth.py
│           │   ├── auth_db.py
│           │   ├── deps.py
│           │   ├── event_schema.py
│           │   ├── routes/
│           │   ├── session_manager.py
│           │   ├── session_manager_db.py
│           │   └── ws_permissions.py
│           └── tests/
├── frontend/                   (Phase D 才搬)
├── deploy/                     (Phase F 才更新 Dockerfile 路徑)
└── docs/
```

## 10. 下一步

Phase C 通了,Phase D(搬 frontend)+ Phase E(新建 Cowork)可平行進行。

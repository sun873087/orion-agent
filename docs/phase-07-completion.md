# Phase 7 — Production Foundation + Docker Sandbox 完工記錄

**完成日期**:2026-05-07
**Plan doc**:`docs/phases/07-production-foundation.md`(範圍 B:核心 + Docker sandbox,
**不含** K8s 部署 → Phase 7c)
**狀態**:✅ `make check` 全綠 — **350 unit tests passed, 2 skipped**(Docker tests 無 daemon 時 skip)

---

## 交付清單

### 新增模組

```
src/orion_agent/
├── sandbox/                              [全新,5 檔]
│   ├── __init__.py
│   ├── protocol.py                       SandboxBackend Protocol + ExecResult + SandboxError
│   ├── local.py                          LocalBackend(host fs / shell,預設)
│   ├── docker_backend.py                 DockerBackend(per-session container 隔離)
│   ├── factory.py                        get_sandbox_backend(name | env)
│   └── proxy_tools.py                    SandboxedBash/Read/Write/Edit + build_sandboxed_tools
├── storage/db/                           [全新,5 檔]
│   ├── __init__.py
│   ├── engine.py                         create_db_engine + db_session + init_db
│   ├── models.py                         User / Session / Message ORM models
│   └── alembic/                          Alembic migration env
│       ├── env.py
│       └── versions/0001_init.py         init schema
├── api/auth_db.py                        [新] bcrypt + create_user / authenticate
├── api/session_manager_db.py             [新] DbSessionManager(取代 in-memory)
└── services/logging.py                   [新] structlog config + request_id middleware

deploy/                                   [全新,4 檔,docs only]
├── README.md                             部署指引
├── Dockerfile.api                        FastAPI image
├── Dockerfile.sandbox                    sandbox base image(per-session container 用)
└── docker-compose.yml                    Postgres + API 本機 stack

alembic.ini                               [新] Alembic 設定(讀 ORION_DB_URL)
```

### 修改既有檔

```
src/orion_agent/
├── core/state.py                         AgentContext 加 sandbox_backend
├── core/conversation.py                  Conversation 加 sandbox_backend(send 注 ctx)
├── api/app.py                            lifespan 起 DB engine、註 request_id middleware、
│                                          configure_logging;切 DbSessionManager when DB URL
├── api/routes/auth.py                    加 /auth/register;login 動態切 DB 模式
└── main.py                               run --sandbox local|docker;serve --db-url

pyproject.toml                            sqlalchemy[asyncio] / alembic / asyncpg /
                                          aiosqlite / bcrypt / docker
```

### Tests(全新,7 檔,共 41 案例)

```
tests/unit/sandbox/
├── test_local_backend.py        9 tests(exec / read / write / cwd / timeout / cleanup)
├── test_factory.py              4 tests(env / 預設 / 未知 backend)
├── test_proxy_tools.py          9 tests(FakeBackend 驗 routing — Bash/Read/Write/Edit)
└── test_docker_backend.py       2 tests(skip if no docker daemon)
tests/unit/db/
├── test_models.py               3 tests(User CRUD / FK 關聯 / unique 衝突)
├── test_auth_db.py              7 tests(hash 雙向、authenticate 三路徑)
└── test_db_session_manager.py   4 tests(create/get/delete/list,user 隔離)
tests/unit/services/
└── test_logging.py              4 tests(idempotent / get_logger / contextvars)
```

---

## 設計決策

### 1. SandboxBackend Protocol — 可插拔

```python
class SandboxBackend(Protocol):
    name: str
    async def exec(self, argv, *, cwd, timeout, env) -> ExecResult: ...
    async def read_file(self, path) -> bytes: ...
    async def write_file(self, path, data) -> None: ...
    async def cleanup(self) -> None: ...
```

- **LocalBackend**:走 host(同 Phase 1-6 預設行為,`name="local"`)。
- **DockerBackend**:每 conversation 一個 container,`docker.exec_run` + `get_archive` /
  `put_archive` 讀寫檔。block 操作 wrap `anyio.to_thread`。
- **K8sBackend**(Phase 7c):同 Protocol。

### 2. proxy_tools 而非改既有工具

不動 `tools/shell/bash.py`(LocalBackend 直接路徑保留)。新建
`sandbox/proxy_tools.py`,提供 `SandboxedBashTool` / `SandboxedFileReadTool` /
`SandboxedFileWriteTool` / `SandboxedFileEditTool`。Tool name / description /
input_schema 與 Phase 1 工具一致(模型看到一樣),只是執行路徑改走 backend。

`main.py --sandbox docker` 觸發 `build_sandboxed_tools(backend)` 取代預設 tool 集合。

### 3. SQLAlchemy 雙模:Postgres prod / SQLite test

- prod:`postgresql+asyncpg://user:pw@host/db`
- test:`sqlite+aiosqlite:///:memory:`(unit test 不需 setup)
- 同套 models 跑兩邊;Alembic env.py 自動把 `asyncpg` → `psycopg2`、`aiosqlite` →
  `sqlite`(migration 走 sync)。

### 4. bcrypt password + dual-mode auth

- DB 模式(`ORION_DB_URL` 設):`/auth/register` 建 user,`/auth/login` 驗 bcrypt
- Dev fallback(無 DB):任意 username 通過(向後相容 Phase 6)
- `authenticate` 對未知 user 仍跑一次 hash check 抗 timing attack

### 5. DbSessionManager 介面同 Phase 6

`SessionManager` Protocol 同前(`create / get / delete / list_for_user / size`),
caller(routes / WebSocket)無需改。in-memory cache 保留 `Conversation` 物件;
DB 存 metadata(turns / messages / tokens)。
**Phase 7 範圍 = single-instance**;cache miss 視同新 session(跨 worker 復原留 7c)。

### 6. structlog + request_id

- `services/logging.py`:`configure_logging()`(lifespan 啟動呼一次)
- `request_id_middleware`:每 request 產 UUID(或拿 `X-Request-ID` header),
  bind `structlog.contextvars` → 後續 log 自動帶 `request_id` / `method` / `path`
- format:`ORION_LOG_FORMAT=json` 強制 JSON;否則 tty 自動 console

### 7. 部署檔 = docker-compose + Dockerfile

`deploy/`:`Dockerfile.api`(FastAPI)+ `Dockerfile.sandbox`(per-session base)+
`docker-compose.yml`(Postgres + API)。本機 dev / smoke test 用,production 走
Phase 7c 的 K8s。

---

## CLI / API 變更

### `orion run` 新 flag

```bash
orion run --sandbox docker "Bash: ls /tmp"
# 工具改透過 DockerBackend 執行;預設 local 同 Phase 1-6 行為
```

### `orion serve` 新 flag

```bash
orion serve --port 8000 --db-url postgresql+asyncpg://orion:dev@localhost/orion
# 等同設 ORION_DB_URL;會自動切 DbSessionManager
```

### 新 endpoint

```
POST /auth/register   { username, password } → { user_id, username }
POST /auth/login      { username, password } → { token, ... }   # 改驗密碼
```

### 新環境變數

| Env | 用途 |
|---|---|
| `ORION_DB_URL` | DB 連線。未設 → in-memory(Phase 6 行為) |
| `ORION_DB_AUTO_CREATE` | `1`(預設)→ lifespan create_all。production 設 `0` 走 Alembic |
| `ORION_SANDBOX` | `local`(預設)/ `docker` |
| `ORION_LOG_FORMAT` | `json` / `console`(預設 tty 自動) |
| `ORION_LOG_LEVEL` | `debug` / `info`(預設)/ `warning` / `error` |

---

## Verification

```bash
cd orion-agent/api/

# 1. install + check
make fix-install
make check
# → ruff All checks passed!
# → mypy: Success: no issues found in 112 source files
# → pytest: 350 passed, 2 skipped(Docker tests 無 daemon 時 skip)

# 2. SQLite-mode demo
ORION_DB_URL="sqlite+aiosqlite:///:memory:" \
  uv run orion serve --port 8765 &

curl -X POST http://127.0.0.1:8765/auth/register \
  -H 'Content-Type: application/json' \
  -d '{"username":"alice","password":"secret123"}'
# → { "user_id": "...", "username": "alice" }

curl -X POST http://127.0.0.1:8765/auth/login \
  -H 'Content-Type: application/json' \
  -d '{"username":"alice","password":"secret123"}'
# → { "token": "eyJhbGc..." }

# 3. Docker sandbox(若有)
docker info > /dev/null 2>&1 && \
  uv run orion run --sandbox docker --no-mcp "echo hi from sandbox"
# → 在 docker container 內跑;cleanup 自動停 + remove
```

---

## Phase 7 故意先不做(都已開新 phase plan)

| 項目 | 留給 |
|---|---|
| K8s Pod-per-session sandbox + Helm chart | Phase 7c(`docs/phases/7c-helm-chart.md`) |
| gVisor RuntimeClass / NetworkPolicy / RBAC | Phase 7c |
| 預熱 ReplicaSet pool | Phase 7c |
| Cross-instance Conversation 復原(Redis state + transcript replay) | Phase 7c |
| Redis cache / S3 large output | Phase 8+ |
| Real OAuth providers(Google / GitHub) | Phase 11+ |
| Per-user quota / rate limit / YAML policy engine | Phase 11+ |
| argon2id 取代 bcrypt | Phase 11+ |

---

## 風險與已緩解

| 風險 | 緩解 |
|---|---|
| iCloud Drive 在 ~/Desktop 把 .venv 檔複製成 ` 2`/` 3` | `make fix-install` 清除 + reinstall |
| Docker SDK 是 sync,async loop 阻塞 | 全部 wrap `anyio.to_thread.run_sync` |
| Phase 7 cache miss 會視同新 session | Phase 7c 加 Redis state + transcript replay |
| Postgres migration 跟 Phase 2 transcript 衝突 | Phase 2 transcript 仍 file-based,DB 只存 metadata |

---

## Tests 摘要

| Suite | 數量 | 說明 |
|---|---|---|
| Phase 0 — provider HTTP wrapper | 既有 | 不動 |
| Phase 1 — tools / query_loop | 既有 | 不動 |
| Phase 2 — transcript / replacement | 既有 | 不動 |
| Phase 3 — memory | 既有 | 不動 |
| Phase 4 — prompt assembler | 既有 | 不動 |
| Phase 5 — MCP integration | 既有 | 不動 |
| Phase 6 — FastAPI / WebSocket | 既有 | 不動 |
| **Phase 7 sandbox** | 24 | LocalBackend + factory + proxy_tools(FakeBackend)+ DockerBackend(skip) |
| **Phase 7 db** | 14 | models / auth_db / DbSessionManager(SQLite in-memory) |
| **Phase 7 services/logging** | 4 | configure / get_logger / middleware / contextvars |
| **總計** | **350 + 2 skipped** | mypy --strict / ruff 全綠 |

# orion-agent — Deploy

Phase 7 部署檔。本機 stack 跑 Postgres + API + Docker sandbox backend。
Production K8s / Helm 留到 **Phase 7c**(`docs/phases/21-helm-chart.md`)。

## 檔案

| 檔案 | 用途 |
|---|---|
| `Dockerfile.api` | FastAPI server image |
| `Dockerfile.sandbox` | DockerBackend per-session container 的 base image |
| `docker-compose.yml` | Postgres + API stack(本機 dev / smoke test) |

## 本機跑

從 repo root(含 `orion-agent/`):

```bash
cd orion-agent

# 1. 建 sandbox base image(DockerBackend 拿來跑 per-session container)
docker build -f deploy/Dockerfile.sandbox -t orion-agent-sandbox:dev .

# 2. 起整個 stack(api + postgres)
docker compose -f deploy/docker-compose.yml up --build

# API 在 http://localhost:8000
# /healthz / /auth/register / /auth/login / /sessions / /chat/stream
```

## 環境變數

API container 認的:

| Env | 說明 |
|---|---|
| `ORION_DB_URL` | DB connection string。`postgresql+asyncpg://...` 或 `sqlite+aiosqlite:///...`。**未設** → in-memory SessionManager(Phase 6 行為)。 |
| `ORION_DB_AUTO_CREATE` | `1`(預設)→ lifespan 自動 `Base.metadata.create_all`。production 改 `0`,改走 Alembic。 |
| `ORION_SANDBOX` | `local`(預設)/ `docker`。`docker` 需 docker.sock 可達。 |
| `ORION_LOG_FORMAT` | `json` / `console`。預設依 tty 自動。 |
| `ORION_LOG_LEVEL` | `debug` / `info`(預設)/ `warning` / `error`。 |
| `ORION_JWT_SECRET` | JWT 簽章金鑰。**production 必設**(否則 lifespan 會用 ephemeral key,重啟 invalidate 全部 token)。 |
| `ANTHROPIC_API_KEY` / `OPENAI_API_KEY` | LLM key,至少要設一個對應 ORION_PROVIDER。 |
| `ORION_PROVIDER` / `ORION_MODEL` | LLM 預設值(可由 client per-session override)。 |

## Alembic 升級

production 跑 migration(不用 auto-create):

```bash
docker compose -f deploy/docker-compose.yml run --rm api \
    alembic upgrade head
```

## 注意

1. **Docker sandbox 需 docker.sock**:本檔 bind-mount `/var/run/docker.sock` —
   只適合 local dev。production 改用 Phase 7c 的 K8s Pod-per-session 方案。
2. **`.env`**:`api/.env` 放 LLM key、JWT secret;此 compose 從 `../.env`(repo root)讀。
3. **port 5432 衝突**:host 已有 Postgres → 改 compose `ports` mapping。
4. **首次 build 慢**:python:3.12-slim + bcrypt + asyncpg 第一次拉 ~1.5 min。

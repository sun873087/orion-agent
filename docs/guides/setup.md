# Setup

從 0 跑通本機 6 個 workspace member。預計 15-30 分鐘。

## 需求

| 工具 | 版本 | 安裝 |
|---|---|---|
| Python | ≥ 3.11 | system / pyenv |
| [uv](https://github.com/astral-sh/uv) | latest | `curl -LsSf https://astral.sh/uv/install.sh \| sh` |
| Node | ≥ 20.19 | system / nvm |
| pnpm | ≥ 10 | `npm i -g pnpm` |
| git | any | system |

可選:
- Docker(`make dev-api` 用 docker-compose 起 Postgres,或 `--sandbox docker`)
- Anthropic / OpenAI API key(沒 key 只能跑 ping / 結構驗證,跑不了真對話)

## 安裝

```bash
git clone <repo-url>
cd orion-agent

# Per-app .env(只複製你要跑的那個 app):
cp apps/orion-cli/.env.example      apps/orion-cli/.env       # CLI
cp apps/orion-chat/.env.example     apps/orion-chat/.env      # Chat server
cp apps/orion-cowork/.env.example   apps/orion-cowork/.env    # Cowork 桌機
cp packages/orion-model-proxy/.env.example packages/orion-model-proxy/.env  # Proxy
# 填 ANTHROPIC_API_KEY / OPENAI_API_KEY,或設 ORION_MODEL_PROXY_URL 走 proxy

make install          # uv sync + pnpm install
```

## 驗證 — 全 test 綠

```bash
make test
```

預期 6 行 pass 訊息(orion-model / orion-sdk / orion-cli / orion-chat-api / orion-cowork sidecar / orion-model-proxy)1100+ tests 全綠。

## 跑各個 app

### 1. CLI(最簡單)

```bash
make dev-cli PROMPT="讀 /etc/hosts 並摘要"
```

或直接 `uv run --package orion-cli orion run "..."`。

### 2. Chat API + Web

兩個 terminal:

```bash
# Terminal 1 — server
make dev-api
# → http://127.0.0.1:8000/healthz

# Terminal 2 — web
make dev-web
# → http://127.0.0.1:5173
```

瀏覽器開 `:5173`,註冊一個 user → 登入 → 開新 session → 對話。

### 3. Cowork(Electron 桌機)

```bash
make dev-cowork
```

Electron 開窗,renderer 載 Vite dev server(:5174),sidecar 由 main process 啟動。

### 4. Model Proxy(集中計費)

```bash
# 第一次:bootstrap(生 admin token + 寫 .env + 指引)
make proxy-bootstrap

# 填 proxy `.env` 內的 ANTHROPIC_API_KEY / OPENAI_API_KEY,然後:
make dev-model-proxy
# → http://127.0.0.1:9090(admin endpoints: enabled)

# Admin UI:http://127.0.0.1:9090/admin/ui/
#   Login(貼 admin token)→ New user → Generate API key → 把明文 token 貼回
#   apps/orion-cowork/.env(或其他 client)的 ORION_MODEL_PROXY_KEY
```

詳細:[`../features/model-proxy.md`](../features/model-proxy.md)

### 5. 直接戳 sidecar(無 Electron)

```bash
echo '{"id":"1","method":"ping"}' | \
  uv run --package orion-cowork-sidecar python -m orion_cowork_sidecar
# → {"event": "sidecar.ready"}
# → {"id": "1", "event": "pong", "final": true}
```

## 卡關 → [troubleshooting.md](./troubleshooting.md)

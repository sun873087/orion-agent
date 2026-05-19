# Setup

從 0 跑通本機 5 個 package。預計 15-30 分鐘。

## 需求

| 工具 | 版本 | 安裝 |
|---|---|---|
| Python | ≥ 3.11 | system / pyenv |
| [uv](https://github.com/astral-sh/uv) | latest | `curl -LsSf https://astral.sh/uv/install.sh \| sh` |
| Node | ≥ 20.19 | system / nvm |
| npm | ≥ 10 | 跟 Node |
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

make install          # uv sync + npm install
```

## 驗證 5 個 package 都裝好

```bash
make test
```

預期 5 行 pass 訊息,914 tests 全綠。

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

Electron 開窗,renderer 載 vite dev server(:5174),sidecar 由 main process 啟動。

**Phase E PoC** 階段,UI 簡陋,但 streaming text + tool call 應該都跑得起來。

### 4. 直接戳 sidecar(無 Electron)

```bash
echo '{"id":"1","method":"ping"}' | \
  uv run --package orion-cowork-sidecar python -m orion_cowork_sidecar
# → {"event": "sidecar.ready"}
# → {"id": "1", "event": "pong", "final": true}
```

## 常見問題

跑不通看 [`troubleshooting.md`](./troubleshooting.md)。

## 下一步

- 對 architecture 沒概念 → [`../architecture/README.md`](../architecture/README.md)
- 想看某 feature → [`../features/README.md`](../features/README.md)
- 想改 code → [`run-tests.md`](./run-tests.md) 跟 [`manual-testing.md`](./manual-testing.md)
- 想 build Cowork 成 `.dmg` 給人裝 → [`build.md`](./build.md)

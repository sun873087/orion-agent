# Orion Model Proxy

**Phase 31-X**。Transparent reverse proxy 包 OpenAI / Anthropic。3 個自家 host
(CLI / Chat / Cowork)透過 env var 把 SDK 的 `base_url` 切過去就走 proxy,
外部任何用 OpenAI / Anthropic SDK 寫的工具也能用同個 endpoint。

**實作位置**:`packages/orion-model-proxy/`

## 為什麼

| 痛點 | Proxy 解什麼 |
|---|---|
| `OPENAI_API_KEY` / `ANTHROPIC_API_KEY` 各 host 各放 `.env` | 1 處(proxy 機)放完所有 host + 工具共用 |
| Cost 各 host 各算 | 集中觀測點(下階段可加 DB 紀錄)|
| 外部工具(LangChain / Cursor / aider)沒辦法跟我們共用 key | base_url 指 proxy 就 work |
| 想 routing / cache / rate limit / failover | 集中加在 proxy(下階段)|

## 架構(極簡)

```
┌──────────────────────────────────────────────┐
│  orion-model-proxy(FastAPI, :9090)            │
│                                                │
│  /openai/{path:path}     ──→ api.openai.com   │
│  /anthropic/{path:path}  ──→ api.anthropic.com │
│  /v1/health[/{provider}]                       │
│                                                │
│  Only:                                         │
│  - 換 Authorization / x-api-key 為 proxy 真 key │
│  - filter hop-by-hop headers                   │
│  - 自動 gzip decompress                        │
│  - SSE / NDJSON streaming 透傳                  │
│                                                │
│  **不解析 body** — 純 byte-for-byte 透傳        │
└──────────────────────────────────────────────┘
                ▲
                │ OpenAI / Anthropic 原生 wire(client 怎麼打 proxy 就怎麼透傳)
                │
   ┌────────────┼─────────────────────────────┐
   │            │                             │
[自家 host]                              [外部 SDK / 工具]
 import orion_model                       LangChain / Cursor / aider /
   provider.get_provider("anthropic"...)  自寫 script(用 OpenAI 或
   audio.transcribe(...)                  Anthropic Python SDK)
   audio.synthesize(...)
   ↑
   SDK 內部 base_url 由 env ORION_MODEL_PROXY_URL 控:
     有設 → AsyncAnthropic(base_url=f"{proxy}/anthropic")
            AsyncOpenAI(base_url=f"{proxy}/openai/v1")
     沒設 → SDK 預設打 api.anthropic.com / api.openai.com
   Ollama 不經 proxy(本機 daemon,proxy 對它無增值)
```

**沒有 Orion-native 中間層** — 之前的 `/v1/messages` + `/v1/audio/*` 抽象冗餘,SDK
本來就會講 OpenAI / Anthropic 原生 wire,直接透傳更乾淨,wire format 跟外部 SDK 共用。

## Quick start

### 1. 啟動 proxy

```bash
export ANTHROPIC_API_KEY=sk-ant-...
export OPENAI_API_KEY=sk-...
# 可選:proxy 自己的 auth token
export ORION_MODEL_PROXY_KEY=$(uuidgen)

make dev-model-proxy
# [orion-model-proxy] listening on http://127.0.0.1:9090
```

可選 env vars:

| Env | 預設 | 說明 |
|---|---|---|
| `ORION_MODEL_PROXY_HOST` | `127.0.0.1` | listen host(對外服改 `0.0.0.0`)|
| `ORION_MODEL_PROXY_PORT` | `9090` | listen port |
| `ORION_MODEL_PROXY_KEY` | — | Bearer token;沒設 = 不認證(本機 dev)|

### 2. 自家 host 切過去

```bash
export ORION_MODEL_PROXY_URL=http://127.0.0.1:9090
# Cowork / CLI / Chat 程式碼**完全不變**,SDK base_url 由 env 控
make dev-cowork   # 或 dev-cli / dev-api
```

### 3. 外部 SDK 用法

**Python OpenAI SDK:**

```python
from openai import OpenAI
client = OpenAI(
    base_url="http://proxy.local:9090/openai/v1",
    api_key="anything",  # client 隨便填,proxy 才有真 key
)

# Chat completions
resp = client.chat.completions.create(model="gpt-4o-mini",
    messages=[{"role": "user", "content": "hi"}])

# Responses API
resp = client.responses.create(model="gpt-4o-mini", input="hi")

# TTS / STT / Embeddings / Files / Fine-tuning — 任何 OpenAI endpoint 自動支援
audio = client.audio.speech.create(model="tts-1", voice="nova", input="hi")
text  = client.audio.transcriptions.create(model="whisper-1", file=open("a.webm","rb"))
emb   = client.embeddings.create(model="text-embedding-3-small", input="hi")
```

**Python Anthropic SDK:**

```python
from anthropic import Anthropic
client = Anthropic(
    base_url="http://proxy.local:9090/anthropic",  # SDK 自動 append /v1
    api_key="anything",
)
resp = client.messages.create(
    model="claude-sonnet-4-6",
    max_tokens=1024,
    messages=[{"role": "user", "content": "hi"}],
)
```

**curl:**

```bash
curl http://proxy.local:9090/openai/v1/chat/completions \
  -H "Authorization: Bearer anything" \
  -H "Content-Type: application/json" \
  -d '{"model":"gpt-4o-mini","messages":[{"role":"user","content":"hi"}]}'
```

## Endpoints

| Path | 用途 |
|---|---|
| `GET /v1/health` | proxy 自家 health + 顯各 provider key 是否設好 |
| `GET /v1/health/{provider}` | per-provider key 狀態 |
| `GET /v1/catalog` | Orion catalog(chat / stt / tts)— **host 必 fetch 這個**,proxy 是唯一 source of truth |
| `ANY /openai/{path:path}` | catch-all transparent proxy → api.openai.com |
| `ANY /anthropic/{path:path}` | catch-all transparent proxy → api.anthropic.com |

**Catch-all 設計**:OpenAI / Anthropic 未來新加任何 endpoint(image / video / files / fine-tuning / vector store / batch ...) **proxy 不必改 code 自動支援**。

## Auth

兩條互不影響:

1. **Proxy 自家 auth**(可選):`ORION_MODEL_PROXY_KEY` env 設了 → request 帶
   `Authorization: Bearer <same>` 才放行。**這層 client 端必須匹配**。
2. **Upstream provider auth**(必要):`OPENAI_API_KEY` / `ANTHROPIC_API_KEY` env
   設在 proxy 那台機。Proxy 收到 request 後**覆寫**對應 header(OpenAI `Authorization`,
   Anthropic `x-api-key`)為真 key。**client 端傳什麼都被覆蓋**。

```
client:  Authorization: Bearer client-token
         x-api-key: anything
              ↓
proxy:  ① 比對 client token 是否 = ORION_MODEL_PROXY_KEY(若有設)
        ② 把 Authorization / x-api-key 覆寫成 server env 內真 key
        ③ forward 到 upstream
```

### Client 端怎麼傳 Bearer

`ORION_MODEL_PROXY_KEY` 同名 env 在 client 端設了就會自動帶上:

- **Anthropic SDK**(只送 `x-api-key`,沒這個 fix 會直接 401):
  `orion_model.anthropic_provider` init 時把 token 塞 `default_headers={"Authorization": f"Bearer ..."}`
- **OpenAI SDK**(本來會送 `Authorization: Bearer <api_key>`):同樣用 `default_headers`
  蓋掉 SDK 自動生成的 Authorization,**不要**把 PROXY token 塞 `api_key` 欄位 — 那是給
  upstream 用的(雖然會被 proxy 覆寫,但語意混淆)
- **`orion_model.audio.stt` / `tts`**(httpx 直發)— Bearer 來源從 `OPENAI_API_KEY`
  改成 `ORION_MODEL_PROXY_KEY`(若 proxy URL 設了)

外部 SDK / 工具(LangChain / Cursor / aider / curl)— 你自己控 Authorization,
直接帶 PROXY token 即可,Orion 不介入。

## 自家 host 怎麼接

`orion_model` 三個層次都靠 env `ORION_MODEL_PROXY_URL` 自動切到 proxy:

### 1. Chat / Audio API call

provider 在 SDK init 時換 base_url:

```python
# packages/orion-model/src/orion_model/anthropic_provider.py
if proxy := os.environ.get("ORION_MODEL_PROXY_URL"):
    client = AsyncAnthropic(
        base_url=f"{proxy}/anthropic",
        api_key=os.environ.get("ANTHROPIC_API_KEY") or "via-proxy",
    )
else:
    client = AsyncAnthropic()  # 直連
```

Caller 完全不必動 — `get_provider("anthropic", "claude-...")` 回的還是 `AnthropicProvider` 實例,只是裡面 SDK 連的是 proxy 不是 api.anthropic.com。

`orion_model.audio.stt` / `audio.tts` 內部 `httpx.post` 的 URL 也走同樣 env-gate(`_openai_base()`)。

### 2. Catalog metadata

`orion_model.catalog.list_catalog()` / `stt_catalog.list_stt_catalog()` /
`tts_catalog.list_tts_catalog()` 內部的 `_load()` 函式優先順序:

1. **proxy `/v1/catalog`**(設了 env 就 fetch)
2. `ORION_MODELS_FILE` override path
3. Packaged `models.json` fallback

```python
# packages/orion-model/src/orion_model/catalog.py
def _fetch_from_proxy() -> ... | None:
    proxy = os.environ.get("ORION_MODEL_PROXY_URL")
    if not proxy:
        return None
    try:
        resp = httpx.get(f"{proxy}/v1/catalog", timeout=5.0)
        return _parse_config(resp.json()["chat"])
    except Exception:
        return None  # 失敗 fallback packaged

@cache
def _load():
    if from_proxy := _fetch_from_proxy():
        return from_proxy
    ...  # 既有 override / packaged path
```

`@functools.cache` 保證一次 process 內只 fetch 一次(proxy 改 catalog 後
host 要重啟才看見;production 想 hot-reload 後續可加 TTL)。

Fetch fail / proxy 不可達自動 fallback 到 packaged json — dev / CI 不必先
起 proxy daemon。但 production 部署時 proxy = source of truth,**catalog
變更(新 model / 改 pricing)只在 proxy 那台機改**,host 重啟就同步。

### 3. 下游函式(自動受惠)

`validate(provider, model)` / `get_pricing(provider, model)` /
`get_max_context_tokens(...)` 等所有讀 catalog 的函式都走 `_load()` 拿同份
資料,**caller 完全不必動**就跟著切到 proxy 來源。

## Phasing

**Phase A — MVP**(本 commit)
- ✅ `/openai/*` + `/anthropic/*` transparent reverse proxy
- ✅ Bearer-token auth(optional)
- ✅ SDK base_url env-gate(provider + audio.stt + audio.tts)
- ✅ Cowork / CLI / Chat zero code change

**Phase B** — Cost tracking + audit log(Postgres `proxy_usage` + admin endpoint)
**Phase C** — Routing alias(`auto-fast` → cheap model;per-user override)
**Phase D** — Cache layer(prompt hash → cached response,proxy 端共用)
**Phase E** — Failover(429 → 切其他 provider)+ rate limit

## 已知限制

- **Proxy 是 SPOF** — 緩解:env unset 立刻 fallback 直連
- **多一跳延遲** — localhost <1 ms,跨網路看 RTT
- **Ollama 不在 proxy 範圍** — 本機 daemon,host 直連最快(無 key 概念,proxy 無增值)
- **無 cost dashboard / DB** — Phase B 才做

## 相關

- `packages/orion-model-proxy/`                                Proxy service
- `packages/orion-model-proxy/.../upstream_proxy.py`            Reverse proxy core
- `packages/orion-model/src/orion_model/{anthropic,openai}_provider.py:__init__` base_url env-gate
- `packages/orion-model/src/orion_model/audio/{stt,tts}.py:_openai_base()`     audio base URL env-gate

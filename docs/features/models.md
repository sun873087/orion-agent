# Models

支援的 LLM provider + 各自行為。

**實作位置**:`packages/orion-model/src/orion_model/`

## Provider 三選一

| Provider | 對應 SDK | Stream | Cache | Reasoning | 計費 |
|---|---|---|---|---|---|
| **Anthropic** | `anthropic`(Python) | SSE event | ✓(5m / 1h TTL)| ✓ thinking blocks | input/output/cache_read/cache_creation per 1M token |
| **OpenAI** | `openai`(Python) | SSE chunks | ✓(prompt_tokens_details.cached_tokens) | ✓ o-series(reasoning_effort) | input/output per 1M token |
| **Ollama** | 本機 HTTP daemon(`localhost:11434`) | NDJSON | ✗ | 部分 model 有 | 免費 |

## 對外 API

```python
from orion_model.provider import get_provider

provider = get_provider("anthropic", "claude-haiku-4-5")
provider = get_provider("openai", "gpt-5-mini")
provider = get_provider("ollama", "qwen3.5:9b")

async for event in provider.stream(
    messages=[...],
    system=[...],
    tools=[...],
    max_tokens=4096,
):
    # NormalizedEvent
    ...
```

## Catalog(`models.json`)

`packages/orion-model/src/orion_model/models.json` — 全 model 的 metadata source of truth:

```json
{
  "providers": [
    {
      "id": "anthropic",
      "label": "Anthropic",
      "models": [
        {
          "id": "claude-haiku-4-5",
          "label": "Claude Haiku 4.5",
          "max_output_tokens": 8192,
          "max_context_tokens": 200000,
          "supports_reasoning": true,
          "pricing": {
            "input": 1.0, "output": 5.0,
            "cache_read": 0.1, "cache_creation": 1.25
          }
        }
      ]
    }
  ]
}
```

`ORION_MODELS_FILE` env override 給 prod 用(改 pricing / 加 / 移 model)。

## Catalog through proxy

`ORION_MODEL_PROXY_URL` 設了時,`list_catalog()` / `list_stt_catalog()` / `list_tts_catalog()`
會優先 fetch proxy 的 `/v1/catalog`(proxy 是 source of truth);fetch fail 退回 packaged JSON。

## STT / TTS

走 `orion_model.audio`:

```python
from orion_model.audio import transcribe, synthesize

stt = await transcribe(
    provider="openai", model="whisper-1",
    audio_base64=b64data, mime_type="audio/webm",
    duration_seconds=30.0, locale="zh-TW",
)

tts = await synthesize(
    provider="openai", model="tts-1",
    voice="nova", speed=1.0, text="Hello!",
)
```

Direct httpx call(非 SDK)— audio 走 transparent proxy 跟 chat 一樣的 `_openai_base()`
gate。

## 各 provider 設定

### Anthropic

```bash
ANTHROPIC_API_KEY=sk-ant-...
# Cache TTL(可選):"5m" / "1h"
ORION_CACHE_TTL_STATIC=1h      # static system prompt
ORION_CACHE_TTL_SESSION=1h     # session-stable dynamic block
ORION_CACHE_TTL_MESSAGES=5m    # rolling messages
```

Cache 行為:Anthropic 計費 1.25× / 2× write,0.1× read。`cache_config.py` 把 system 拆 7 段,各自 cache_control。

### OpenAI

```bash
OPENAI_API_KEY=sk-proj-...
# Reasoning(o-series + gpt-5 family):每 request 設 reasoning_effort
# 由 orion-sdk 在 build_request 時根據 model + ctx 動態加
```

OpenAI cache 是隱式的(`prompt_tokens_details.cached_tokens` 自動回報)— orion 不需要主動標 cache_control。

### Ollama

```bash
# 預設打 localhost:11434,要改:
OLLAMA_HOST=remote-machine:11434
```

Ollama 本機 daemon — 沒 API key。Model 由 user 自己 `ollama pull`。

## 設計取捨

- **NormalizedMessage 跨 provider**:`orion_model.types.NormalizedMessage`(role + content blocks)是內部表示。`translation/` 子模組各 provider 一個 file,翻譯成 wire format。
- **Catalog as JSON**:不寫死在 code,讓 user / prod 可以 override pricing / 加 fine-tuned model。
- **不依賴 third-party catalog SDK**:LiteLLM 之類有他們的 catalog,但 我們對 cache pricing 跟 reasoning effort 行為要可控,自家 catalog 比較精準。

## 限制 / 已知問題

- **OpenAI Realtime API(WebSocket)沒支援**:proxy / 直連都還沒做
- **Cohere / Mistral / 自架 vLLM 沒支援**:要 user 自己接(寫 Provider subclass)
- **Catalog hot reload 沒做**:改 `models.json` 要重啟 host

## 未來方向

- **更多 provider**:Cohere、Mistral、Groq、Google Gemini、xAI Grok
- **WebSocket realtime**:OpenAI Realtime + Anthropic 之後類似 API
- **Catalog hot-reload**:fsnotify 偵測 `models.json` mtime 變化自動重 load
- **Embedding model 抽象**:目前 embedding 走 OpenAI 直連,要有 provider-neutral 介面

## 看完繼續

- [model-proxy.md](./model-proxy.md) — proxy 集中管 key + 計費
- [streaming.md](./streaming.md) — event 流結構
- [prompt-caching.md](./prompt-caching.md) — cache 決策邏輯

# Models / LLM Providers

orion-agent 透過 `LLMProvider` 抽象支援多 provider。Phase 31-L 後共 3 個 provider:

| Provider | Backend | API key | 預設模型 |
|---|---|---|---|
| `anthropic` | Anthropic Messages API | `ANTHROPIC_API_KEY` | `claude-sonnet-4-6` |
| `openai` | OpenAI Responses API | `OPENAI_API_KEY` | `gpt-5` |
| `ollama` | 本機 Ollama daemon(`/api/chat`)| 不需 | 動態(`ollama pull` 過的) |

**實作位置**:`packages/orion-model/src/orion_model/`
- `provider.py` — `LLMProvider` Protocol + `get_provider()` factory
- `{anthropic,openai,ollama}_provider.py` — 三個實作
- `translation/{anthropic,openai,ollama}.py` — wire format ↔ Normalized
- `catalog.py` + `models.json` — 模型表(context window / pricing)

## Caller API

```python
from orion_model.provider import get_provider

provider = get_provider("ollama", "qwen3.5:0.8b")
# 或 get_provider("anthropic", "claude-sonnet-4-6")
# 或 get_provider("openai", "gpt-5")

async for event in provider.stream(system=..., messages=..., tools=...):
    ...
```

3 個 provider 都實作同 `stream()` interface,yield 同套 `NormalizedEvent`(`MessageStart` / `TextDelta` / `ThinkingDelta` / `ToolUseStart/Delta/Stop` / `MessageStop`)。SDK 上層完全不見任何 provider 細節。

---

## Anthropic 設定

最簡單 — 設 API key 即可:

```bash
# .env
ANTHROPIC_API_KEY=sk-ant-...
```

從 [console.anthropic.com](https://console.anthropic.com) 拿 key。

**已知支援 model**(`models.json` 內):
- `claude-opus-4-7` — 最強,$15/$75 per 1M tokens
- `claude-sonnet-4-6` — 平衡,$3/$15
- `claude-haiku-4-5` — 快,$1/$5

---

## OpenAI 設定

```bash
# .env
OPENAI_API_KEY=sk-proj-...
```

從 [platform.openai.com](https://platform.openai.com) 拿 key。

**已知支援 model**(`models.json` 內):`gpt-5.5-pro` / `gpt-5.5` / `gpt-5.4` / `gpt-5.2` / `gpt-5` / `gpt-5-mini` / `gpt-4o` / `gpt-4o-mini` / `o3`。

---

## Ollama 設定(本機 LLM)

跑本機 LLM,**不用 API key、不計費**。99% 場景 zero config — 預設裝完跑得起來。

### 0-config happy path

```bash
# 1. 裝 Ollama(http://ollama.com/download 或 brew install ollama)
brew install ollama

# 2. 起 daemon(背景或另開 terminal)
ollama serve

# 3. 拉 model
ollama pull qwen3.5:0.8b     # 1GB,vision+tools,256K ctx
ollama pull llama3.1:8b      # ~5GB,主流通用
ollama pull qwen2.5:7b       # 中英文好
ollama pull deepseek-coder-v2:16b   # 寫 code 強

# 4. 起 Cowork 對話
cd apps/orion-cowork && pnpm dev

# 5. UI 右下 model pill → Ollama (Local) → 選 model → 對話
```

`.env` **不用設**任何東西。

### 換 port / 遠端 server

只在以下場景才需要設 `.env`:

```bash
# .env

# 本機 Ollama 換 port(預設 11434)
OLLAMA_HOST=localhost:8888

# 遠端 server(內網 / VPN)
OLLAMA_HOST=192.168.1.50:11434
OLLAMA_HOST=https://ollama.lan/

# Cowork 看 .env 沒設 OLLAMA_HOST 就用 http://localhost:11434
```

格式規則(`resolve_ollama_base_url()`):
- 沒 scheme(`host:port`) → 自動補 `http://`
- 完整 URL(`https://...`) → 直接用
- 預設:`http://localhost:11434`

### Model 列表的兩個來源

Ollama 是 **dynamic provider** — `models.json` 內 `ollama` 條目的 `models[]` 是 **static fallback**:

| 場景 | UI 顯示 |
|---|---|
| Daemon 連得上 | 動態走 `ollama.list_models` RPC → `/api/tags`,**user 實際 pull 過的** |
| Daemon 沒在跑 | 顯 `models.json` 內 `ollama.models[]` 條目(灰色 disabled),user 知道有什麼選擇可用 |

**目前 static fallback 只有 `qwen3.5:0.8b`**(Phase 31-L 加)。要擴的話直接改 `packages/orion-model/src/orion_model/models.json`:

```json
{
  "id": "ollama",
  "label": "Ollama (Local)",
  "dynamic": true,
  "models": [
    {
      "id": "qwen3.5:0.8b",
      "label": "Qwen 3.5 · 0.8B(vision+tools, 256K ctx, 1GB)",
      "max_output_tokens": 4096,
      "max_context_tokens": 262144,
      "supports_reasoning": false,
      "pricing": {"input": 0.0, "output": 0.0, "cache_read": 0.0}
    },
    {
      "id": "llama3.1:8b",
      "label": "Llama 3.1 · 8B",
      "max_output_tokens": 4096,
      "max_context_tokens": 128000,
      "supports_reasoning": false,
      "pricing": {"input": 0.0, "output": 0.0, "cache_read": 0.0}
    }
  ]
}
```

或走 `ORION_MODELS_FILE` env override 不動 repo:

```bash
# .env
ORION_MODELS_FILE=/Users/you/my-orion-models.json
```

### Tool calling / vision 支援

不是每個 model 都支援。看 [ollama.com/library](https://ollama.com/library) 各 model 頁的 tag 列表:

| Tag 標籤 | 意義 |
|---|---|
| `tools` | 支援 function calling(Cowork 工具系統能用) |
| `vision` | 支援圖片輸入(`messages[i].images = ["base64..."]`) |
| `thinking` | 支援 reasoning chain(DeepSeek-R1 family 用 `<think>...</think>` inline) |

**Cowork 不會主動偵測**支援度 — 不支援的 model 你叫它呼工具就 silently ignore,純對話正常。要靠 user 自己選對 model。常見 tool-capable:
- `qwen3.5:*` / `qwen2.5:*`
- `llama3.1:*` / `llama3.2:*`
- `mistral-nemo` / `mistral:latest`
- `deepseek-coder-v2:*`

### Debug

UI 顯紅 banner「Ollama 沒在跑」但你確定 daemon 起來了:

```bash
# 看 daemon listen port
curl http://localhost:11434/api/version
# 或
curl http://localhost:11434/api/tags

# 都沒回應 → daemon 沒起 / 防火牆擋 / port 錯
# 有回應 → 看 OLLAMA_HOST .env 是否設錯
```

UI 顯示動態 model 列表為空,但 `ollama list` 看得到:

```bash
# 確認 Cowork sidecar 連到對的 base_url(看 dev console 或 sidecar stderr)
# 若 OLLAMA_HOST 設了但 daemon 不在那 port → 顯空
```

---

## 設計取捨

### 為何 Ollama 走 native(非 OpenAI-compat)?

Ollama 提供 OpenAI-compatible 端點(`/v1/chat/completions`),理論上可以重用 `OpenAIProvider` + `base_url` 覆蓋。**沒走這條路**因為:

1. **Vision format 不同**:Ollama native 用 `messages[i].images = [...]`,OpenAI 用 content list 內 `image_url`。Compat 端點兩邊行為不一致
2. **Tool calling 細節**:Ollama native 的 `tool_calls.arguments` 是 dict(非 stringified JSON),OpenAI 是 string
3. **`<think>` inline reasoning**:DeepSeek-R1 family 在 content 內 emit `<think>...</think>`,native API 比較好處理
4. **Admin endpoints**:`/api/tags`(list)、`/api/show`(metadata)、`/api/pull`(下載)— OpenAI-compat 沒這些,Cowork 動態 model list 要這條

### 為何 catalog 是 static + dynamic 混合?

`models.json` 預定義常用模型 + tool 標記 — 給 daemon 沒開時 UI 仍有東西顯。Daemon 起來後優先用動態列表 — user 實際 pulled 過的才有意義。**不 merge** 避免「明明沒裝卻列在那」的 confusion。

### 為何 Ollama pricing 永遠 $0?

API call 不收錢,但 GPU 時間 / 電費是隱性成本 — 不在 Cowork cost dashboard 算。Cost dashboard 顯 token 數但 $ 標 0,Tooltip 解釋「本地模型不產生 API 費用」(尚未實作)。

---

## 限制 / 已知問題

- **Tool calling 不自動偵測** — 不支援的 model 你勾 tools 它 silently ignore;UI 不警告(Phase 2 想加 `/api/show` 解析 template 偵測)
- **Streaming 慢**:Ollama 序列化 token 經 NDJSON → renderer,本機通常 OK,但 7B+ 模型 prompt 處理可能 5-10s 才開始 stream
- **Concurrent request**:Ollama daemon 預設單請求排隊,Cowork 多 session 同送會堵住(MVP 接受 — local 本來就 single-user)
- **Image 大檔**:Vision model 餵圖時要 base64 encode 整張塞 NDJSON,大圖(>2MB)單 turn 變慢
- **`/api/pull` UI 沒做** — user 自己 `ollama pull <name>` 從 terminal 拉
- **`/api/show` metadata 沒抓** — context_length / parameter_size / quantization 未在 UI 顯示

詳見 [`../roadmap/cowork-wishlist.md`](../roadmap/cowork-wishlist.md) Local model 條目。

---

## 相關

- [agent-loop.md](./agent-loop.md) — `LLMProvider.stream()` 在 query_loop 怎麼用
- [streaming.md](./streaming.md) — provider events → `NormalizedEvent` 轉換
- [tools.md](./tools.md) — `ToolDefinition` 怎麼傳給 provider
- [`../architecture/packages.md`](../architecture/packages.md) — `orion-model` package 結構

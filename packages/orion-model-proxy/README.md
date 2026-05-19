# orion-model-proxy

HTTP proxy server in front of `orion-model`。CLI / Chat / Cowork 透過此 proxy 連
provider(集中 key / cost / routing / cache)。Wire format 走 Orion native
NormalizedMessage,**不是** OpenAI-compat。

## Quick start

```bash
# 跑 proxy(預設 :9090)
export OPENAI_API_KEY=sk-...
export ANTHROPIC_API_KEY=sk-ant-...
# 可選:proxy 自己的 auth key(host 端要設一樣的 ORION_MODEL_PROXY_KEY)
export ORION_MODEL_PROXY_KEY=$(uuidgen)
uv run --package orion-model-proxy orion-model-proxy

# Host 端切過去走 proxy
export ORION_MODEL_PROXY_URL=http://127.0.0.1:9090
export ORION_MODEL_PROXY_KEY=...  # 跟 proxy 一致
```

詳見 [`docs/features/model-proxy.md`](../../docs/features/model-proxy.md)。

# orion-model-proxy

HTTP transparent reverse proxy 包 OpenAI / Anthropic + multi-tenant auth +
per-user 計費。CLI / Chat / Cowork / 任何外部 SDK 都能透過 `base_url` 指過來。

## Quick start

```bash
# 1. Proxy 啟動(預設 :9090)
export OPENAI_API_KEY=sk-...
export ANTHROPIC_API_KEY=sk-ant-...
export ORION_MODEL_PROXY_ADMIN_KEY=$(python -c "import secrets; print(secrets.token_urlsafe(32))")
uv run --package orion-model-proxy orion-model-proxy

# 2. Admin 建 user + 生 token(Web UI 或 REST)
#    瀏覽器開:http://127.0.0.1:9090/admin/ui/
#    Login → New user → Generate API key → 複製明文 token(只顯示一次)

# 3. Host 端切過去 — client 設拿到的 token
export ORION_MODEL_PROXY_URL=http://127.0.0.1:9090
export ORION_MODEL_PROXY_KEY=sk-orion-prod-...
```

## Phase

- **Phase 31-X**:transparent reverse proxy MVP(/openai/{path} + /anthropic/{path})
- **Phase 32**:multi-tenant + DB(users / api_keys / usage_log)+ Admin Web UI +
  hard budget enforcement(超 cap 402)

詳見:
- [`docs/features/model-proxy.md`](../../docs/features/model-proxy.md)
- [`docs/roadmap/plans/32-model-proxy-multi-tenant.md`](../../docs/roadmap/plans/32-model-proxy-multi-tenant.md)

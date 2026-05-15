# orion-agent / api

Multi-LLM agent harness(Anthropic Claude + OpenAI),只用 `anthropic` / `openai` 兩個薄 HTTP wrapper —
**不用** Anthropic Agent SDK、OpenAI Agents SDK、LangChain、LiteLLM 等 agent 框架。

對應 `docs/phases/00-foundation.md`(Phase 0)。

---

## Quick start

```bash
# 安裝
make install                       # = uv sync

# 全綠檢查
make check                         # = lint + typecheck + unit tests

# Demo(需 API key)
export ANTHROPIC_API_KEY=sk-ant-...
make run-anthropic

export OPENAI_API_KEY=sk-...
make run-openai
```

或自訂:

```bash
uv run orion --provider anthropic --model claude-sonnet-4-6 "Read /etc/hosts"
uv run orion --provider openai    --model gpt-5             "Read /etc/hosts"
```

---

## 目錄結構

```
src/orion_agent/
  core/         Tool Protocol、AgentContext
  llm/          LLMProvider abstraction
    types.py            NormalizedMessage / ContentBlock
    events.py           Streaming events(7 種)
    provider.py         LLMProvider Protocol + get_provider() 工廠
    anthropic_provider.py    呼 client.messages.stream()
    openai_provider.py       呼 client.responses.create(stream=True)
    translation/        normalized → 各家 wire format
    pricing.py          每 1M tokens 計費
  services/     feature_flags
  tools/        FileReadTool(Phase 0 唯一示範)
  main.py       CLI entrypoint(typer)
tests/
  unit/         CI 必跑,無 API 呼叫
  integration/  需 API key,user 手動跑
```

---

## Phase 0 範圍 / 限制

✅ LLMProvider 抽象(可同時跑 Claude + GPT)
✅ Streaming events normalized
✅ FileReadTool + Tool Protocol
✅ CLI demo:單 turn streaming → 工具執行印結果

❌ **不**回填工具結果給模型再請求 → 屬 Phase 1 完整 agent loop
❌ FastAPI / WebSocket → Phase 6
❌ Sandbox / permissions → Phase 4

---

## Make targets

| target | 作用 |
|---|---|
| `make install` | `uv sync` |
| `make test` | unit tests(`tests/unit/`) |
| `make test-all` | unit + integration(需 API key) |
| `make typecheck` | `mypy --strict src/` |
| `make lint` | `ruff check` |
| `make format` | `ruff format` |
| `make check` | lint + typecheck + test |
| `make run-anthropic` | demo with Claude |
| `make run-openai` | demo with GPT |

---

## 測試 UI

`../ui/test-ui.html` — 從 Phase 6 之後才會接 FastAPI,目前只是介面樣板,
Phase 0 demo 走 CLI。

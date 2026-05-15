# Integration tests

這些測試會**真的呼叫** Anthropic / OpenAI API,需要 API key 並會花錢。
CI 預設**不**跑這個目錄(`make test` 只跑 `tests/unit/`)。

## 設置

```bash
export ANTHROPIC_API_KEY=sk-ant-...
export OPENAI_API_KEY=sk-...
```

或寫進 `.env`(`uv run` 會自動讀取):

```
ANTHROPIC_API_KEY=sk-ant-...
OPENAI_API_KEY=sk-...
```

## 跑

```bash
# 全部
uv run pytest tests/integration/ -v

# 只跑 Anthropic
uv run pytest tests/integration/ -v -k anthropic

# 只跑 OpenAI
uv run pytest tests/integration/ -v -k openai
```

## 注意

- Phase 0 還沒寫 integration test。Phase 1 + 之後才會加(完整 query loop 才有意義驗證)。
- 此目錄已留位置給後續 phase。

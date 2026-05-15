# orion-model

LLM provider abstraction layer extracted from orion-agent (Phase 30-B).

- Anthropic + OpenAI providers,統一 `NormalizedMessage` / `NormalizedEvent` 介面
- Tool definition schema(`ToolDefinition`,跟 agent runtime 解耦)
- Pricing / cache config / model catalog(`models.json`)

不含 agent loop,適合單純做 prompt 測試 / benchmark / 純 LLM 呼叫場景。

## 使用方式

```python
from orion_model import get_provider

provider = get_provider("anthropic", "claude-sonnet-4-6")
async for event in provider.stream(messages=[...], tools=[...]):
    ...
```

## 依賴關係

- 上游:`anthropic`、`openai`、`httpx`、`pydantic`、`structlog`
- 下游:`orion-sdk`(agent runtime;Phase 30-C 後生效)
- **禁止依賴**:`orion_sdk` / `orion_cli` / `orion_chat_api`(由 import-linter 強制)

"""LLM Provider 抽象層 — Anthropic + OpenAI 雙支援。

Phase 1+ 的 query_loop 透過 `LLMProvider.stream()` 取 normalized events,
完全不見 anthropic / openai SDK 細節。

用法:
  from orion_model.provider import get_provider
  provider = get_provider("anthropic", "claude-sonnet-4-6")
  # 或 get_provider("openai", "gpt-5")

  async for event in provider.stream(system=..., messages=..., tools=...):
      ...
"""

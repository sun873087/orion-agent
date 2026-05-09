# Phase 0:Foundation(基礎建設 + LLM Provider 雙支援)

## 速覽

- **預計時程**:3-4 週
- **前置 Phase**:無(起點)
- **後續 Phase**:Phase 1 完全依賴本 phase 的 `Tool` Protocol、`AgentContext`、`LLMProvider`
- **主要交付物**:
  - Python 專案骨架(pyproject.toml + 工具鏈)
  - **`Tool` Protocol**(Pydantic-based)
  - **`AgentContext` dataclass**(取代 TS `bootstrap/state.ts` 全域狀態)
  - **`LLMProvider` 抽象 + Anthropic + OpenAI 雙實作**(直接呼 HTTP API,不用 Agents SDK)
  - **Normalized event 型別**(Phase 1+ 看不到 SDK 細節)
  - 第一個工具 `FileReadTool`
  - 端到端 demo:**同 prompt 切換 Claude / GPT 都跑通**

## 1. 目標與動機

Phase 0 不寫 agent loop,**搭好「能寫 agent loop」所需的基礎**:

- 型別系統(Tool / AgentContext / Message / Event)
- LLM 雙支援(Anthropic API + OpenAI API,可任意切換 model)
- 一個能跑的工具

完成後 repo 應該:

- `mypy --strict` 全綠
- `pytest` 跑通
- `python -m claude_agent_py --provider anthropic "Read /etc/hosts ..."` 與 `--provider openai` 都能跑同樣對話

**為何 LLM 抽象從 day 1 就做?**

事後做要改 Phase 1-15 全部 code path。Phase 0 多花 0.5-1 週把抽象搭好,後續 Phase 1+ 只見 normalized event 與 LLMProvider Protocol,**完全不見 anthropic / openai 字眼**。

**前提**:不用任何 Agent 框架(Anthropic Agent SDK / OpenAI Agents SDK / LangChain / LiteLLM **都不用**)。直接用兩家最基本的 HTTP wrapper:

```python
# OK(基本 HTTP wrapper):
from anthropic import AsyncAnthropic        # = Anthropic API HTTP client
from openai import AsyncOpenAI                # = OpenAI API HTTP client

# ❌ 不用(Agent 框架):
# from anthropic.agents import ClaudeAgent
# from openai_agents import Agent
# from langchain.agents import ...
# import litellm
```

兩家 Python 套件**只是 OpenAPI client 自動產生的 HTTP wrapper**,不是 agent 框架。Phase 1-15 全部自己寫 agent loop / 工具編排 / streaming 解析。

## 2. TS 源檔映射

| Python 模組 | 對應 TS 源檔 | 注意 |
|---|---|---|
| `src/core/tool.py` | `src/Tool.ts` | Protocol 取代 interface,Pydantic 取代 zod |
| `src/core/state.py` | `src/bootstrap/state.ts` | 改 dataclass,**不要全域可變** |
| `src/llm/types.py` | `src/types/message.ts` | Normalized message + content blocks |
| `src/llm/events.py` | (新)| 統一 streaming event |
| `src/llm/provider.py` | (新)| LLMProvider Protocol |
| `src/llm/anthropic_provider.py` | `src/services/api/claude.ts` 部分 | 直接呼 `messages.stream` |
| `src/llm/openai_provider.py` | (新)| 直接呼 `responses.create` |
| `src/llm/translation/*.py` | (新)| 訊息 / 工具 / 圖片格式翻譯 |
| `src/tools/file/read.py` | `src/tools/FileReadTool/FileReadTool.ts` | 簡化版 |

## 3. 任務拆解

### Week 1:專案骨架

- [ ] 1.1 `poetry init claude-agent-py`(或 `uv init`)
- [ ] 1.2 加入依賴:`anthropic`、`openai`、`pydantic>=2`、`anyio`、`structlog`、`typer`
- [ ] 1.3 dev 依賴:`pytest`、`pytest-asyncio`、`mypy`、`ruff`、`hypothesis`
- [ ] 1.4 設定 `pyproject.toml`:`mypy --strict`、ruff rules、pytest config
- [ ] 1.5 建立目錄骨架(見 § 4)
- [ ] 1.6 `make test`、`make typecheck`、`make lint` 全綠跑通(空檔)
- [ ] 1.7 設定 pre-commit hook(ruff + mypy)
- [ ] 1.8 README.md + LICENSE

### Week 2:核心型別(Tool / AgentContext / Normalized events)

- [ ] 2.1 `src/core/tool.py` — `Tool` Protocol + `ToolInput` + `ToolEvent`
- [ ] 2.2 `src/core/state.py` — `AgentContext` dataclass
- [ ] 2.3 `src/llm/types.py` — `NormalizedMessage` + `ContentBlock`(text / tool_use / tool_result / image / thinking)
- [ ] 2.4 `src/llm/events.py` — Streaming events(`MessageStart` / `TextDelta` / `ToolUseStart` / `ToolUseInputDelta` / `ToolUseStop` / `ThinkingDelta` / `MessageStop`)
- [ ] 2.5 `src/llm/tool_def.py` — 中性 `ToolDefinition`(讓 provider 自翻譯)
- [ ] 2.6 `src/services/feature_flags.py` — runtime feature flags

### Week 3:LLM Provider(Anthropic + OpenAI)

- [ ] 3.1 `src/llm/provider.py` — `LLMProvider` Protocol + `ProviderCapabilities`
- [ ] 3.2 `src/llm/anthropic_provider.py` — 直接呼 `messages.stream(...)`
- [ ] 3.3 `src/llm/translation/anthropic.py` — Normalized → Anthropic 格式
- [ ] 3.4 `src/llm/openai_provider.py` — 直接呼 `responses.create(stream=True, ...)`
- [ ] 3.5 `src/llm/translation/openai.py` — Normalized → OpenAI Responses API 格式
- [ ] 3.6 `src/llm/pricing.py` — per-provider per-model 定價表
- [ ] 3.7 兩 provider 各自單元測試
- [ ] 3.8 **swap test**:同 prompt 跑兩 provider,output 結構一致

### Week 4:第一個工具 + 端到端

- [ ] 4.1 `src/tools/file/read.py` — `FileReadTool`(簡化版)
- [ ] 4.2 `src/main.py` — CLI 進入點(支援 `--provider anthropic|openai`)
- [ ] 4.3 整合測試:模型呼叫 FileReadTool 走完一輪(對 Anthropic / OpenAI 都過)
- [ ] 4.4 寫 Phase 0 心得

## 4. 模組架構與檔案

```
claude-agent-py/
├── pyproject.toml
├── README.md
├── Makefile
├── .pre-commit-config.yaml
├── src/
│   └── claude_agent_py/
│       ├── __init__.py
│       ├── main.py                      # CLI 進入點(臨時)
│       │
│       ├── core/
│       │   ├── tool.py                  # ◀ Tool Protocol
│       │   └── state.py                 # ◀ AgentContext
│       │
│       ├── llm/                         # ◀ LLM Provider 抽象 + 雙實作
│       │   ├── types.py                 # NormalizedMessage / ContentBlock
│       │   ├── events.py                # Streaming events
│       │   ├── tool_def.py              # 中性 ToolDefinition
│       │   ├── provider.py              # LLMProvider Protocol + factory
│       │   ├── anthropic_provider.py    # 直接呼 Anthropic API
│       │   ├── openai_provider.py       # 直接呼 OpenAI Responses API
│       │   ├── pricing.py               # 定價表
│       │   └── translation/
│       │       ├── anthropic.py
│       │       └── openai.py
│       │
│       ├── services/
│       │   └── feature_flags.py
│       │
│       └── tools/
│           └── file/
│               └── read.py              # ◀ FileReadTool
│
└── tests/
    ├── conftest.py
    ├── unit/
    │   ├── test_tool_protocol.py
    │   ├── test_agent_context.py
    │   ├── llm/
    │   │   ├── test_anthropic_provider.py
    │   │   ├── test_openai_provider.py
    │   │   ├── test_translation_anthropic.py
    │   │   └── test_translation_openai.py
    │   └── tools/
    │       └── test_file_read.py
    └── integration/
        ├── test_swap_provider.py        # ◀ 關鍵:雙 provider 跑同 prompt
        └── test_first_turn.py
```

## 5. Python Skeleton

### 5.1 `core/tool.py`

```python
"""Tool Protocol。對應 TS Tool interface。Python 用 Protocol + Pydantic 取代 zod + buildTool。"""
from __future__ import annotations
from typing import Protocol, runtime_checkable, AsyncIterator, TypeVar
from pydantic import BaseModel


class ToolInput(BaseModel):
    model_config = {"extra": "forbid"}


class TextEvent(BaseModel):
    type: str = "text"
    text: str


class ProgressEvent(BaseModel):
    type: str = "progress"
    data: dict


class ErrorEvent(BaseModel):
    type: str = "error"
    message: str
    is_recoverable: bool = False


ToolEvent = TextEvent | ProgressEvent | ErrorEvent

Input_T = TypeVar("Input_T", bound=ToolInput)


@runtime_checkable
class Tool(Protocol[Input_T]):
    name: str
    input_schema: type[Input_T]
    description: str

    async def call(self, input: Input_T, ctx: "AgentContext") -> AsyncIterator[ToolEvent]:
        ...

    def is_concurrency_safe(self, input: Input_T) -> bool:
        return False  # 預設保守

    def is_read_only(self, input: Input_T) -> bool:
        return False

    def max_result_size_chars(self) -> int | float:
        return 100_000
```

### 5.2 `core/state.py`

```python
"""AgentContext — 取代 TS bootstrap/state.ts 全域狀態。每 conversation 一個。"""
from __future__ import annotations
from dataclasses import dataclass, field
from pathlib import Path
from uuid import UUID, uuid4
import anyio


@dataclass
class TokenBudget:
    max_input_tokens: int = 200_000
    max_output_tokens: int = 8_192
    used_input_tokens: int = 0
    used_output_tokens: int = 0


@dataclass
class AgentContext:
    session_id: UUID = field(default_factory=uuid4)
    cwd: Path = field(default_factory=Path.cwd)
    abort_event: anyio.Event = field(default_factory=anyio.Event)
    token_budget: TokenBudget = field(default_factory=TokenBudget)
    feature_flags: dict[str, bool] = field(default_factory=dict)

    def feature(self, name: str) -> bool:
        return self.feature_flags.get(name, False)
```

### 5.3 `llm/types.py`

```python
"""Normalized 訊息型別。Phase 1+ 只見這些,看不到 anthropic / openai 細節。"""
from __future__ import annotations
from typing import Literal
from pydantic import BaseModel


class TextBlock(BaseModel):
    type: Literal["text"] = "text"
    text: str


class ToolUseBlock(BaseModel):
    type: Literal["tool_use"] = "tool_use"
    id: str
    name: str
    input: dict


class ToolResultBlock(BaseModel):
    type: Literal["tool_result"] = "tool_result"
    tool_use_id: str
    content: str | list
    is_error: bool = False


class ImageBlock(BaseModel):
    type: Literal["image"] = "image"
    media_type: str  # "image/png" / "image/jpeg" / ...
    data: str         # base64


class ThinkingBlock(BaseModel):
    """Anthropic extended thinking + OpenAI o-series reasoning 共用。"""
    type: Literal["thinking"] = "thinking"
    text: str


ContentBlock = TextBlock | ToolUseBlock | ToolResultBlock | ImageBlock | ThinkingBlock


class NormalizedMessage(BaseModel):
    role: Literal["user", "assistant", "system"]
    content: str | list[ContentBlock]
```

### 5.4 `llm/events.py`

```python
"""Streaming events。Phase 1 query_loop 接收這些 normalized event。"""
from __future__ import annotations
from typing import Literal
from dataclasses import dataclass
from pydantic import BaseModel


@dataclass
class NormalizedUsage:
    input_tokens: int
    output_tokens: int
    cache_read_tokens: int = 0
    cache_creation_tokens: int = 0
    reasoning_tokens: int = 0  # OpenAI o-series 的 reasoning


class MessageStartEvent(BaseModel):
    type: Literal["message_start"] = "message_start"
    message_id: str
    model: str


class TextDeltaEvent(BaseModel):
    type: Literal["text_delta"] = "text_delta"
    text: str


class ThinkingDeltaEvent(BaseModel):
    type: Literal["thinking_delta"] = "thinking_delta"
    text: str


class ToolUseStartEvent(BaseModel):
    type: Literal["tool_use_start"] = "tool_use_start"
    block_index: int
    tool_use_id: str
    tool_name: str


class ToolUseInputDeltaEvent(BaseModel):
    type: Literal["tool_use_input_delta"] = "tool_use_input_delta"
    block_index: int
    partial_json: str


class ToolUseStopEvent(BaseModel):
    type: Literal["tool_use_stop"] = "tool_use_stop"
    block_index: int
    tool_use_id: str
    tool_name: str
    full_input: dict


class MessageStopEvent(BaseModel):
    type: Literal["message_stop"] = "message_stop"
    stop_reason: Literal["end_turn", "max_tokens", "stop_sequence", "tool_use", "content_filter", "error"]
    usage: NormalizedUsage


NormalizedEvent = (
    MessageStartEvent | TextDeltaEvent | ThinkingDeltaEvent
    | ToolUseStartEvent | ToolUseInputDeltaEvent | ToolUseStopEvent
    | MessageStopEvent
)
```

### 5.5 `llm/tool_def.py`

```python
"""中性 Tool 定義。各 provider 自翻譯。"""
from pydantic import BaseModel


class ToolDefinition(BaseModel):
    """送給模型看的工具定義。Phase 0 的 Tool 透過
    .input_schema.model_json_schema() 產生這個。"""
    name: str
    description: str
    input_schema: dict
    cache_control: bool = False  # Anthropic only,標 cache breakpoint
```

### 5.6 `llm/provider.py`

```python
"""LLMProvider Protocol。"""
from __future__ import annotations
from typing import Protocol, AsyncIterator, Literal
from dataclasses import dataclass

from claude_agent_py.llm.types import NormalizedMessage
from claude_agent_py.llm.events import NormalizedEvent
from claude_agent_py.llm.tool_def import ToolDefinition


@dataclass
class ProviderCapabilities:
    prompt_caching: bool       # 手動 cache_control
    auto_caching: bool          # 自動 caching(OpenAI)
    parallel_tool_calls: bool
    native_mcp: bool
    structured_output: bool
    reasoning_blocks: bool
    max_context_tokens: int


class LLMProvider(Protocol):
    name: str  # "anthropic" / "openai"
    model: str
    capabilities: ProviderCapabilities

    async def stream(
        self,
        *,
        system: str | list[str],
        messages: list[NormalizedMessage],
        tools: list[ToolDefinition] | None = None,
        max_tokens: int = 4096,
        temperature: float | None = None,
        cache_breakpoints: list[int] | None = None,
        reasoning_effort: Literal["minimal", "low", "medium", "high"] | None = None,
    ) -> AsyncIterator[NormalizedEvent]:
        ...

    def estimate_cost(
        self, *, input_tokens: int, output_tokens: int,
        cache_read_tokens: int = 0, cache_creation_tokens: int = 0,
        reasoning_tokens: int = 0,
    ) -> float:
        ...


def get_provider(provider_name: str, model: str) -> LLMProvider:
    """工廠。"""
    if provider_name == "anthropic":
        from claude_agent_py.llm.anthropic_provider import AnthropicProvider
        return AnthropicProvider(model=model)
    elif provider_name == "openai":
        from claude_agent_py.llm.openai_provider import OpenAIProvider
        return OpenAIProvider(model=model)
    raise ValueError(f"Unknown provider: {provider_name}")
```

### 5.7 `llm/anthropic_provider.py`

```python
"""直接呼 Anthropic Messages API HTTP 端點(透過 anthropic 套件 = HTTP wrapper)。"""
from __future__ import annotations
from typing import AsyncIterator, Literal
import json

from anthropic import AsyncAnthropic

from claude_agent_py.llm.provider import LLMProvider, ProviderCapabilities
from claude_agent_py.llm.types import NormalizedMessage
from claude_agent_py.llm.events import (
    NormalizedEvent, NormalizedUsage,
    MessageStartEvent, TextDeltaEvent, ThinkingDeltaEvent,
    ToolUseStartEvent, ToolUseInputDeltaEvent, ToolUseStopEvent, MessageStopEvent,
)
from claude_agent_py.llm.tool_def import ToolDefinition
from claude_agent_py.llm.translation.anthropic import (
    translate_messages_to_anthropic, translate_tools_to_anthropic, apply_cache_breakpoints,
)


class AnthropicProvider:
    name = "anthropic"

    _MODEL_LIMITS = {
        "claude-opus-4-7": 200_000,
        "claude-sonnet-4-6": 200_000,
        "claude-haiku-4-5": 200_000,
    }

    def __init__(self, model: str = "claude-sonnet-4-6", client: AsyncAnthropic | None = None):
        self.model = model
        self.client = client or AsyncAnthropic()
        self.capabilities = ProviderCapabilities(
            prompt_caching=True, auto_caching=False,
            parallel_tool_calls=True, native_mcp=True, structured_output=False,
            reasoning_blocks=model.startswith("claude-opus-4") or model.startswith("claude-sonnet-4-7"),
            max_context_tokens=self._MODEL_LIMITS.get(model, 200_000),
        )

    async def stream(self, *, system, messages, tools=None, max_tokens=4096,
                     temperature=None, cache_breakpoints=None, reasoning_effort=None,
                     ) -> AsyncIterator[NormalizedEvent]:
        anthropic_messages = translate_messages_to_anthropic(messages)
        anthropic_tools = translate_tools_to_anthropic(tools or [])

        if isinstance(system, str):
            system_param = system
        else:
            system_param = [
                {"type": "text", "text": s,
                 **({"cache_control": {"type": "ephemeral"}} if i == len(system) - 1 else {})}
                for i, s in enumerate(system)
            ]

        if cache_breakpoints:
            anthropic_messages = apply_cache_breakpoints(anthropic_messages, cache_breakpoints)

        kwargs = {}
        if self.capabilities.reasoning_blocks and reasoning_effort:
            kwargs["thinking"] = {"type": "enabled", "budget_tokens": {
                "minimal": 1024, "low": 4096, "medium": 16384, "high": 32768,
            }[reasoning_effort]}
        if temperature is not None:
            kwargs["temperature"] = temperature

        # 直接呼 Anthropic API HTTP 端點
        async with self.client.messages.stream(
            model=self.model,
            system=system_param,
            messages=anthropic_messages,
            tools=anthropic_tools or None,
            max_tokens=max_tokens,
            **kwargs,
        ) as stream:
            current_block_idx = None
            current_tool_id = None
            current_tool_name = None
            current_partial_json = ""

            async for event in stream:
                etype = event.type

                if etype == "message_start":
                    yield MessageStartEvent(message_id=event.message.id, model=event.message.model)

                elif etype == "content_block_start":
                    block = event.content_block
                    current_block_idx = event.index
                    if block.type == "tool_use":
                        current_tool_id = block.id
                        current_tool_name = block.name
                        current_partial_json = ""
                        yield ToolUseStartEvent(
                            block_index=current_block_idx,
                            tool_use_id=current_tool_id,
                            tool_name=current_tool_name,
                        )

                elif etype == "content_block_delta":
                    delta = event.delta
                    if delta.type == "text_delta":
                        yield TextDeltaEvent(text=delta.text)
                    elif delta.type == "thinking_delta":
                        yield ThinkingDeltaEvent(text=delta.thinking)
                    elif delta.type == "input_json_delta":
                        current_partial_json += delta.partial_json
                        yield ToolUseInputDeltaEvent(
                            block_index=current_block_idx,
                            partial_json=delta.partial_json,
                        )

                elif etype == "content_block_stop":
                    if current_tool_id is not None:
                        try:
                            full_input = json.loads(current_partial_json) if current_partial_json else {}
                        except json.JSONDecodeError:
                            full_input = {"_parse_error": current_partial_json}
                        yield ToolUseStopEvent(
                            block_index=current_block_idx,
                            tool_use_id=current_tool_id,
                            tool_name=current_tool_name,
                            full_input=full_input,
                        )
                        current_tool_id = None

                elif etype == "message_stop":
                    final = await stream.get_final_message()
                    yield MessageStopEvent(
                        stop_reason=final.stop_reason or "end_turn",
                        usage=NormalizedUsage(
                            input_tokens=final.usage.input_tokens,
                            output_tokens=final.usage.output_tokens,
                            cache_read_tokens=getattr(final.usage, "cache_read_input_tokens", 0) or 0,
                            cache_creation_tokens=getattr(final.usage, "cache_creation_input_tokens", 0) or 0,
                        ),
                    )

    def estimate_cost(self, **usage) -> float:
        from claude_agent_py.llm.pricing import PRICING
        p = PRICING["anthropic"][self.model]
        return (
            usage.get("input_tokens", 0) * p["input"] / 1e6
            + usage.get("output_tokens", 0) * p["output"] / 1e6
            + usage.get("cache_read_tokens", 0) * p["cache_read"] / 1e6
            + usage.get("cache_creation_tokens", 0) * p["cache_creation"] / 1e6
        )
```

### 5.8 `llm/openai_provider.py`

```python
"""直接呼 OpenAI Responses API HTTP 端點(透過 openai 套件 = HTTP wrapper)。"""
from __future__ import annotations
from typing import AsyncIterator, Literal
import json

from openai import AsyncOpenAI

from claude_agent_py.llm.provider import LLMProvider, ProviderCapabilities
from claude_agent_py.llm.types import NormalizedMessage
from claude_agent_py.llm.events import (
    NormalizedEvent, NormalizedUsage,
    MessageStartEvent, TextDeltaEvent, ThinkingDeltaEvent,
    ToolUseStartEvent, ToolUseInputDeltaEvent, ToolUseStopEvent, MessageStopEvent,
)
from claude_agent_py.llm.tool_def import ToolDefinition
from claude_agent_py.llm.translation.openai import (
    translate_messages_to_openai, translate_tools_to_openai,
)


class OpenAIProvider:
    name = "openai"

    _MODEL_LIMITS = {
        "gpt-5.4":     1_000_000, "gpt-5":      1_000_000, "gpt-5-mini": 1_000_000,
        "gpt-4o":      128_000,   "gpt-4o-mini":128_000,   "o3":         200_000,
    }

    def __init__(self, model: str = "gpt-5", client: AsyncOpenAI | None = None):
        self.model = model
        self.client = client or AsyncOpenAI()
        is_reasoning = model.startswith("o") or model.startswith("gpt-5")
        self.capabilities = ProviderCapabilities(
            prompt_caching=False,        # 沒手動 cache_control
            auto_caching=True,            # 但 prefix>1024 tokens 自動 cache
            parallel_tool_calls=True, native_mcp=True, structured_output=True,
            reasoning_blocks=is_reasoning,
            max_context_tokens=self._MODEL_LIMITS.get(model, 128_000),
        )

    async def stream(self, *, system, messages, tools=None, max_tokens=4096,
                     temperature=None, cache_breakpoints=None, reasoning_effort=None,
                     ) -> AsyncIterator[NormalizedEvent]:
        # OpenAI 不支 cache_control,system list 拼成單字串
        system_str = system if isinstance(system, str) else "\n\n".join(system)
        openai_input = translate_messages_to_openai(messages, system=system_str)
        openai_tools = translate_tools_to_openai(tools or [])

        kwargs = {}
        if temperature is not None:
            kwargs["temperature"] = temperature
        if self.capabilities.reasoning_blocks and reasoning_effort:
            kwargs["reasoning"] = {"effort": reasoning_effort}

        # 直接呼 OpenAI Responses API
        stream_obj = await self.client.responses.create(
            model=self.model,
            input=openai_input,
            tools=openai_tools or None,
            stream=True,
            max_output_tokens=max_tokens,
            **kwargs,
        )

        current_block_idx = None
        current_tool_id = None
        current_tool_name = None
        current_partial_args = ""

        async for event in stream_obj:
            etype = event.type

            if etype == "response.created":
                yield MessageStartEvent(message_id=event.response.id, model=self.model)

            elif etype == "response.output_text.delta":
                yield TextDeltaEvent(text=event.delta)

            elif etype == "response.reasoning.delta":
                yield ThinkingDeltaEvent(text=event.delta)

            elif etype == "response.output_item.added":
                item = event.item
                if item.type == "function_call":
                    current_block_idx = event.output_index
                    current_tool_id = item.call_id
                    current_tool_name = item.name
                    current_partial_args = ""
                    yield ToolUseStartEvent(
                        block_index=current_block_idx,
                        tool_use_id=current_tool_id,
                        tool_name=current_tool_name,
                    )

            elif etype == "response.function_call_arguments.delta":
                current_partial_args += event.delta
                yield ToolUseInputDeltaEvent(
                    block_index=current_block_idx,
                    partial_json=event.delta,
                )

            elif etype == "response.output_item.done":
                item = event.item
                if item.type == "function_call":
                    try:
                        full_input = json.loads(current_partial_args) if current_partial_args else {}
                    except json.JSONDecodeError:
                        full_input = {"_parse_error": current_partial_args}
                    yield ToolUseStopEvent(
                        block_index=current_block_idx,
                        tool_use_id=current_tool_id,
                        tool_name=current_tool_name,
                        full_input=full_input,
                    )
                    current_tool_id = None

            elif etype == "response.completed":
                response = event.response
                stop_reason = self._map_stop_reason(response.status, response.incomplete_details)
                yield MessageStopEvent(
                    stop_reason=stop_reason,
                    usage=NormalizedUsage(
                        input_tokens=response.usage.input_tokens,
                        output_tokens=response.usage.output_tokens,
                        cache_read_tokens=response.usage.input_tokens_details.cached_tokens or 0,
                        cache_creation_tokens=0,
                        reasoning_tokens=response.usage.output_tokens_details.reasoning_tokens or 0,
                    ),
                )

    def _map_stop_reason(self, status, incomplete) -> str:
        if status == "completed":
            return "end_turn"
        if incomplete and incomplete.reason == "max_output_tokens":
            return "max_tokens"
        return "error" if status == "incomplete" else "end_turn"

    def estimate_cost(self, **usage) -> float:
        from claude_agent_py.llm.pricing import PRICING
        p = PRICING["openai"][self.model]
        return (
            usage.get("input_tokens", 0) * p["input"] / 1e6
            + usage.get("output_tokens", 0) * p["output"] / 1e6
            + usage.get("cache_read_tokens", 0) * p["cache_read"] / 1e6
        )
```

### 5.9 `llm/translation/anthropic.py`

```python
"""Normalized → Anthropic 格式翻譯。"""
from claude_agent_py.llm.types import NormalizedMessage, ContentBlock
from claude_agent_py.llm.tool_def import ToolDefinition


def translate_messages_to_anthropic(messages: list[NormalizedMessage]) -> list[dict]:
    result = []
    for m in messages:
        if m.role == "system":
            continue  # Anthropic system 在 top-level
        if isinstance(m.content, str):
            result.append({"role": m.role, "content": m.content})
            continue
        result.append({"role": m.role, "content": [_block_to_anthropic(b) for b in m.content]})
    return result


def _block_to_anthropic(block: ContentBlock) -> dict:
    if block.type == "text":
        return {"type": "text", "text": block.text}
    if block.type == "tool_use":
        return {"type": "tool_use", "id": block.id, "name": block.name, "input": block.input}
    if block.type == "tool_result":
        return {"type": "tool_result", "tool_use_id": block.tool_use_id,
                "content": block.content, "is_error": block.is_error}
    if block.type == "image":
        return {"type": "image", "source": {
            "type": "base64", "media_type": block.media_type, "data": block.data,
        }}
    if block.type == "thinking":
        return {"type": "thinking", "thinking": block.text}
    raise ValueError(f"Unknown block type: {block.type}")


def translate_tools_to_anthropic(tools: list[ToolDefinition]) -> list[dict]:
    result = []
    for t in tools:
        d = {"name": t.name, "description": t.description, "input_schema": t.input_schema}
        if t.cache_control:
            d["cache_control"] = {"type": "ephemeral"}
        result.append(d)
    return result


def apply_cache_breakpoints(messages: list[dict], breakpoints: list[int]) -> list[dict]:
    for idx in breakpoints:
        if idx < len(messages):
            content = messages[idx]["content"]
            if isinstance(content, list) and content:
                content[-1]["cache_control"] = {"type": "ephemeral"}
    return messages
```

### 5.10 `llm/translation/openai.py`

```python
"""Normalized → OpenAI Responses API 格式翻譯。"""
import json
from claude_agent_py.llm.types import NormalizedMessage, ContentBlock
from claude_agent_py.llm.tool_def import ToolDefinition


def translate_messages_to_openai(
    messages: list[NormalizedMessage], *, system: str | None = None,
) -> list[dict]:
    """Responses API input 是 list of items。"""
    result = []
    if system:
        result.append({
            "type": "message", "role": "system",
            "content": [{"type": "input_text", "text": system}],
        })

    for m in messages:
        if m.role == "system":
            continue
        if isinstance(m.content, str):
            key = "input_text" if m.role == "user" else "output_text"
            result.append({"type": "message", "role": m.role,
                           "content": [{"type": key, "text": m.content}]})
            continue

        message_content = []
        for block in m.content:
            if block.type == "text":
                key = "input_text" if m.role == "user" else "output_text"
                message_content.append({"type": key, "text": block.text})
            elif block.type == "image":
                message_content.append({
                    "type": "input_image",
                    "image_url": f"data:{block.media_type};base64,{block.data}",
                })
            elif block.type == "tool_use":
                if message_content:
                    result.append({"type": "message", "role": m.role, "content": message_content})
                    message_content = []
                result.append({
                    "type": "function_call",
                    "call_id": block.id, "name": block.name,
                    "arguments": json.dumps(block.input),
                })
            elif block.type == "tool_result":
                if message_content:
                    result.append({"type": "message", "role": m.role, "content": message_content})
                    message_content = []
                result.append({
                    "type": "function_call_output",
                    "call_id": block.tool_use_id,
                    "output": block.content if isinstance(block.content, str) else json.dumps(block.content),
                })
            # thinking 不送回(OpenAI 模型自己 emit,client 不該回送)

        if message_content:
            result.append({"type": "message", "role": m.role, "content": message_content})

    return result


def translate_tools_to_openai(tools: list[ToolDefinition]) -> list[dict]:
    return [{"type": "function", "name": t.name, "description": t.description,
             "parameters": t.input_schema} for t in tools]
```

### 5.11 `llm/pricing.py`

```python
"""Per-provider per-model 定價(USD per 1M tokens,2026/05)。"""

PRICING = {
    "anthropic": {
        "claude-opus-4-7":   {"input": 15.0, "output": 75.0, "cache_creation": 18.75, "cache_read": 1.50},
        "claude-sonnet-4-6": {"input":  3.0, "output": 15.0, "cache_creation":  3.75, "cache_read": 0.30},
        "claude-haiku-4-5":  {"input":  1.0, "output":  5.0, "cache_creation":  1.25, "cache_read": 0.10},
    },
    "openai": {
        "gpt-5.4":     {"input": 5.0,  "output": 20.0, "cache_read": 1.25},
        "gpt-5":       {"input": 2.5,  "output": 10.0, "cache_read": 0.625},
        "gpt-5-mini":  {"input": 0.25, "output": 1.0,  "cache_read": 0.0625},
        "gpt-4o":      {"input": 2.5,  "output": 10.0, "cache_read": 1.25},
        "gpt-4o-mini": {"input": 0.15, "output": 0.60, "cache_read": 0.075},
        "o3":          {"input": 5.0,  "output": 20.0, "cache_read": 1.25},
    },
}
```

### 5.12 `tools/file/read.py`

```python
"""FileReadTool — 第一個工具,簡化版(只支援文字檔)。"""
from __future__ import annotations
from pathlib import Path
from typing import AsyncIterator

from claude_agent_py.core.tool import Tool, ToolInput, ToolEvent, TextEvent, ErrorEvent
from claude_agent_py.core.state import AgentContext


class FileReadInput(ToolInput):
    file_path: str
    offset: int | None = None
    limit: int | None = None


class FileReadTool:
    name = "Read"
    description = "Read contents of a file."
    input_schema = FileReadInput

    def is_concurrency_safe(self, input): return True
    def is_read_only(self, input): return True
    def max_result_size_chars(self): return float("inf")

    async def call(self, input: FileReadInput, ctx: AgentContext) -> AsyncIterator[ToolEvent]:
        path = Path(input.file_path)
        if not path.is_absolute():
            yield ErrorEvent(message=f"path must be absolute: {input.file_path}")
            return
        if not path.exists():
            yield ErrorEvent(message=f"file not found: {input.file_path}")
            return
        try:
            content = path.read_text(encoding="utf-8")
        except UnicodeDecodeError:
            yield ErrorEvent(message=f"file is not utf-8: {input.file_path}")
            return

        lines = content.splitlines()
        start = (input.offset - 1) if input.offset else 0
        end = (start + input.limit) if input.limit else len(lines)
        yield TextEvent(text="\n".join(lines[start:end]))
```

### 5.13 `main.py`(支援 `--provider` 切換)

```python
"""Phase 0 臨時 CLI,測試雙 provider。"""
from __future__ import annotations
import asyncio, sys, argparse, json

from claude_agent_py.core.state import AgentContext
from claude_agent_py.llm.provider import get_provider
from claude_agent_py.llm.types import NormalizedMessage
from claude_agent_py.llm.tool_def import ToolDefinition
from claude_agent_py.llm.events import (
    TextDeltaEvent, ToolUseStopEvent, MessageStopEvent, ThinkingDeltaEvent,
)
from claude_agent_py.tools.file.read import FileReadTool


async def main(provider_name: str, model: str, prompt: str) -> None:
    ctx = AgentContext()
    provider = get_provider(provider_name, model)
    tool = FileReadTool()

    tool_def = ToolDefinition(
        name=tool.name,
        description=tool.description,
        input_schema=tool.input_schema.model_json_schema(),
    )

    print(f"[{provider_name}/{model}] {prompt}")
    messages = [NormalizedMessage(role="user", content=prompt)]

    pending_tool_use = None
    async for event in provider.stream(
        system="You are an agent. Use the Read tool when asked to read files.",
        messages=messages,
        tools=[tool_def],
    ):
        if isinstance(event, TextDeltaEvent):
            print(event.text, end="", flush=True)
        elif isinstance(event, ThinkingDeltaEvent):
            print(f"\n[thinking] {event.text}", end="", flush=True)
        elif isinstance(event, ToolUseStopEvent):
            print(f"\n[tool_use] {event.tool_name}({event.full_input})")
            pending_tool_use = event
        elif isinstance(event, MessageStopEvent):
            print(f"\n[stop_reason: {event.stop_reason}]")
            print(f"[cost ≈ ${provider.estimate_cost(**event.usage.__dict__):.5f}]")

    # 簡化:若有 tool_use,跑工具(完整迴圈在 Phase 1)
    if pending_tool_use:
        input_obj = tool.input_schema.model_validate(pending_tool_use.full_input)
        async for ev in tool.call(input_obj, ctx):
            print(f"[tool_result] {ev}")


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--provider", choices=["anthropic", "openai"], default="anthropic")
    parser.add_argument("--model", default="claude-sonnet-4-6")
    parser.add_argument("prompt", nargs="+")
    args = parser.parse_args()
    asyncio.run(main(args.provider, args.model, " ".join(args.prompt)))
```

## 6. 設計決策與取捨

### 為何 Phase 0 從一開始就做 LLM 抽象?

事後改要動 Phase 1-15 全部。多 0.5-1 週做對抽象,**整個專案永遠不見 anthropic / openai 字眼在 Phase 1+ 程式碼**。

### 為何 `LLMProvider` Protocol 而非 abstract class?

Protocol = duck typing,不需要顯式 inherit。第三家(Gemini / Bedrock)自己實作四個 method 就能用。

### 為何不用 LiteLLM / LangChain?

- LiteLLM:**失去 cache_control / structured_output 等 provider-specific feature 控制權**
- LangChain:過度抽象,debug 困難,且本來就建議「自己手寫 agent loop」(Phase 1)

直接用兩家**最薄的 HTTP wrapper**(`anthropic` / `openai` 套件)+ 自寫翻譯層 = 完全控制 + 可預測行為。

### 為何 `cache_breakpoints` 在 LLMProvider 介面但 OpenAI 忽略?

capability 駕馭。`provider.capabilities.prompt_caching` 偵測,呼叫端條件性傳。OpenAI 端忽略此參數(自動 cache 不需控制)。

比 `if isinstance(provider, AnthropicProvider)` 乾淨。

### 為何用 Pydantic v2?

- `model_json_schema()` 自動產 JSON Schema 給 Anthropic / OpenAI 用
- 嚴格驗證 + 好的型別提示
- v1 已 deprecated

### 為何 `AgentContext` 是 dataclass 不是 module-level state?

TS bootstrap/state.ts 是 module-level mutable。Python 改 dataclass:
- 測試時 reset 容易(直接 new)
- 多 session 隔離自動
- 型別清晰

這是 Python port **比 TS 原版乾淨**的地方。

### Anthropic / OpenAI 本質差異(無法統一,只能翻譯)

| 差異 | 影響 |
|---|---|
| Anthropic system 在 top-level,OpenAI 在 messages[0] | translation 處理 |
| Anthropic content blocks list,OpenAI tool_call 是獨立 item | translation 處理 |
| Anthropic prompt cache 手動,OpenAI 自動 | capability flag 條件 |
| Anthropic structured output 用假工具,OpenAI 有 response_format | capability flag 條件 |

### Phase 0 故意不做的

| 項目 | 留給哪個 phase |
|---|---|
| 完整多輪 query loop | Phase 1 |
| 工具 result 包成 ToolResultBlock 回模型 | Phase 1 |
| canUseTool / 權限 | Phase 1 |
| 並發 / sibling abort | Phase 1 |
| Hook | Phase 8 |
| Memory / system prompt 組裝 | Phase 3-4 |
| 錯誤分類 / fallback model / retry | Phase 1+ |

## 7. 驗收標準

### 自動測試

```bash
pytest tests/ --cov=claude_agent_py
mypy --strict src/
ruff check src/ tests/
```

關鍵測試:

- `test_tool_protocol.py` — `runtime_checkable` 驗 `FileReadTool` 滿足 `Tool`
- `test_anthropic_provider.py` — translation + streaming events 正確
- `test_openai_provider.py` — 同上
- `test_translation_anthropic.py` — 訊息 / 工具 / 圖片往返 byte-identical
- `test_translation_openai.py` — 同上
- **`test_swap_provider.py`(關鍵)** — 同 prompt / 同 tools 跑兩 provider,output 結構一致
- `test_file_read.py` — 各邊界情境

### 手動驗證

```bash
# 用 Anthropic
python -m claude_agent_py --provider anthropic --model claude-sonnet-4-6 \
  "Read /etc/hosts and tell me what's in it"

# 用 OpenAI
python -m claude_agent_py --provider openai --model gpt-5 \
  "Read /etc/hosts and tell me what's in it"
```

兩者都應該:
1. Streaming 文字逐字輸出
2. 看到 `[tool_use] Read({'file_path': '/etc/hosts'})`
3. 看到 `[tool_result]` 內容
4. `[cost ≈ $X.XXXXX]` 成本估算

### 整合驗證

無前置 phase。手動驗證跑通即可。

## 8. 常見踩雷

### 踩雷 1:OpenAI Responses API ≠ chat.completions

別把 chat completions 教學 copy 到 Responses API。**訊息格式不同**(Responses 是 input items,chat 是 messages array)。本 phase 用 Responses API。

### 踩雷 2:partial JSON 解析

兩家 streaming 都是 partial JSON 增量(`input_json_delta` / `function_call_arguments.delta`)。**只在 ToolUseStop 才 parse 完整**。中途 invalid 不要解。

### 踩雷 3:Anthropic system 不能放 messages

```python
# ❌ 錯
messages=[{"role": "system", "content": "..."}]

# ✅ 對
system="...",
messages=[{"role": "user", ...}]
```

translation 函式要過濾 role=system。

### 踩雷 4:OpenAI tool_result 用 `call_id` 不是 `id`

```python
# ❌ 錯
{"type": "function_call_output", "id": "..."}

# ✅ 對
{"type": "function_call_output", "call_id": "..."}
```

### 踩雷 5:Anthropic cache_control 4 個上限

Anthropic 限 4 個 cache breakpoint per request。Phase 4 標 cache 時要選最關鍵的 4 個。

### 踩雷 6:Pydantic v2 vs v1

`model_config` / `@field_validator` / 新 JSON Schema 生成方式。**確保 `pydantic>=2`**。

### 踩雷 7:asyncio vs anyio

兩家 SDK 用 asyncio,FastAPI 也是。Phase 0 用 asyncio 即可。**Phase 6+ 改 anyio**(更好的結構化並行)。

### 踩雷 8:streaming 中斷處理

```python
try:
    async for event in provider.stream(...):
        ...
except (asyncio.TimeoutError, anthropic.APIConnectionError, openai.APIConnectionError):
    # 處理中斷
    ...
```

### 踩雷 9:reasoning tokens 計費

OpenAI o-series / GPT-5 的 reasoning tokens **計入 output**:
```python
total_output = output_tokens + reasoning_tokens
```

Anthropic extended thinking 也類似(都計 output)。

### 踩雷 10:Provider swap test 真的要跑兩家

不要只測 Anthropic 然後假設 OpenAI 也能跑。`test_swap_provider.py` 必須**實際呼叫兩家 API**(可用 mock + recorded VCR 跑 CI)。

## 9. 參考資料

### 直接呼的 API 文件

- **Anthropic**:[Messages API](https://docs.anthropic.com/en/api/messages) / [Streaming](https://docs.anthropic.com/en/api/messages-streaming) / [Prompt caching](https://docs.anthropic.com/en/docs/build-with-claude/prompt-caching)
- **OpenAI**:[Responses API](https://platform.openai.com/docs/api-reference/responses) / [Streaming events](https://developers.openai.com/api/reference/resources/responses/streaming-events) / [Function calling](https://platform.openai.com/docs/guides/function-calling) / [Reasoning](https://developers.openai.com/api/docs/guides/reasoning)

### Python clients(只當 HTTP wrapper)

- [anthropic-sdk-python](https://github.com/anthropics/anthropic-sdk-python)
- [openai-python](https://github.com/openai/openai-python)

### docs/01-11

- [docs/02 §10-12](../02-agent-loop.md) — Tool 抽象細節
- [docs/11 §0](../11-tools-catalog.md) — 工具的本質(function call,不是 SDK)

### TS 源檔

- `src/Tool.ts` — Tool interface 完整版
- `src/tools/FileReadTool/FileReadTool.ts` — 完整版 FileReadTool
- `src/services/api/claude.ts` — Anthropic 端點細節

### 外部資源

- [Pydantic v2 docs](https://docs.pydantic.dev/latest/)
- [PEP 544 — Protocols](https://peps.python.org/pep-0544/)
- [anyio docs](https://anyio.readthedocs.io/)

## 10. 完成檢查表

- [ ] `pyproject.toml` mypy strict + ruff 設好
- [ ] `Tool` Protocol + `FileReadTool` 滿足
- [ ] `AgentContext` dataclass(取代全域)
- [ ] `LLMProvider` Protocol + capability flags
- [ ] `AnthropicProvider` 直接呼 `messages.stream`,events 翻譯
- [ ] `OpenAIProvider` 直接呼 `responses.create`,events 翻譯
- [ ] Translation 雙向測過(訊息 / 工具 / 圖片)
- [ ] `test_swap_provider.py` 同 prompt 換 provider 跑通
- [ ] `--provider anthropic` 與 `--provider openai` 兩種 demo 都跑通
- [ ] coverage > 60%
- [ ] 寫 Phase 0 心得

## 11. 對 Phase 1-15 的影響

完成後,**Phase 1-15 全程程式碼不該見 anthropic / openai 字眼**,只見 LLMProvider 與 NormalizedEvent:

| Phase | 怎麼用 LLMProvider |
|---|---|
| 1 query_loop | `async for event in provider.stream(...)` 處理 NormalizedEvent |
| 3 sideQuery | 也走 `provider.stream()`(用較小 model 如 Haiku / gpt-5-mini) |
| 4 system prompt | `if provider.capabilities.prompt_caching: 用 cache_breakpoints` |
| 6 SyntheticOutputTool | `if provider.capabilities.structured_output: 用 response_format;else 用假工具` |
| 9 cost tracker | 直接 `provider.estimate_cost(...)` |
| 10 fallback model | 切 provider 或切 model 都行 |
| 12 forked_agent | cache 共享僅 Anthropic 享優勢,但 OpenAI 仍能 fork |
| 15 multi-agent | coordinator 與 worker 可用不同 provider(進階情境) |

完成後進入 [Phase 1:Agent Loop 核心](./01-agent-loop.md)。

"""Test fixtures shared by all packages that depend on orion-sdk。

使用方式(在 tests/conftest.py 加一行):

    pytest_plugins = ["orion_sdk._testing"]

之後 fixture(`isolate_sessions_dir` autouse、`tmp_ctx`、`sample_text_file`、
`mock_provider`)即可直接在 test 內以參數注入。

放在 orion_sdk 套件內(而非 tests/ 內),才能跨 package 透過 import 拉進來
(類似 sqlalchemy.testing / numpy.testing 的慣例)。Production runtime 不會
import 此模組,但會跟著 wheel ship — 屬內部 helpers,雙底線開頭表 private。
"""

from __future__ import annotations

from collections.abc import AsyncIterator
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import pytest
from dotenv import load_dotenv

from orion_model.events import (
    MessageStartEvent,
    MessageStopEvent,
    NormalizedEvent,
    NormalizedUsage,
    TextDeltaEvent,
    ToolUseStartEvent,
    ToolUseStopEvent,
)
from orion_model.provider import ProviderCapabilities
from orion_model.tool_def import ToolDefinition
from orion_model.types import NormalizedMessage

from orion_sdk.core.state import AgentContext

# integration tests 才能讀到 API keys
load_dotenv()


@pytest.fixture(autouse=True)
def isolate_sessions_dir(
    tmp_path_factory: pytest.TempPathFactory, monkeypatch: pytest.MonkeyPatch
) -> Path:
    """所有測試強制把 ORION_SESSIONS_DIR 指向 tmp,避免污染 ~/.orion/。"""
    sessions_dir = tmp_path_factory.mktemp("orion-sessions")
    monkeypatch.setenv("ORION_SESSIONS_DIR", str(sessions_dir))
    return sessions_dir


@pytest.fixture
def tmp_ctx(tmp_path: Path) -> AgentContext:
    """乾淨的 AgentContext,cwd 設為 tmp_path,適合工具測試。"""
    return AgentContext(cwd=tmp_path)


@pytest.fixture
def sample_text_file(tmp_path: Path) -> Path:
    """暫存目錄下建一個 5 行小檔。"""
    p = tmp_path / "sample.txt"
    p.write_text("alpha\nbeta\ngamma\ndelta\nepsilon\n", encoding="utf-8")
    return p


# ─── MockProvider for query_loop tests ──────────────────────────────────────


@dataclass
class MockTurn:
    """單 turn 模型回應的 script。"""

    text: str = ""
    tool_uses: list[tuple[str, str, dict[str, Any]]] = field(default_factory=list)
    """每筆 (tool_use_id, tool_name, input_dict)。"""


@dataclass
class MockProvider:
    """假 LLMProvider,逐輪 yield 預先 scripted 的 events。

    用法:
        provider = MockProvider(turns=[
            MockTurn(text="reading...", tool_uses=[("t1", "Read", {"path": "/etc/hosts"})]),
            MockTurn(text="done"),
        ])
    """

    name: str = "mock"
    model: str = "mock-1"
    capabilities: ProviderCapabilities = field(
        default_factory=lambda: ProviderCapabilities(
            prompt_caching=False,
            auto_caching=False,
            parallel_tool_calls=True,
            native_mcp=False,
            structured_output=False,
            reasoning_blocks=False,
            max_context_tokens=200_000,
        )
    )
    turns: list[MockTurn] = field(default_factory=list)
    _turn_index: int = 0
    captured_calls: list[dict[str, Any]] = field(default_factory=list)

    async def stream(
        self,
        *,
        system: str | list[str],
        messages: list[NormalizedMessage],
        tools: list[ToolDefinition] | None = None,
        max_tokens: int = 4096,
        temperature: float | None = None,
        cache_breakpoints: list[int] | None = None,
        reasoning_effort: Any = None,
    ) -> AsyncIterator[NormalizedEvent]:
        self.captured_calls.append({
            "system": system,
            "messages": list(messages),
            "tools": tools,
            "max_tokens": max_tokens,
        })

        if self._turn_index >= len(self.turns):
            yield MessageStopEvent(
                stop_reason="end_turn",
                usage=NormalizedUsage(input_tokens=0, output_tokens=0),
            )
            return

        turn = self.turns[self._turn_index]
        self._turn_index += 1

        yield MessageStartEvent(message_id=f"msg_{self._turn_index}", model=self.model)

        if turn.text:
            yield TextDeltaEvent(text=turn.text)

        for idx, (tu_id, tu_name, tu_input) in enumerate(turn.tool_uses):
            yield ToolUseStartEvent(
                block_index=idx + 1, tool_use_id=tu_id, tool_name=tu_name
            )
            yield ToolUseStopEvent(
                block_index=idx + 1,
                tool_use_id=tu_id,
                tool_name=tu_name,
                full_input=tu_input,
            )

        stop_reason = "tool_use" if turn.tool_uses else "end_turn"
        yield MessageStopEvent(
            stop_reason=stop_reason,
            usage=NormalizedUsage(input_tokens=10, output_tokens=20),
        )

    def estimate_cost(
        self,
        *,
        input_tokens: int,
        output_tokens: int,
        cache_read_tokens: int = 0,
        cache_creation_tokens: int = 0,
        reasoning_tokens: int = 0,
    ) -> float:
        return 0.0


@pytest.fixture
def mock_provider() -> MockProvider:
    """空 MockProvider,test 自己塞 turns。"""
    return MockProvider()

"""memory/relevance.py — heuristic + LLM modes。"""

from __future__ import annotations

from pathlib import Path

import pytest

from orion_model.types import NormalizedMessage
from orion_sdk.memory import relevance
from orion_sdk.memory.relevance import rank_memories
from orion_sdk.memory.types import Memory, MemoryFrontmatter, MemoryType
from orion_sdk._testing import MockProvider, MockTurn


def _mk(name: str, desc: str, body: str = "", t: MemoryType | None = MemoryType.USER) -> Memory:
    return Memory(
        frontmatter=MemoryFrontmatter(name=name, description=desc, type=t),
        body=body,
        file_path=Path(f"/tmp/{name}.md"),
    )


@pytest.mark.asyncio
async def test_empty_memories_returns_empty() -> None:
    msgs = [NormalizedMessage(role="user", content="hi")]
    out = await rank_memories([], msgs)
    assert out == []


@pytest.mark.asyncio
async def test_heuristic_keyword_match() -> None:
    """Default heuristic 模式:keyword 重疊高的優先。"""
    memories = [
        _mk("Python tips", "tricks for python development", "uses asyncio"),
        _mk("Lunch preference", "user likes ramen", "ramen"),
        _mk("Project deadline", "ship Q3", "deadline"),
    ]
    msgs = [NormalizedMessage(role="user", content="help me with python asyncio")]
    out = await rank_memories(memories, msgs, max_results=2)
    assert len(out) >= 1
    # Python 相關 memory 應在最前
    assert out[0].name == "Python tips"


@pytest.mark.asyncio
async def test_heuristic_no_match_falls_back_to_user_priority() -> None:
    """無 keyword 命中時回 user/feedback 類優先。"""
    memories = [
        _mk("Reference doc", "Linear URL", t=MemoryType.REFERENCE),
        _mk("Project info", "deadline X", t=MemoryType.PROJECT),
        _mk("User profile", "name is alice", t=MemoryType.USER),
        _mk("Feedback rule", "always test", t=MemoryType.FEEDBACK),
    ]
    msgs = [NormalizedMessage(role="user", content="completely_unrelated_query_xyz")]
    out = await rank_memories(memories, msgs, max_results=4)
    # user 應在 feedback 前
    types = [m.type for m in out]
    assert types[0] == MemoryType.USER
    assert types[1] == MemoryType.FEEDBACK


@pytest.mark.asyncio
async def test_max_results_limits_output() -> None:
    memories = [_mk(f"m{i}", "general") for i in range(20)]
    msgs = [NormalizedMessage(role="user", content="test")]
    out = await rank_memories(memories, msgs, max_results=3)
    assert len(out) == 3


@pytest.mark.asyncio
async def test_no_user_query_returns_priority_default() -> None:
    """No user message → return type-priority sorted memories。"""
    memories = [
        _mk("a", "x", t=MemoryType.PROJECT),
        _mk("b", "y", t=MemoryType.USER),
    ]
    msgs: list[NormalizedMessage] = []
    out = await rank_memories(memories, msgs, max_results=2)
    # USER 優先(priority=0 < project=2)
    assert out[0].type == MemoryType.USER


@pytest.mark.asyncio
async def test_stop_words_dont_match() -> None:
    """`in` / `am` / `the` 等 stop word 不該成為 relevance 訊號。

    複現實際使用場景:query 含 stop word `in`,memory body 也含 `in`,但 user 真正
    要找的是另一條 memory 命中其他 keyword。
    """
    memories = [
        _mk(
            "Linear bugs",
            "track bugs in Linear ORION-BUGS project",
            "all bug reporting goes to Linear",
        ),
        _mk(
            "Python expertise",
            "user is fluent in Python async patterns",
            "uses asyncio anyio",
        ),
    ]
    msgs = [NormalizedMessage(role="user", content="What languages am I fluent in?")]
    out = await rank_memories(memories, msgs, max_results=2)
    # Python memory 應排第一(命中「fluent」)而非 Linear(原 "in" 假命中)
    assert out[0].name == "Python expertise"


@pytest.mark.asyncio
async def test_stop_words_no_false_match_when_only_stop_overlap() -> None:
    """純 stop word 重疊 → 視同零命中,fallback 到 type priority。"""
    memories = [
        _mk("Project info", "deadline X", t=MemoryType.PROJECT),
        _mk("User profile", "name alice", t=MemoryType.USER),
    ]
    msgs = [NormalizedMessage(role="user", content="what is the answer")]
    out = await rank_memories(memories, msgs, max_results=2)
    # 應 fallback type priority(USER 優先)
    assert out[0].type == MemoryType.USER


# ─── LLM ranker 強制走 Haiku ────────────────────────────────────────────────


@pytest.fixture
def _reset_ranker_cache() -> None:
    relevance._reset_ranker_provider_cache_for_tests()
    yield
    relevance._reset_ranker_provider_cache_for_tests()


@pytest.mark.asyncio
async def test_llm_rank_uses_ranker_provider_not_caller_provider(
    monkeypatch: pytest.MonkeyPatch, _reset_ranker_cache: None
) -> None:
    """LLM 模式啟用時,實際呼叫應走 internal ranker provider(Haiku),
    而非 caller 傳入的主對話 provider。
    """
    monkeypatch.setenv("ORION_MEMORY_RANKER", "llm")

    # 假 ranker provider:回合法 JSON {"indices": [1, 0]}
    ranker_mock = MockProvider(
        model="claude-haiku-4-5",
        turns=[
            MockTurn(
                text="",
                tool_uses=[("t1", "rank_memories", {"indices": [1, 0]})],
            )
        ],
    )
    monkeypatch.setattr(relevance, "_ranker_provider", lambda: ranker_mock)

    # caller 傳的 provider(模擬主對話用的 Opus / Sonnet)
    caller_provider = MockProvider(model="claude-opus-4-7")

    memories = [
        _mk("m0", "first", body="alpha"),
        _mk("m1", "second", body="beta"),
    ]
    msgs = [NormalizedMessage(role="user", content="please rank these")]

    out = await rank_memories(
        memories, msgs, provider=caller_provider, max_results=2
    )

    # ranker 收到請求,caller_provider 沒被碰
    assert len(ranker_mock.captured_calls) == 1
    assert caller_provider.captured_calls == []
    # 回的順序遵照 ranker 的 indices
    assert [m.name for m in out] == ["m1", "m0"]


@pytest.mark.asyncio
async def test_llm_rank_falls_back_to_heuristic_when_ranker_fails(
    monkeypatch: pytest.MonkeyPatch, _reset_ranker_cache: None
) -> None:
    """Ranker provider stream 中 raise → fallback heuristic,不爆 caller。"""
    monkeypatch.setenv("ORION_MEMORY_RANKER", "llm")

    class _BrokenProvider:
        name = "broken"
        model = "broken"
        capabilities = None

        async def stream(self, **_: object):  # type: ignore[no-untyped-def]
            raise RuntimeError("API key missing")
            yield  # 讓它成 async generator

        def estimate_cost(self, **_: object) -> float:  # type: ignore[no-untyped-def]
            return 0.0

    monkeypatch.setattr(relevance, "_ranker_provider", lambda: _BrokenProvider())

    memories = [
        _mk("python", "python tips", body="asyncio"),
        _mk("ramen", "lunch", body="food"),
    ]
    msgs = [NormalizedMessage(role="user", content="help me with python asyncio")]

    out = await rank_memories(memories, msgs, provider=MockProvider(), max_results=2)
    # heuristic 應命中 "python" memory
    assert out[0].name == "python"


def test_ranker_provider_uses_haiku_model_by_default(
    monkeypatch: pytest.MonkeyPatch, _reset_ranker_cache: None
) -> None:
    monkeypatch.delenv("ORION_MEMORY_RANKER_MODEL", raising=False)
    provider = relevance._ranker_provider()
    assert provider is not None
    assert provider.model == "claude-haiku-4-5"


def test_ranker_provider_env_override_model(
    monkeypatch: pytest.MonkeyPatch, _reset_ranker_cache: None
) -> None:
    monkeypatch.setenv("ORION_MEMORY_RANKER_MODEL", "claude-haiku-4-5")
    provider = relevance._ranker_provider()
    assert provider is not None
    assert provider.model == "claude-haiku-4-5"


def test_ranker_provider_auto_detects_openai_model(
    monkeypatch: pytest.MonkeyPatch, _reset_ranker_cache: None
) -> None:
    """設成 OpenAI catalog 內的 model → 自動建 OpenAIProvider。"""
    monkeypatch.setenv("ORION_MEMORY_RANKER_MODEL", "gpt-5-mini")
    # 避免 OpenAIProvider() 在沒 OPENAI_API_KEY 時 raise(構造本身應 OK,但保險)
    monkeypatch.setenv("OPENAI_API_KEY", "sk-test-dummy")
    provider = relevance._ranker_provider()
    assert provider is not None
    assert provider.name == "openai"
    assert provider.model == "gpt-5-mini"


def test_ranker_provider_unknown_model_falls_back_to_haiku(
    monkeypatch: pytest.MonkeyPatch,
    _reset_ranker_cache: None,
    caplog: pytest.LogCaptureFixture,
) -> None:
    """Catalog 找不到的 model id → log warning + 退回 Haiku 預設。"""
    monkeypatch.setenv("ORION_MEMORY_RANKER_MODEL", "fictional-model-xyz")
    with caplog.at_level("WARNING", logger="orion_sdk.memory.relevance"):
        provider = relevance._ranker_provider()
    assert provider is not None
    assert provider.name == "anthropic"
    assert provider.model == "claude-haiku-4-5"
    assert any("fictional-model-xyz" in r.message for r in caplog.records)

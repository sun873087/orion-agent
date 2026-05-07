"""Relevance ranker — 從全 memory 集合挑跟當前 conversation 最相關的 N 個。

對應 spec § 5 relevance.py。

兩種模式:
- **heuristic**(預設):純關鍵字 bag-of-words overlap,快、零 LLM cost
- **llm**(env `ORION_MEMORY_RANKER=llm` 啟用):送 memory descriptions + 最近 user
  訊息給 LLM 評分,挑 top N。較貴但更準

LLM 模式失敗(parse error / API down)→ 自動 fallback heuristic。
"""

from __future__ import annotations

import os
import re

from orion_agent.llm.provider import LLMProvider
from orion_agent.llm.types import NormalizedMessage, TextBlock, ToolUseBlock
from orion_agent.memory.types import Memory, MemoryType

_DEFAULT_MAX_RESULTS = 10


def _extract_recent_user_query(messages: list[NormalizedMessage]) -> str:
    """抓最近的 user role 訊息文字內容(供 ranking 比對)。"""
    for m in reversed(messages):
        if m.role != "user":
            continue
        if isinstance(m.content, str):
            return m.content
        # list of blocks → 串 TextBlock
        if isinstance(m.content, list):
            parts: list[str] = []
            for b in m.content:
                if isinstance(b, TextBlock):
                    parts.append(b.text)
            if parts:
                return " ".join(parts)
    return ""


def _tokenize(text: str) -> set[str]:
    return {w for w in re.findall(r"\w+", text.lower()) if len(w) > 1}


def _heuristic_score(memory: Memory, query_words: set[str]) -> int:
    text = f"{memory.name} {memory.description} {memory.body}".lower()
    memory_words = _tokenize(text)
    return len(query_words & memory_words)


def _heuristic_rank(
    memories: list[Memory],
    query: str,
    max_results: int,
) -> list[Memory]:
    """Bag-of-words overlap。"""
    query_words = _tokenize(query)
    if not query_words:
        # 沒 query word — 優先回 user / feedback 類(general 偏好,最常需要)
        return _by_type_priority(memories)[:max_results]

    scored = [(_heuristic_score(m, query_words), m) for m in memories]
    scored.sort(key=lambda x: x[0], reverse=True)

    relevant = [m for s, m in scored if s > 0][:max_results]
    if relevant:
        return relevant
    # 全 0 分 → fallback 到 type priority
    return _by_type_priority(memories)[:max_results]


def _by_type_priority(memories: list[Memory]) -> list[Memory]:
    """user > feedback > project > reference > 無 type 順序。"""
    priority = {
        MemoryType.USER: 0,
        MemoryType.FEEDBACK: 1,
        MemoryType.PROJECT: 2,
        MemoryType.REFERENCE: 3,
    }
    return sorted(
        memories,
        key=lambda m: (priority.get(m.type, 99), m.filename) if m.type else (99, m.filename),
    )


async def _llm_rank(
    memories: list[Memory],
    query: str,
    provider: LLMProvider,
    max_results: int,
) -> list[Memory] | None:
    """讓 provider 看 memory descriptions + query,回 top N indices。

    失敗(parse error / API error)→ 回 None,caller 改 fallback heuristic。
    """
    listings = []
    for i, m in enumerate(memories):
        type_str = m.type.value if m.type else "?"
        listings.append(f"[{i}] ({type_str}) {m.name}: {m.description}")

    system_prompt = (
        "You score memory relevance to the user's current query. "
        "Output is parsed mechanically — emit only integers, one per line."
    )
    user_text = (
        f"User query:\n{query}\n\n"
        f"Available memories:\n" + "\n".join(listings) + "\n\n"
        f"Return up to {max_results} most relevant memory indices, "
        "one per line as just the integer (no brackets, no explanation, "
        "most relevant first). If none are relevant, return nothing."
    )

    try:
        text = await _provider_complete(provider, system_prompt, user_text)
    except Exception:  # noqa: BLE001
        return None

    indices: list[int] = []
    for line in text.splitlines():
        line = line.strip()
        if not line:
            continue
        # 支援 "[2]" 或 "2" 或 "2." 格式
        cleaned = re.sub(r"[^\d]", "", line)
        if cleaned.isdigit():
            idx = int(cleaned)
            if 0 <= idx < len(memories) and idx not in indices:
                indices.append(idx)

    if not indices:
        return None
    return [memories[i] for i in indices[:max_results]]


async def _provider_complete(
    provider: LLMProvider, system: str, user_text: str
) -> str:
    """簡單包 provider.stream → 累積 text 回單一 string。"""
    from orion_agent.llm.events import (
        MessageStopEvent,
        TextDeltaEvent,
        ToolUseStopEvent,
    )

    chunks: list[str] = []
    messages = [NormalizedMessage(role="user", content=user_text)]
    async for ev in provider.stream(
        system=system,
        messages=messages,
        tools=[],
        max_tokens=512,
    ):
        if isinstance(ev, TextDeltaEvent):
            chunks.append(ev.text)
        elif isinstance(ev, ToolUseStopEvent):
            pass  # ranker 不該 emit tool_use,忽略
        elif isinstance(ev, MessageStopEvent):
            break
    return "".join(chunks)


async def rank_memories(
    memories: list[Memory],
    conversation_messages: list[NormalizedMessage],
    *,
    provider: LLMProvider | None = None,
    max_results: int = _DEFAULT_MAX_RESULTS,
) -> list[Memory]:
    """挑 top N relevant memories。

    Args:
        memories: 全部可用 memory(從 scan_memory_dir 取得)
        conversation_messages: 當前對話歷史 — 用最近 user 訊息做 query
        provider: 若有且 ORION_MEMORY_RANKER=llm,用 LLM 排;否則 heuristic
        max_results: 上限,預設 10
    """
    if not memories:
        return []

    query = _extract_recent_user_query(conversation_messages)

    use_llm = (
        provider is not None
        and os.environ.get("ORION_MEMORY_RANKER", "heuristic").lower() == "llm"
    )

    if use_llm and provider is not None and query:
        result = await _llm_rank(memories, query, provider, max_results)
        if result is not None:
            return result
        # LLM 失敗 → fallback

    # _:silently 忽略無關引數,維持 type completeness
    _ = ToolUseBlock  # keep import alive
    return _heuristic_rank(memories, query, max_results)

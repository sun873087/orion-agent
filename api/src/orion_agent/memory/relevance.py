"""Relevance ranker — 從全 memory 集合挑跟當前 conversation 最相關的 N 個。

對應 spec § 5 relevance.py。

兩種模式:
- **heuristic**(預設):純關鍵字 bag-of-words overlap,快、零 LLM cost
- **llm**(env `ORION_MEMORY_RANKER=llm` 啟用):送 memory descriptions + 最近 user
  訊息給 LLM 評分,挑 top N。較貴但更準

LLM 模式**永遠用 Anthropic Haiku 4.5**(跟主對話 model 解耦)— ranking 是輕任務,
用 Haiku 跟 Sonnet/Opus 比可降一個量級的成本。可用 `ORION_MEMORY_RANKER_MODEL` 覆寫
model id。Haiku provider 建構或呼叫失敗 → 自動 fallback heuristic。
"""

from __future__ import annotations

import logging
import os
import re

from orion_model.provider import LLMProvider
from orion_model.types import NormalizedMessage, TextBlock
from orion_agent.memory.types import Memory, MemoryType

_log = logging.getLogger(__name__)

_DEFAULT_MAX_RESULTS = 10
_DEFAULT_RANKER_MODEL = "claude-haiku-4-5"

_ranker_provider_cache: LLMProvider | None = None


def _ranker_provider() -> LLMProvider | None:
    """Lazy 取或建構 ranker 專用 provider(module 層 cache,只建一次)。

    成本考量:ranker 只需要選 indices,Haiku 4.5 ($1/$5 per 1M) 比 Sonnet 便宜 3×、
    比 Opus 便宜 15×。把它跟主對話 provider 解耦,避免高階 model 被拉去做 ranking。

    Provider 從 catalog 自動偵測(`find_provider_by_model`):
      - `ORION_MEMORY_RANKER_MODEL=claude-haiku-4-5` → AnthropicProvider(預設)
      - `ORION_MEMORY_RANKER_MODEL=gpt-5.5-pro`      → OpenAIProvider
      - 未知 model id → log warning + fallback 回 Haiku 4.5

    Provider 永遠從 model 反查 — 沒獨立的「ranker provider」env,避免 model 與
    provider 不一致的矛盾組合。

    建構失敗 → 回 None,caller fallback heuristic。實際 API key 缺失要到 side_query
    階段才 raise,由既有 try/except 處理。
    """
    global _ranker_provider_cache
    if _ranker_provider_cache is not None:
        return _ranker_provider_cache

    from orion_model.catalog import find_provider_by_model
    from orion_model.provider import get_provider

    model = os.environ.get("ORION_MEMORY_RANKER_MODEL", _DEFAULT_RANKER_MODEL)
    provider_id = find_provider_by_model(model)

    if provider_id is None:
        default_provider = find_provider_by_model(_DEFAULT_RANKER_MODEL)
        if default_provider is None:
            # packaged catalog 一定含預設 Haiku — 走到這裡代表 catalog 壞了
            _log.error(
                "default ranker model %r missing from catalog; ranker disabled",
                _DEFAULT_RANKER_MODEL,
            )
            return None
        _log.warning(
            "ORION_MEMORY_RANKER_MODEL=%r not found in catalog; "
            "falling back to %s (%s).",
            model, _DEFAULT_RANKER_MODEL, default_provider,
        )
        model = _DEFAULT_RANKER_MODEL
        provider_id = default_provider

    try:
        _ranker_provider_cache = get_provider(provider_id, model)
    except Exception:  # noqa: BLE001
        return None
    return _ranker_provider_cache


def _reset_ranker_provider_cache_for_tests() -> None:
    """測試用:清掉 cached provider,讓 monkeypatched env 生效。"""
    global _ranker_provider_cache
    _ranker_provider_cache = None


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


_STOP_WORDS = frozenset({
    # Articles
    "a", "an", "the",
    # Pronouns
    "i", "you", "he", "she", "it", "we", "they",
    "me", "my", "your", "his", "her", "our", "their", "its",
    "us", "him", "them", "myself", "yourself", "ourselves",
    # Aux / be / do / have
    "am", "is", "are", "was", "were", "be", "been", "being",
    "do", "does", "did", "doing", "done",
    "have", "has", "had", "having",
    # Modals
    "will", "would", "could", "should", "shall",
    "can", "may", "might", "must",
    # Prepositions
    "in", "on", "at", "to", "for", "of", "with", "by", "from",
    "into", "onto", "out", "off", "up", "down",
    "about", "over", "under", "between", "through", "across",
    # Conjunctions
    "and", "or", "but", "not", "so", "if", "then", "as", "than",
    "because", "since", "while", "though", "although",
    # Demonstratives
    "this", "that", "these", "those",
    # Wh-words(meta — 通常不帶 topic 訊號)
    "what", "where", "when", "how", "why", "who", "which",
    "whom", "whose",
    # 常見 qualifier / quantifier
    "just", "only", "too", "very", "more", "most", "less", "least",
    "some", "any", "all", "both", "each", "every", "no", "none",
    "many", "much", "few",
    # 其他高頻無內容詞
    "yes", "ok", "okay", "please", "thanks", "thank",
    "now", "later", "today", "really",
})
"""停用字 — heuristic ranker 不該因這些詞撞 match。"""


def _tokenize(text: str) -> set[str]:
    return {
        w
        for w in re.findall(r"\w+", text.lower())
        if len(w) > 1 and w not in _STOP_WORDS
    }


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

    Phase 12:改走 side_query — 不汙染主 transcript、可選 JSON Schema 強制輸出。
    Ranker 永遠用 Haiku 4.5(見 `_ranker_provider`),caller 傳入的 `provider` 只作為
    Haiku 建構失敗時的 fallback。失敗(parse error / API error)→ 回 None,caller 改
    fallback heuristic。
    """
    from orion_agent.services.side_query import (
        SideQueryParams,
        side_query,
    )

    ranker = _ranker_provider() or provider

    listings = []
    for i, m in enumerate(memories):
        type_str = m.type.value if m.type else "?"
        listings.append(f"[{i}] ({type_str}) {m.name}: {m.description}")

    system_prompt = (
        "You score memory relevance to the user's current query. "
        "Return JSON with an `indices` array of memory indices, "
        "most relevant first, max length capped by the user instruction."
    )
    user_text = (
        f"User query:\n{query}\n\n"
        f"Available memories:\n" + "\n".join(listings) + "\n\n"
        f"Return up to {max_results} most relevant memory indices."
    )

    schema = {
        "name": "rank_memories",
        "schema": {
            "type": "object",
            "properties": {
                "indices": {
                    "type": "array",
                    "items": {"type": "integer"},
                    "description": "Memory indices, most relevant first.",
                },
            },
            "required": ["indices"],
        },
    }

    try:
        result = await side_query(
            SideQueryParams(
                system=system_prompt,
                user_text=user_text,
                max_tokens=512,
                json_schema=schema,
                query_source="memdir_relevance",
            ),
            provider=ranker,
        )
    except Exception:  # noqa: BLE001
        return None

    indices: list[int] = []
    if isinstance(result.structured, dict):
        raw = result.structured.get("indices")
        if isinstance(raw, list):
            for v in raw:
                if isinstance(v, int) and 0 <= v < len(memories) and v not in indices:
                    indices.append(v)

    # 沒走 schema 路徑(provider 不支援) → 回退舊式 line-by-line 解析
    if not indices and result.text.strip():
        for line in result.text.splitlines():
            line = line.strip()
            if not line:
                continue
            cleaned = re.sub(r"[^\d]", "", line)
            if cleaned.isdigit():
                idx = int(cleaned)
                if 0 <= idx < len(memories) and idx not in indices:
                    indices.append(idx)

    if not indices:
        return None
    return [memories[i] for i in indices[:max_results]]


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

    return _heuristic_rank(memories, query, max_results)

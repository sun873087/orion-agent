"""Memory Layer 4 — merge suggest job。

對 over-quota 的 type 跑:
  1. 用 OpenAI text-embedding-3-small 取每 memory 的 embedding
  2. cluster 相似 ≥ threshold 的 memory(預設 0.85 cosine similarity)
  3. 對每個 ≥2 個 memory 的 cluster 跑 LLM:「合併 or 不合併?」
  4. 寫建議到 `<memory_dir>/_suggestions.jsonl`
     每行一個建議(unique id),user accept / reject 流程由上層 API 接

設計取捨:
- **不自動合併** — 永遠是 suggest,user 必須明確 accept
- **每 user 每天最多跑一次**(由 caller 控制 — apscheduler / cron),
  避免 embedding API 重複燒錢
- 大量 memory(>100)時 batch embedding call(OpenAI API 一次最多 2048 inputs)
- LLM merge call 用 Anthropic Haiku 4.5(快 + 便宜),caller 可換 provider
"""

from __future__ import annotations

import asyncio
import json
import math
import os
import uuid
from collections.abc import Sequence
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import structlog

from orion_model.provider import LLMProvider
from orion_model.types import NormalizedMessage
from orion_sdk.memory.types import Memory, MemoryType

log = structlog.get_logger(__name__)

_SUGGESTIONS_FILE = "_suggestions.jsonl"
_EMBED_MODEL = "text-embedding-3-small"
_DEFAULT_SIMILARITY_THRESHOLD = 0.85
_EMBED_BATCH_SIZE = 100


def suggestions_path(memory_dir: Path) -> Path:
    return memory_dir / _SUGGESTIONS_FILE


@dataclass
class MergeSuggestion:
    """A "consider merging these into one" suggestion。"""

    id: str
    type: MemoryType | None
    member_filenames: list[str]
    """要被合併的 memory 檔名(≥2)。"""
    merged_name: str
    """LLM 提出的新 memory name。"""
    merged_description: str
    merged_body: str
    """LLM 提出的合併後 body。"""
    rationale: str
    """LLM 為何認為這些該合併(<= 2 句)。"""
    created_at: str = field(default_factory=lambda: datetime.now(timezone.utc).isoformat())

    def to_dict(self) -> dict[str, Any]:
        return {
            "id": self.id,
            "type": self.type.value if self.type else None,
            "member_filenames": list(self.member_filenames),
            "merged_name": self.merged_name,
            "merged_description": self.merged_description,
            "merged_body": self.merged_body,
            "rationale": self.rationale,
            "created_at": self.created_at,
        }


# ─── Embedding ───────────────────────────────────────────────────────


def _memory_text(m: Memory) -> str:
    """concat name + description + body for embedding(typically <= 500 token)。"""
    return f"{m.name}\n{m.description}\n{m.body}".strip()


async def _embed_texts(texts: list[str]) -> list[list[float]]:
    """Batch embedding via OpenAI text-embedding-3-small。

    Returns [[float]] 對應 texts 順序。失敗 raise(讓 caller decide)。
    """
    from openai import AsyncOpenAI

    api_key = os.environ.get("OPENAI_API_KEY")
    if not api_key:
        raise RuntimeError("OPENAI_API_KEY required for memory merge suggest")
    client = AsyncOpenAI(api_key=api_key)

    vectors: list[list[float]] = []
    for i in range(0, len(texts), _EMBED_BATCH_SIZE):
        batch = texts[i:i + _EMBED_BATCH_SIZE]
        resp = await client.embeddings.create(model=_EMBED_MODEL, input=batch)
        for data in resp.data:
            vectors.append(list(data.embedding))
    return vectors


def _cosine(a: list[float], b: list[float]) -> float:
    if not a or not b or len(a) != len(b):
        return 0.0
    dot = sum(x * y for x, y in zip(a, b, strict=False))
    na = math.sqrt(sum(x * x for x in a))
    nb = math.sqrt(sum(y * y for y in b))
    if na == 0 or nb == 0:
        return 0.0
    return dot / (na * nb)


def _cluster(
    memories: list[Memory],
    embeddings: list[list[float]],
    *,
    threshold: float,
) -> list[list[int]]:
    """簡單 single-link clustering by cosine threshold。

    Return list of clusters,each cluster = list of indices into memories。
    單獨成 cluster(沒鄰居)的 memory 不會被回傳(只回 ≥2 的 group)。
    """
    n = len(memories)
    parent = list(range(n))

    def find(x: int) -> int:
        while parent[x] != x:
            parent[x] = parent[parent[x]]
            x = parent[x]
        return x

    def union(a: int, b: int) -> None:
        ra, rb = find(a), find(b)
        if ra != rb:
            parent[ra] = rb

    for i in range(n):
        for j in range(i + 1, n):
            if _cosine(embeddings[i], embeddings[j]) >= threshold:
                union(i, j)

    groups: dict[int, list[int]] = {}
    for i in range(n):
        groups.setdefault(find(i), []).append(i)
    return [g for g in groups.values() if len(g) >= 2]


# ─── LLM merge call ──────────────────────────────────────────────────


_MERGE_SYSTEM = (
    "你是 memory 管理助手。看一組 N 筆 memory(可能語意重疊),判斷是否該合併成一篇,"
    "若要合併,寫出合併後的 name / description / body / rationale。\n\n"
    "輸出 JSON,**只**這個格式:\n"
    "{\n"
    ' "merge": true,\n'
    ' "name": "合併後 name",\n'
    ' "description": "一句話 description",\n'
    ' "body": "合併後完整 markdown body",\n'
    ' "rationale": "為何該合併(2 句內)"\n'
    "}\n\n"
    "若不該合併(內容只是表面相關,實際各自獨立):\n"
    "{\n"
    ' "merge": false,\n'
    ' "rationale": "為何不該合併"\n'
    "}\n\n"
    "重要:輸出純 JSON,不要 markdown code fence 不要前言。"
)


def _build_merge_user_prompt(memories: list[Memory]) -> str:
    lines = ["以下 {} 筆 memory:".format(len(memories)), ""]
    for i, m in enumerate(memories, 1):
        lines.append(f"--- memory {i}:{m.filename} ---")
        lines.append(f"name: {m.name}")
        lines.append(f"description: {m.description}")
        lines.append(f"body:\n{m.body}")
        lines.append("")
    return "\n".join(lines)


async def _ask_llm_merge(
    cluster_members: list[Memory], provider: LLMProvider
) -> dict[str, Any] | None:
    """Ask LLM 是否該合併。回 parsed dict 或 None(LLM 失敗 / bad JSON)。"""
    user_text = _build_merge_user_prompt(cluster_members)
    messages = [NormalizedMessage(role="user", content=user_text)]

    chunks: list[str] = []
    try:
        async for ev in provider.stream(
            system=_MERGE_SYSTEM,
            messages=messages,
            tools=[],
            max_tokens=2000,
        ):
            from orion_model.events import TextDeltaEvent
            if isinstance(ev, TextDeltaEvent):
                chunks.append(ev.text)
    except Exception as e: # noqa: BLE001
        log.warning("merge_suggester.llm_error", error=str(e))
        return None

    raw = "".join(chunks).strip()
    # 偶爾 LLM 還是用 ```json 包,試著剝
    if raw.startswith("```"):
        raw = raw.strip("`")
        if raw.startswith("json"):
            raw = raw[4:]
        raw = raw.strip()
    try:
        return json.loads(raw)
    except json.JSONDecodeError:
        log.warning("merge_suggester.bad_json", raw=raw[:200])
        return None


# ─── Public job entry ────────────────────────────────────────────────


async def run_merge_suggest_job(
    memories: list[Memory],
    memory_dir: Path,
    *,
    provider: LLMProvider,
    mtype: MemoryType | None = None,
    similarity_threshold: float = _DEFAULT_SIMILARITY_THRESHOLD,
) -> list[MergeSuggestion]:
    """跑一次 merge-suggest。

    Args:
        memories: 候選 memory 池(通常已 filter 到 quota 超量的 type)
        memory_dir: 寫 `_suggestions.jsonl` 的目錄
        provider: LLM provider 用 to ask "is this mergeable"
        mtype: 該 cluster 屬於的 type(寫進 suggestion record)
        similarity_threshold: cosine ≥ 此值就視為同 cluster 候選

    Returns:
        產生的 MergeSuggestion list(已寫入 disk)。空 list = 沒可合併的 group。

    Behaviour:
        - 少於 2 筆 memory → 跳過(無 cluster 可生)
        - embedding API 失敗 → 整個 job 中止,raise
        - LLM 回 `merge: false` → 該 cluster 跳過,不寫 suggestion
        - LLM 失敗 / bad JSON → 該 cluster 跳過,log warn

    Idempotency:
        每次跑都 append 新 suggestion 進 jsonl,不去重(by design — caller 對既有
        suggestion 已決定,新一輪可能基於更新後 memory 集合給新建議)。
    """
    if len(memories) < 2:
        return []

    texts = [_memory_text(m) for m in memories]
    embeddings = await _embed_texts(texts)
    clusters = _cluster(memories, embeddings, threshold=similarity_threshold)

    out: list[MergeSuggestion] = []
    memory_dir.mkdir(parents=True, exist_ok=True)
    target = suggestions_path(memory_dir)

    for cluster in clusters:
        members = [memories[i] for i in cluster]
        verdict = await _ask_llm_merge(members, provider)
        if not verdict or not verdict.get("merge"):
            continue
        sug = MergeSuggestion(
            id=str(uuid.uuid4()),
            type=mtype,
            member_filenames=[m.filename for m in members],
            merged_name=str(verdict.get("name", "")),
            merged_description=str(verdict.get("description", "")),
            merged_body=str(verdict.get("body", "")),
            rationale=str(verdict.get("rationale", "")),
        )
        out.append(sug)
        with target.open("a", encoding="utf-8") as f:
            f.write(json.dumps(sug.to_dict(), ensure_ascii=False) + "\n")

    return out


def load_suggestions(memory_dir: Path) -> list[dict[str, Any]]:
    """讀出當前 pending suggestions(每行一個 dict)。"""
    path = suggestions_path(memory_dir)
    if not path.exists():
        return []
    out: list[dict[str, Any]] = []
    with path.open(encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            try:
                out.append(json.loads(line))
            except json.JSONDecodeError:
                continue
    return out


def remove_suggestion(memory_dir: Path, suggestion_id: str) -> bool:
    """從 _suggestions.jsonl 移除某 id(user accept / reject 後 cleanup)。

    Return True 若有刪到。Rewrite 整檔(JSONL 不支援 in-place delete)。
    """
    path = suggestions_path(memory_dir)
    if not path.exists():
        return False
    kept: list[str] = []
    removed = False
    with path.open(encoding="utf-8") as f:
        for line in f:
            line_stripped = line.strip()
            if not line_stripped:
                continue
            try:
                obj = json.loads(line_stripped)
                if obj.get("id") == suggestion_id:
                    removed = True
                    continue
            except json.JSONDecodeError:
                # 壞行也 keep 避免靜默丟資料
                pass
            kept.append(line if line.endswith("\n") else line + "\n")
    if removed:
        path.write_text("".join(kept), encoding="utf-8")
    return removed

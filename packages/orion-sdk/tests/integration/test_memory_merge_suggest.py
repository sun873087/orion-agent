"""Real-API integration:memory Layer 4 merge suggester。

灌 3 個語意極相似的 feedback memory + 1 個無關 memory,跑
run_merge_suggest_job,驗證:
- OpenAI embedding API 真實打通
- 相似的 3 個 cluster 在一起
- 不相關的 1 個被排除
- LLM 判定該合併 → 寫 suggestion 進 _suggestions.jsonl

成本估算:embedding ~$0.00005,LLM Haiku ~$0.001。
"""

from __future__ import annotations

import os
from pathlib import Path

import pytest

from orion_model.provider import get_provider
from orion_sdk.memory.merge_suggester import load_suggestions, run_merge_suggest_job
from orion_sdk.memory.types import Memory, MemoryFrontmatter, MemoryType

pytestmark = pytest.mark.skipif(
    not (os.environ.get("OPENAI_API_KEY") and os.environ.get("ANTHROPIC_API_KEY")),
    reason="needs both OPENAI_API_KEY (embeddings) and ANTHROPIC_API_KEY (merge LLM)",
)


def _make_memory(name: str, body: str, mtype: MemoryType = MemoryType.FEEDBACK) -> Memory:
    fm = MemoryFrontmatter(
        name=name,
        description=body[:80],
        type=mtype,
    )
    return Memory(frontmatter=fm, body=body, file_path=Path(f"{name}.md"))


@pytest.mark.asyncio
async def test_clusters_similar_feedback_and_writes_suggestion(tmp_path: Path) -> None:
    """三個極相似 + 一個無關,應產出 1 個 merge suggestion。"""
    memories = [
        _make_memory(
            "feedback_be_concise_1",
            "User prefers concise responses. Trim padding and pleasantries; "
            "get to the point quickly.",
        ),
        _make_memory(
            "feedback_brief_answers",
            "Be brief. User dislikes verbose explanations and prefers short, "
            "direct answers without filler.",
        ),
        _make_memory(
            "feedback_no_filler",
            "Skip filler phrases and unnecessary preamble. User wants concise "
            "responses without padding.",
        ),
        # 完全無關 — 不該進 cluster
        _make_memory(
            "feedback_use_tabs",
            "User prefers tabs over spaces for Python indentation in this project. "
            "Configure formatters accordingly.",
        ),
    ]

    provider = get_provider("anthropic", "claude-haiku-4-5")
    suggestions = await run_merge_suggest_job(
        memories,
        memory_dir=tmp_path,
        provider=provider,
        mtype=MemoryType.FEEDBACK,
        similarity_threshold=0.6, # 寬一點,確保 3 個 concise feedback 進同 cluster
    )

    # 至少 1 個 cluster 被識別,且 LLM 同意合併
    assert len(suggestions) >= 1, (
        "LLM 拒絕合併三個明顯重複的 concise feedback,或 embedding 沒 cluster"
    )

    sug = suggestions[0]
    # 該 cluster 應該包含三個 concise feedback,不含 tabs 那個
    member_set = set(sug.member_filenames)
    assert "feedback_use_tabs.md" not in member_set, (
        f"unrelated memory mistakenly clustered: {member_set}"
    )
    # 三個 concise 至少進兩個進 cluster
    concise_in_cluster = member_set & {
        "feedback_be_concise_1.md",
        "feedback_brief_answers.md",
        "feedback_no_filler.md",
    }
    assert len(concise_in_cluster) >= 2, (
        f"expected ≥2 concise feedbacks in cluster, got: {member_set}"
    )

    # suggestion 真寫進 disk
    loaded = load_suggestions(tmp_path)
    assert len(loaded) == len(suggestions)
    assert loaded[0]["id"] == sug.id

    # LLM 給的內容像樣
    assert sug.merged_name, "empty merged_name"
    assert sug.merged_body, "empty merged_body"
    assert sug.rationale, "empty rationale"

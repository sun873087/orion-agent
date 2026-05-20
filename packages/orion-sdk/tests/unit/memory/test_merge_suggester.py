"""Unit tests for orion_sdk.memory.merge_suggester (Layer 4)。

只測純邏輯(_cosine / _cluster / persistence helpers)。
真實 embedding + LLM 整合測試在 tests/integration/test_memory_merge_suggest.py。
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from orion_sdk.memory.merge_suggester import (
    MergeSuggestion,
    _cluster,
    _cosine,
    load_suggestions,
    remove_suggestion,
    suggestions_path,
)
from orion_sdk.memory.types import Memory, MemoryFrontmatter, MemoryType


def _make_memory(name: str, mtype: MemoryType | None = MemoryType.FEEDBACK) -> Memory:
    fm = MemoryFrontmatter(name=name, description=f"d-{name}", type=mtype)
    return Memory(frontmatter=fm, body=f"body-{name}", file_path=Path(f"{name}.md"))


# ─── _cosine ──────────────────────────────────────────────────────────


def test_cosine_identical() -> None:
    v = [1.0, 2.0, 3.0]
    assert _cosine(v, v) == pytest.approx(1.0)


def test_cosine_orthogonal() -> None:
    assert _cosine([1.0, 0.0], [0.0, 1.0]) == pytest.approx(0.0)


def test_cosine_opposite() -> None:
    assert _cosine([1.0, 0.0], [-1.0, 0.0]) == pytest.approx(-1.0)


def test_cosine_zero_vector_returns_zero() -> None:
    assert _cosine([0.0, 0.0], [1.0, 1.0]) == 0.0


def test_cosine_mismatched_length_returns_zero() -> None:
    assert _cosine([1.0, 2.0], [1.0]) == 0.0


# ─── _cluster ─────────────────────────────────────────────────────────


def test_cluster_groups_similar() -> None:
    mems = [_make_memory(s) for s in "abcd"]
    # a/b/c 同向高 cosine,d 跟所有 orthogonal
    embeds = [
        [1.0, 0.0],
        [0.99, 0.01],
        [0.98, 0.02],
        [0.0, 1.0],
    ]
    clusters = _cluster(mems, embeds, threshold=0.95)
    assert len(clusters) == 1
    assert set(clusters[0]) == {0, 1, 2}


def test_cluster_no_groups_when_dissimilar() -> None:
    mems = [_make_memory(s) for s in "abc"]
    embeds = [
        [1.0, 0.0, 0.0],
        [0.0, 1.0, 0.0],
        [0.0, 0.0, 1.0],
    ]
    clusters = _cluster(mems, embeds, threshold=0.5)
    assert clusters == [] # 沒 cluster ≥2


def test_cluster_excludes_singletons() -> None:
    """單獨 memory 不形成 cluster — 只回 ≥2 的 group。"""
    mems = [_make_memory(s) for s in "abc"]
    embeds = [
        [1.0, 0.0],
        [0.99, 0.01],
        [0.0, 1.0], # 孤兒
    ]
    clusters = _cluster(mems, embeds, threshold=0.95)
    assert clusters == [[0, 1]]


# ─── Persistence helpers ──────────────────────────────────────────────


def test_load_suggestions_empty_when_no_file(tmp_path: Path) -> None:
    assert load_suggestions(tmp_path) == []


def test_load_and_remove_suggestion(tmp_path: Path) -> None:
    sug1 = MergeSuggestion(
        id="sug-1",
        type=MemoryType.FEEDBACK,
        member_filenames=["a.md", "b.md"],
        merged_name="merged",
        merged_description="d",
        merged_body="body",
        rationale="r",
    )
    sug2 = MergeSuggestion(
        id="sug-2",
        type=MemoryType.USER,
        member_filenames=["c.md", "d.md"],
        merged_name="m2",
        merged_description="d2",
        merged_body="b2",
        rationale="r2",
    )
    target = suggestions_path(tmp_path)
    with target.open("w") as f:
        f.write(json.dumps(sug1.to_dict()) + "\n")
        f.write(json.dumps(sug2.to_dict()) + "\n")

    loaded = load_suggestions(tmp_path)
    assert len(loaded) == 2
    assert loaded[0]["id"] == "sug-1"
    assert loaded[1]["id"] == "sug-2"

    assert remove_suggestion(tmp_path, "sug-1") is True
    after = load_suggestions(tmp_path)
    assert len(after) == 1
    assert after[0]["id"] == "sug-2"

    # 移除不存在的 id 回 False
    assert remove_suggestion(tmp_path, "non-existent") is False


def test_load_skips_malformed_lines(tmp_path: Path) -> None:
    target = suggestions_path(tmp_path)
    target.write_text(
        '{"id": "ok"}\n'
        "not json\n"
        '{"id": "ok2"}\n'
    )
    loaded = load_suggestions(tmp_path)
    assert [x["id"] for x in loaded] == ["ok", "ok2"]


def test_merge_suggestion_to_dict_none_type() -> None:
    s = MergeSuggestion(
        id="x",
        type=None,
        member_filenames=["a.md"],
        merged_name="n",
        merged_description="d",
        merged_body="b",
        rationale="r",
    )
    d = s.to_dict()
    assert d["type"] is None
    assert d["id"] == "x"

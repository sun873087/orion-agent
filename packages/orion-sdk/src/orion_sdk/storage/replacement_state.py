"""ContentReplacementState — 第 3 層聚合預算 + 三類分流。

對應 TS Claude Code `utils/toolResultStorage.ts:enforceToolResultBudget`。

核心 invariant:
- **mustReapply**:已替換,套同樣 preview(byte-identical → prompt cache 命中)
- **frozen**:已送過全內容,**永不變動**(prompt cache 穩定)
- **fresh**:本輪新進來,可決策 replace / 留全內容

決策不可逆:
- fresh → 決定不替換 → frozen(永遠不變)
- fresh → 決定替換 → mustReapply(永遠套同樣 preview)

對應第 2 層持久化的差別:第 2 層在工具完成時就替換大結果(individual >= 100KB)。
第 3 層在進 API 前 aggregate 所有 tool result 的 byte 數,若超 budget,挑最大的
fresh ones 替換,直到回到 budget。
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any
from uuid import UUID

from orion_model.types import (
    NormalizedMessage,
    TextBlock,
    ToolResultBlock,
)
from orion_sdk.storage.tool_result import (
    build_large_result_envelope,
    generate_preview,
    persist_tool_result,
)

MAX_TOOL_RESULTS_AGGREGATE_BYTES = 200_000
"""所有 tool_result 加總 byte 上限。超過就觸發 budget enforcement。
對應 TS MAX_TOOL_RESULTS_PER_MESSAGE_CHARS。"""


@dataclass(frozen=True)
class ToolResultCandidate:
    """掃 messages 後找到的 tool_result block 候選人。"""

    tool_use_id: str
    size: int
    content: str
    """原始(可能已是 layer-2 preview)content。"""


@dataclass
class ContentReplacementState:
    """跨 turn 累積的決策歷史。"""

    seen_ids: set[str] = field(default_factory=set)
    """**所有**看過的 tool_use_id(已決策過,凍結後不再變動)。"""

    replacements: dict[str, str] = field(default_factory=dict)
    """已替換的 ID → preview content(送回模型的版本,要 byte-identical 套用)。"""

    def is_frozen(self, tool_use_id: str) -> bool:
        """已 seen 但**沒**在 replacements → 我們之前決定要保留全內容。"""
        return tool_use_id in self.seen_ids and tool_use_id not in self.replacements

    def is_must_reapply(self, tool_use_id: str) -> bool:
        """已決策過要替換 → 一律套用同樣 preview。"""
        return tool_use_id in self.replacements


@dataclass
class Partition:
    must_reapply: list[ToolResultCandidate]
    frozen: list[ToolResultCandidate]
    fresh: list[ToolResultCandidate]


@dataclass
class ReplacementDecision:
    """單筆替換決策(供 transcript 紀錄,resume 時重建 state)。"""

    tool_use_id: str
    replacement: str
    """要套用的 preview 字串(byte-identical 重現)。"""


def _content_to_str(content: str | list[Any]) -> str:
    """ToolResultBlock.content 可能是 str 或 list。轉成單一 str(估 size 用)。"""
    if isinstance(content, str):
        return content
    parts: list[str] = []
    for item in content:
        if isinstance(item, str):
            parts.append(item)
        else:
            parts.append(str(item))
    return "".join(parts)


def collect_candidates(
    messages: list[NormalizedMessage],
) -> list[ToolResultCandidate]:
    """掃 messages 找所有 tool_result block。"""
    out: list[ToolResultCandidate] = []
    for m in messages:
        if not isinstance(m.content, list):
            continue
        for block in m.content:
            if isinstance(block, ToolResultBlock):
                text = _content_to_str(block.content)
                out.append(
                    ToolResultCandidate(
                        tool_use_id=block.tool_use_id,
                        size=len(text.encode("utf-8")),
                        content=text,
                    )
                )
    return out


def partition_by_prior_decision(
    candidates: list[ToolResultCandidate],
    state: ContentReplacementState,
) -> Partition:
    """三類分流。對應 TS partitionByPriorDecision。"""
    must_reapply: list[ToolResultCandidate] = []
    frozen: list[ToolResultCandidate] = []
    fresh: list[ToolResultCandidate] = []
    for c in candidates:
        if state.is_must_reapply(c.tool_use_id):
            must_reapply.append(c)
        elif c.tool_use_id in state.seen_ids:
            frozen.append(c)
        else:
            fresh.append(c)
    return Partition(must_reapply=must_reapply, frozen=frozen, fresh=fresh)


def select_fresh_to_replace(
    eligible: list[ToolResultCandidate],
    *,
    frozen_size: int,
    must_reapply_size: int,
    limit: int,
) -> list[ToolResultCandidate]:
    """從 fresh 中按 size 降序挑,直到 (frozen + must_reapply + 剩餘 fresh) <= limit。

    對應 TS selectFreshToReplace。挑最少數量(=最大 size 優先)以最少擾動換最多空間。
    """
    sorted_eligible = sorted(eligible, key=lambda c: c.size, reverse=True)
    selected: list[ToolResultCandidate] = []
    fresh_remaining = sum(c.size for c in eligible)

    fixed = frozen_size + must_reapply_size

    for c in sorted_eligible:
        if fixed + fresh_remaining <= limit:
            break
        selected.append(c)
        fresh_remaining -= c.size

    return selected


def apply_tool_result_budget(
    messages: list[NormalizedMessage],
    state: ContentReplacementState,
    session_id: UUID,
    *,
    limit: int = MAX_TOOL_RESULTS_AGGREGATE_BYTES,
) -> tuple[list[NormalizedMessage], list[ReplacementDecision]]:
    """執行第 3 層預算檢查 + 替換。**mutates `state`** 以記錄新決策。

    Returns:
        (new_messages, decisions_made_this_round)

    Steps:
        1. collect candidates
        2. partition (mustReapply / frozen / fresh)
        3. mustReapply: 套舊 preview(state.replacements[id])
        4. select_fresh_to_replace 挑 fresh → 寫檔 + 換 preview + 加進 state
        5. frozen 不動
        6. 重建 messages
    """
    candidates = collect_candidates(messages)
    if not candidates:
        return messages, []

    partition = partition_by_prior_decision(candidates, state)

    must_reapply_size = sum(len(state.replacements[c.tool_use_id].encode("utf-8"))
                             for c in partition.must_reapply)
    frozen_size = sum(c.size for c in partition.frozen)

    # 1. 強制替換 mustReapply(用 state 內已存的 preview)
    new_replacements: dict[str, str] = dict(state.replacements)

    # 2. fresh 中挑出要替換的(若超 budget)
    to_replace = select_fresh_to_replace(
        partition.fresh,
        frozen_size=frozen_size,
        must_reapply_size=must_reapply_size,
        limit=limit,
    )
    decisions: list[ReplacementDecision] = []

    for c in to_replace:
        # 寫檔 + 產生新 preview envelope
        path = persist_tool_result(session_id, c.tool_use_id, c.content)
        preview = generate_preview(c.content)
        envelope = build_large_result_envelope(c.tool_use_id, preview, path, c.size)
        new_replacements[c.tool_use_id] = envelope
        state.seen_ids.add(c.tool_use_id)
        decisions.append(
            ReplacementDecision(tool_use_id=c.tool_use_id, replacement=envelope)
        )

    # 3. fresh 中沒被選中的 → 標 seen 但不替換 → 變 frozen
    selected_ids = {c.tool_use_id for c in to_replace}
    for c in partition.fresh:
        if c.tool_use_id not in selected_ids:
            state.seen_ids.add(c.tool_use_id)

    # 4. 重建 messages,把所有應替換的 id 套上 envelope
    state.replacements = new_replacements
    new_messages = _rewrite_messages(messages, state.replacements)
    return new_messages, decisions


def _rewrite_messages(
    messages: list[NormalizedMessage],
    replacements: dict[str, str],
) -> list[NormalizedMessage]:
    """掃 messages,把 ToolResultBlock 中 tool_use_id ∈ replacements 的內容換掉。"""
    if not replacements:
        return messages

    out: list[NormalizedMessage] = []
    for m in messages:
        if not isinstance(m.content, list):
            out.append(m)
            continue

        new_blocks: list[Any] = []
        changed = False
        for block in m.content:
            if isinstance(block, ToolResultBlock) and block.tool_use_id in replacements:
                new_blocks.append(
                    ToolResultBlock(
                        tool_use_id=block.tool_use_id,
                        content=replacements[block.tool_use_id],
                        is_error=block.is_error,
                    )
                )
                changed = True
            else:
                new_blocks.append(block)

        if changed:
            out.append(NormalizedMessage(role=m.role, content=new_blocks))
        else:
            out.append(m)
    return out


def reconstruct_content_replacement_state(
    messages: list[NormalizedMessage],
    records: list[dict[str, Any]],
) -> ContentReplacementState:
    """Resume 時從 transcript 重建 state。

    對應 TS reconstructContentReplacementState。

    每個 ID:
    - records 有對應 → replacements 設舊 preview(套用一致性)
    - messages 有但 records 沒 → 加入 seen_ids(視為 frozen,**不主動**替換)

    Args:
        messages: 從 transcript 重建的 NormalizedMessage list
        records: dict 列表,每筆 {"kind": "tool-result-replacement",
                  "tool_use_id": str, "replacement": str}
    """
    state = ContentReplacementState()
    candidate_ids = {c.tool_use_id for c in collect_candidates(messages)}

    for cid in candidate_ids:
        state.seen_ids.add(cid)

    for r in records:
        if r.get("kind") != "tool-result-replacement":
            continue
        tu_id = r.get("tool_use_id")
        replacement = r.get("replacement")
        if tu_id in candidate_ids and isinstance(replacement, str):
            state.replacements[tu_id] = replacement

    # ToolResultBlock 中 ID 在 state.replacements 的 → 也應該確保 messages 已套用 envelope
    # 這個責任由 caller 在 resume 後 call apply_tool_result_budget 一次完成
    # 或更直接:把 messages 內套舊 replacement
    for cid in state.replacements:
        state.seen_ids.add(cid)

    # Use TextBlock import to silence unused-import (kept for future use)
    _ = TextBlock
    return state

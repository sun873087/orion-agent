"""AgentSummary — agent 完成後給人類看的兩三句摘要。Phase 15。

對應 TS Claude Code `src/services/AgentSummary/agentSummary.ts`。

設計:
- 用 Phase 12 `services.side_query`(不汙染主對話)
- 預設 model 為 Haiku — 摘要任務簡單,Sonnet 過度殺雞(spec § 6 設計決策)
- 產出 2-4 句,聚焦「DO 了什麼」,不寫嘗試 / 過程
- 失敗回 fallback 字串(不 raise),呼叫端可信任
"""

from __future__ import annotations

from orion_model.provider import LLMProvider
from orion_model.types import (
    NormalizedMessage,
    TextBlock,
    ToolResultBlock,
    ToolUseBlock,
)
from orion_sdk.services.side_query import (
    SideQueryParams,
    side_query,
)

_SUMMARY_SYSTEM_PROMPT = """\
You are summarizing the work an agent just completed.

Your summary should be:
- 2 to 4 sentences
- Focus on what was DONE (not what was tried or planned)
- Mention key files modified or findings discovered
- Plain prose, suitable for showing to a human user who wasn't present

Format: just the summary text, no preamble, no markdown headings.
"""

_MAX_TRANSCRIPT_CHARS = 6_000
"""餵給 Haiku 摘要前先截斷 — 太長會浪費 input tokens 又降摘要品質。"""

_MAX_SUMMARY_TOKENS = 256


def _format_block(block: object) -> str:
    """單一 ContentBlock → plain text。"""
    if isinstance(block, TextBlock):
        return block.text
    if isinstance(block, ToolUseBlock):
        return f"[tool_use {block.name}({block.input})]"
    if isinstance(block, ToolResultBlock):
        content_str = (
            block.content if isinstance(block.content, str) else str(block.content)
        )
        short = content_str[:200] + ("..." if len(content_str) > 200 else "")
        return f"[tool_result] {short}"
    return ""


def _format_messages(messages: list[NormalizedMessage]) -> str:
    """整段對話攤平給 Haiku 看。"""
    lines: list[str] = []
    for m in messages:
        if isinstance(m.content, str):
            text = m.content
        else:
            parts = [_format_block(b) for b in m.content]
            text = "\n".join(p for p in parts if p)
        if not text.strip():
            continue
        lines.append(f"[{m.role}]\n{text}")
    full = "\n\n".join(lines)
    if len(full) <= _MAX_TRANSCRIPT_CHARS:
        return full
    head = full[: _MAX_TRANSCRIPT_CHARS // 2]
    tail = full[-_MAX_TRANSCRIPT_CHARS // 2 :]
    return f"{head}\n\n... [middle truncated] ...\n\n{tail}"


async def generate_agent_summary(
    messages: list[NormalizedMessage],
    *,
    provider: LLMProvider,
    agent_name: str = "agent",
) -> str:
    """從 agent 對話歷史產生 2-4 句人類友善摘要。

    Args:
        messages: agent 的整段對話(或最後 N 則)。
        provider: LLMProvider — caller 通常傳 Haiku model 的 provider(便宜快)。
        agent_name: 用在 prompt(`Agent {name} just completed work...`)。

    Returns:
        摘要字串。失敗回 `[<agent_name> completed work without summary]`(不 raise)。
    """
    if not messages:
        return f"[{agent_name} produced no messages]"

    transcript = _format_messages(messages)
    if not transcript.strip():
        return f"[{agent_name} produced no textual content]"

    user_text = (
        f"Agent {agent_name} just completed work. "
        f"Provide the 2-4 sentence summary as instructed.\n\n"
        f"Transcript:\n{transcript}"
    )

    try:
        result = await side_query(
            SideQueryParams(
                system=_SUMMARY_SYSTEM_PROMPT,
                user_text=user_text,
                max_tokens=_MAX_SUMMARY_TOKENS,
                query_source="general",
            ),
            provider=provider,
        )
    except Exception:  # noqa: BLE001 — 摘要失敗不該 raise
        return f"[{agent_name} completed work without summary]"

    summary = result.text.strip()
    if not summary:
        return f"[{agent_name} completed work without summary]"
    return summary


__all__ = ["generate_agent_summary"]

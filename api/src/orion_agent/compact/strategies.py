"""Compaction 策略。

Phase 3 範圍兩種:
- **SonnetSummaryStrategy**:呼 LLM 摘要前段 messages,寫成自然語言
- **TruncateStrategy**:fallback — 純截斷 + 加註記(LLM 失敗或刻意關閉時用)

Strategy 介面:`async def summarize(messages, *, provider) -> str`
"""

from __future__ import annotations

from typing import Protocol

from orion_agent.llm.events import (
    MessageStopEvent,
    TextDeltaEvent,
)
from orion_agent.llm.provider import LLMProvider
from orion_agent.llm.types import (
    NormalizedMessage,
    TextBlock,
    ToolResultBlock,
    ToolUseBlock,
)

_SUMMARY_SYSTEM_PROMPT = """\
You compress an earlier portion of an agent conversation into a concise
summary that the model can use to recall what happened.

Include:
- The user's original task / goals
- Key tool calls and what they discovered (file paths, commands run, findings)
- Decisions made and code changes
- Errors encountered

Omit:
- Verbose tool output (just the conclusions)
- Repetitive reasoning
- Already-resolved confusion

Output a single coherent paragraph or bullet list. Aim for 200-500 words.
No preamble, no meta-commentary."""


def _flatten_messages_for_summary(
    messages: list[NormalizedMessage],
) -> str:
    """轉換 messages 成 LLM 可讀的 transcript 文字。"""
    lines: list[str] = []
    for m in messages:
        role = m.role
        if isinstance(m.content, str):
            lines.append(f"## {role}\n{m.content}\n")
            continue
        if not isinstance(m.content, list):
            continue
        for block in m.content:
            if isinstance(block, TextBlock):
                lines.append(f"## {role}\n{block.text}\n")
            elif isinstance(block, ToolUseBlock):
                lines.append(f"## {role} [tool_use {block.name}]\nargs: {block.input}\n")
            elif isinstance(block, ToolResultBlock):
                content_str = (
                    block.content
                    if isinstance(block.content, str)
                    else str(block.content)
                )
                short = content_str[:500] + ("..." if len(content_str) > 500 else "")
                lines.append(f"## {role} [tool_result]\n{short}\n")
    return "\n".join(lines)


class CompactionStrategy(Protocol):
    async def summarize(
        self,
        messages: list[NormalizedMessage],
        *,
        provider: LLMProvider,
    ) -> str:
        ...


class SonnetSummaryStrategy:
    """LLM 摘要 — 用 LLMProvider(可為 Anthropic 或 OpenAI)。

    名字保留 "Sonnet" 是因為 spec 用 Sonnet,但實際接受任何 provider。
    """

    async def summarize(
        self,
        messages: list[NormalizedMessage],
        *,
        provider: LLMProvider,
    ) -> str:
        if not messages:
            return "(no prior messages)"

        flat = _flatten_messages_for_summary(messages)
        user_text = (
            f"Below is the earlier portion of an agent conversation that needs "
            f"to be compressed. Write a summary the agent can use to remember "
            f"what happened.\n\n---\n{flat}\n---"
        )

        chunks: list[str] = []
        async for ev in provider.stream(
            system=_SUMMARY_SYSTEM_PROMPT,
            messages=[NormalizedMessage(role="user", content=user_text)],
            tools=[],
            max_tokens=1024,
        ):
            if isinstance(ev, TextDeltaEvent):
                chunks.append(ev.text)
            elif isinstance(ev, MessageStopEvent):
                break
        result = "".join(chunks).strip()
        if not result:
            return TruncateStrategy().summarize_sync(messages)
        return result


class TruncateStrategy:
    """Fallback — 純截斷,不打 LLM。"""

    async def summarize(
        self,
        messages: list[NormalizedMessage],
        *,
        provider: LLMProvider,  # noqa: ARG002
    ) -> str:
        return self.summarize_sync(messages)

    def summarize_sync(self, messages: list[NormalizedMessage]) -> str:
        if not messages:
            return "(no prior messages)"
        n = len(messages)
        roles = [m.role for m in messages]
        return (
            f"[Earlier conversation truncated: {n} messages "
            f"(roles: {' → '.join(roles[:5])}...{' → '.join(roles[-3:])}). "
            "Full content elided to free context.]"
        )

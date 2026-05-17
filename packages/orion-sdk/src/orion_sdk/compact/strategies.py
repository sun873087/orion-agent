"""Compaction 策略。

Phase 3 範圍兩種:
- **SonnetSummaryStrategy**:呼 LLM 摘要前段 messages,寫成自然語言
- **TruncateStrategy**:fallback — 純截斷 + 加註記(LLM 失敗或刻意關閉時用)

Strategy 介面:`async def summarize(messages, *, provider) -> str`
"""

from __future__ import annotations

from typing import Protocol

from orion_model.events import (
    MessageStopEvent,
    TextDeltaEvent,
)
from orion_model.provider import LLMProvider
from orion_model.types import (
    NormalizedMessage,
    TextBlock,
    ToolResultBlock,
    ToolUseBlock,
)

_LOCALE_LABELS: dict[str, str] = {
    "zh-TW": "Traditional Chinese (繁體中文)",
    "zh-CN": "Simplified Chinese (简体中文)",
    "ja": "Japanese (日本語)",
    "en": "English",
}


def _build_summary_system_prompt(locale: str | None) -> str:
    """組摘要 system prompt — 含目標語系 + 長度縮放規則。

    locale: 'zh-TW' / 'zh-CN' / 'ja' / 'en';None 或不認得就 fallback English。
    """
    lang_label = _LOCALE_LABELS.get(locale or "", "English")
    return f"""\
You compress an earlier portion of an agent conversation into a concise
summary that the model can use to recall what happened.

LANGUAGE: write the summary in **{lang_label}**, matching how the user spoke.

LENGTH — scale to the actual conversation:
- 1-3 turns or a single tool call → 1-2 short bullet lines (~30-60 words)
- 4-10 turns → ~80-150 words
- 10+ turns / substantial work → 200-400 words
Do not pad. A short conversation deserves a short summary.

Include:
- The user's task / goals
- Key tool calls and findings (file paths, commands run, results)
- Decisions made and code changes
- Errors encountered

Omit:
- Verbose tool output (just conclusions)
- Repetitive reasoning
- Already-resolved confusion

Output: bullets or a single paragraph. No preamble, no meta-commentary."""


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
        locale: str | None = None,
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
        locale: str | None = None,
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
            system=_build_summary_system_prompt(locale),
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
        locale: str | None = None,  # noqa: ARG002
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

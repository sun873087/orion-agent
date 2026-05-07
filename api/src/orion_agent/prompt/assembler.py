"""組裝 system prompt。

對應 spec § 5 fetch_system_prompt_parts + build_system_prompt_list。

流程:
  1. fetch_system_prompt_parts(ctx, ...)
     → 並行蒐集動態段(env / git / memory / instructions)
     → 靜態段從 cache 拿(首次計算後 reuse)
  2. build_system_prompt_list(parts)
     → 回 `list[str]`,2 元素:[<靜態段全部 join>, <動態段全部 join>]
     → Anthropic provider 看到 list[str] 自動加 cache_control
        (Phase 0 既有實作)
     → OpenAI provider 看到 list[str] 自動 join 成單字串

Caller 把 list 直接傳給 provider.stream(system=...)。
"""

from __future__ import annotations

import asyncio
from dataclasses import dataclass, field
from pathlib import Path

from orion_agent.llm.provider import LLMProvider
from orion_agent.llm.types import NormalizedMessage
from orion_agent.prompt.dynamic_sections import (
    env_info_section,
    instructions_section,
    language_section,
    memory_section,
    output_style_section,
    session_guidance_section,
)
from orion_agent.prompt.sections import register_section
from orion_agent.prompt.static_sections import render_static_block


@dataclass
class SystemPromptParts:
    """組裝中間結果。caller 通常不直接看,build_system_prompt_list 處理。"""

    static_block: str = ""
    """7 段靜態 system prompt(享 cache)。"""

    dynamic_blocks: list[str] = field(default_factory=list)
    """各動態段內容(env / instructions / memory / language / etc.)。"""


async def fetch_system_prompt_parts(
    *,
    cwd: Path | None = None,
    user_id: str = "default",
    conversation_messages: list[NormalizedMessage] | None = None,
    provider: LLMProvider | None = None,
    language: str | None = None,
    output_style: str | None = None,
    session_guidance: str | None = None,
    use_cache: bool = True,
) -> SystemPromptParts:
    """並行蒐集 system prompt 各段。

    靜態段走 section cache(register_section);動態段每次重算。

    Args:
        cwd: working dir(影響 env / git / instructions)— None 用 Path.cwd()
        user_id: memory 用
        conversation_messages: memory rank 比對用,給最近 user query
        provider: memory rank 用(若為 None,純 heuristic)
        language: 強制回應語言(可選)
        output_style: 例 "haiku" / "json" 等(可選)
        session_guidance: ad-hoc per-conversation 指引(可選)
        use_cache: False → 靜態段也重算(/clear command 用)

    Returns:
        SystemPromptParts
    """
    cwd = cwd or Path.cwd()
    msgs = conversation_messages or []

    # ─── 靜態段(走 cache)─────────────────────────────────────────────
    if use_cache:
        static_block = await register_section(
            "static_block_v1",
            lambda: _async_static_block(),
        )
    else:
        static_block = render_static_block()

    # ─── 動態段(並行)───────────────────────────────────────────────
    env_task = env_info_section(cwd)
    memory_task = memory_section(
        user_id=user_id,
        conversation_messages=msgs,
        provider=provider,
    )
    env_text, memory_text = await asyncio.gather(env_task, memory_task)

    # 同步段(無 I/O)
    instructions_text = instructions_section(cwd)
    language_text = language_section(language)
    output_style_text = output_style_section(output_style)
    session_guidance_text = session_guidance_section(session_guidance)

    dynamic_blocks: list[str] = [
        b
        for b in (
            env_text,
            instructions_text,
            memory_text,
            language_text,
            output_style_text,
            session_guidance_text,
        )
        if b.strip()
    ]

    return SystemPromptParts(
        static_block=static_block,
        dynamic_blocks=dynamic_blocks,
    )


async def _async_static_block() -> str:
    """純 sync render 包成 async,給 register_section 用。"""
    return render_static_block()


def build_system_prompt_list(parts: SystemPromptParts) -> list[str]:
    """SystemPromptParts → list[str](給 LLMProvider.stream)。

    格式:`[<static joined>, <dynamic joined>]`
    - Anthropic 自動把 last-1 element 標 cache_control(Phase 0 既有)— 即靜態段
    - OpenAI list-mode 自動 "\\n\\n".join → 單字串(自動 cache 開頭 prefix)

    若沒動態段 → 仍回 2 元素 list,第二段空字串(維持 cache breakpoint)。
    """
    static = parts.static_block.strip()
    dynamic = "\n\n".join(b.strip() for b in parts.dynamic_blocks if b.strip())
    return [static, dynamic]

"""組裝 system prompt。

對應 spec § 5 fetch_system_prompt_parts + build_system_prompt_list。

流程:
  1. fetch_system_prompt_parts(ctx, ...)
     → 並行蒐集動態段(env / git / memory / instructions)
     → 靜態段從 cache 拿(首次計算後 reuse)
  2. build_system_prompt_list(parts)
     → 回 `list[str]`,2 元素:[<靜態段>, <session-stable 動態段>]
     → 兩段都 session-stable,Anthropic provider 在每段標 cache_control
        ↳ 對話歷史 cache 不會被中間 volatile 段破壞
     → OpenAI provider 看到 list[str] 自動 join 成單字串

  3. per_turn_text(volatile 內容:memory + git_status)
     → 不進 system prompt,由 caller 注入 user message
     → 避免破壞 system → messages 的 cache prefix 連續性

Caller 把 list 傳給 provider.stream(system=...),per_turn_text 拼到當前 user input 前。
"""

from __future__ import annotations

import asyncio
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from orion_model.provider import LLMProvider
from orion_model.types import NormalizedMessage
from orion_sdk.prompt.dynamic_sections import (
    env_info_stable_section,
    git_status_section,
    instructions_section,
    language_section,
    mcp_instructions_section,
    memory_section,
    output_style_section,
    session_guidance_section,
)
from orion_sdk.prompt.sections import register_section
from orion_sdk.prompt.static_sections import render_static_block


@dataclass
class SystemPromptParts:
    """組裝中間結果。caller 通常不直接看,build_system_prompt_list 處理。"""

    static_block: str = ""
    """7 段靜態 system prompt(享 cache,跨 session 重用)。"""

    session_stable_blocks: list[str] = field(default_factory=list)
    """session-stable 動態段(享 cache,session 內重用):
    instructions / custom_instructions / mcp / language / output_style /
    session_guidance / env_info(platform/cwd/date)。"""

    per_turn_text: str = ""
    """per-turn volatile 內容(memory + git_status)— 不進 system,由 caller
    注入 user message。"""


async def fetch_system_prompt_parts(
    *,
    cwd: Path | None = None,
    user_id: str = "default",
    conversation_messages: list[NormalizedMessage] | None = None,
    provider: LLMProvider | None = None,
    language: str | None = None,
    output_style: str | None = None,
    session_guidance: str | None = None,
    mcp_manager: object | None = None,
    use_cache: bool = True,
    custom_instructions_user: str | None = None,
    custom_instructions_conversation: str | None = None,
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

    # ─── per-turn volatile(並行)— 不進 system ─────────────────────
    git_task = git_status_section(cwd)
    memory_task = memory_section(
        user_id=user_id,
        conversation_messages=msgs,
        provider=provider,
    )
    git_text, memory_text = await asyncio.gather(git_task, memory_task)

    # ─── session-stable 動態段(同步,無 I/O)── 進 system,享 cache ──
    env_stable_text = env_info_stable_section(cwd)
    instructions_text = instructions_section(cwd)
    language_text = language_section(language)
    output_style_text = output_style_section(output_style)
    session_guidance_text = session_guidance_section(session_guidance)
    mcp_text = mcp_instructions_section(mcp_manager)

    # Phase 13:Web chat 的 custom instructions(已從 DB 拉好)
    custom_inst_text = ""
    if custom_instructions_user or custom_instructions_conversation:
        from orion_sdk.prompt.instructions import (
            CustomInstructions,
            assemble_instructions_section,
        )
        custom_inst_text = assemble_instructions_section(
            CustomInstructions(
                user_level=custom_instructions_user,
                conversation_level=custom_instructions_conversation,
            )
        )

    session_stable_blocks: list[str] = [
        b
        for b in (
            env_stable_text,
            instructions_text,
            custom_inst_text,
            mcp_text,
            language_text,
            output_style_text,
            session_guidance_text,
        )
        if b.strip()
    ]

    per_turn_text = "\n\n".join(
        b.strip() for b in (memory_text, git_text) if b.strip()
    )

    return SystemPromptParts(
        static_block=static_block,
        session_stable_blocks=session_stable_blocks,
        per_turn_text=per_turn_text,
    )


async def _async_static_block() -> str:
    """純 sync render 包成 async,給 register_section 用。"""
    return render_static_block()


def inject_per_turn_into_user_message(
    user_msg: NormalizedMessage, per_turn_text: str
) -> NormalizedMessage:
    """把 per-turn volatile 內容注入 user message 開頭。

    回新的 NormalizedMessage(不 mutate 原物件)。空 per_turn 直接回原物件。

    String content:用 `\\n\\n` 分隔 per_turn 與原 user text。
    List content(含 image/tool 等 block):在 list 開頭插入 TextBlock。
    """
    if not per_turn_text.strip():
        return user_msg

    if isinstance(user_msg.content, str):
        new_content: str | list[Any] = (
            f"{per_turn_text.strip()}\n\n{user_msg.content}"
        )
    else:
        from orion_model.types import TextBlock
        new_content = [TextBlock(text=per_turn_text.strip()), *user_msg.content]

    return NormalizedMessage(role=user_msg.role, content=new_content)


def build_system_prompt_list(parts: SystemPromptParts) -> list[str]:
    """SystemPromptParts → list[str](給 LLMProvider.stream)。

    回傳 `[static_block, session_stable_block]` — 兩段都 session-stable,
    Anthropic provider 在每段標 cache_control(2 個 cache breakpoint)。

    per_turn_text(memory + git_status)**不**在這個 list 裡 — caller 從
    `parts.per_turn_text` 拿,注入 user message 開頭。

    若沒 session-stable 段 → 第二段空字串(2 元素 list 維持 bp 結構穩定)。
    """
    static = parts.static_block.strip()
    session_stable = "\n\n".join(
        b.strip() for b in parts.session_stable_blocks if b.strip()
    )
    return [static, session_stable]

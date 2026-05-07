"""動態段 builder — env / instructions / memory / language / output_style。

對應 spec § 5 dynamic 部分。

這些段 each turn 都重算(內容會隨 cwd / git status / 新 memory 而變)。
跟靜態段不同,**不**進 section_cache。
"""

from __future__ import annotations

from pathlib import Path

from orion_agent.llm.provider import LLMProvider
from orion_agent.llm.types import NormalizedMessage
from orion_agent.memory.paths import user_memory_paths
from orion_agent.memory.relevance import rank_memories
from orion_agent.memory.render import render_memories
from orion_agent.memory.scan import scan_memory_dir
from orion_agent.prompt.context import (
    find_instructions_files,
    get_env_info,
    get_git_context,
    read_instructions,
)


async def env_info_section(cwd: Path | None = None) -> str:
    """env info + git status 拼成一段。"""
    env = get_env_info(cwd)
    git = await get_git_context(cwd)
    if git:
        return f"# Environment\n\n{env}\n\n{git}"
    return f"# Environment\n\n{env}"


def instructions_section(cwd: Path | None = None) -> str:
    """user instructions(.orion/instructions.md)— 沒檔回空。"""
    files = find_instructions_files(cwd)
    if not files:
        return ""
    text = read_instructions(files)
    if not text.strip():
        return ""
    return f"# User instructions\n\n{text}"


async def memory_section(
    *,
    user_id: str,
    conversation_messages: list[NormalizedMessage],
    provider: LLMProvider | None = None,
    max_results: int = 10,
) -> str:
    """挑相關 memory 並 render 成 system prompt 區塊。

    包 Phase 3 機制:scan + rank + render。沒 memory / 載入失敗 → 回空字串。
    """
    try:
        paths = user_memory_paths(user_id)
        index = scan_memory_dir(paths)
        if not index.memories:
            return ""
        relevant = await rank_memories(
            index.memories,
            conversation_messages,
            provider=provider,
            max_results=max_results,
        )
        return render_memories(relevant)
    except Exception:  # noqa: BLE001 — memory 載入失敗不該影響對話
        return ""


def output_style_section(style: str | None = None) -> str:
    """選用的 output style hint。預設不加。"""
    if not style:
        return ""
    return f"# Output style\n\nFormat your response as: {style}"


def language_section(language: str | None = None) -> str:
    """user 偏好的回應語言。"""
    if not language:
        return ""
    return (
        f"# Response language\n\n"
        f"Respond in **{language}** unless the user explicitly asks otherwise."
    )


def session_guidance_section(extra: str | None = None) -> str:
    """Conversation 級別的 ad-hoc 指引(若有)。"""
    if not extra:
        return ""
    return f"# Session guidance\n\n{extra}"

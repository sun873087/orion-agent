"""動態段 builder — env / instructions / memory / language / output_style。

對應 spec § 5 dynamic 部分。

**Volatility 分類**(2026-05-10 cache 優化後):
- session-stable(進 system prompt 的 session_stable_block,享 cache):
  instructions / custom_instructions / mcp_instructions / language / output_style /
  session_guidance / env_info_stable(platform / cwd / date)
- per-turn(不進 system prompt,改注入 user message,避免破壞 cache prefix):
  memory / git_status

跟靜態段不同,**不**進 section_cache(每次重新計算,但內容多半不變 → cache hit)。
"""

from __future__ import annotations

from pathlib import Path

from orion_model.provider import LLMProvider
from orion_model.types import NormalizedMessage
from orion_sdk.memory.paths import user_memory_paths
from orion_sdk.memory.relevance import rank_memories
from orion_sdk.memory.render import render_memories
from orion_sdk.memory.scan import scan_memory_dir
from orion_sdk.prompt.context import (
    find_instructions_files,
    get_env_info,
    get_git_context,
    read_instructions,
)


def env_info_stable_section(cwd: Path | None = None) -> str:
    """session-stable env info(platform / cwd / date)— 不含 git。

    git_status 抽到 git_status_section(per-turn,不進 system prompt)。
    """
    env = get_env_info(cwd)
    return f"# Environment\n\n{env}"


async def git_status_section(cwd: Path | None = None) -> str:
    """per-turn git status — 抽出獨立段供 user-message 注入。"""
    git = await get_git_context(cwd)
    if not git:
        return ""
    return f"# Git status\n\n{git}"


async def env_info_section(cwd: Path | None = None) -> str:
    """[deprecated] env info + git status 拼成一段。

    保留給 backward-compat / 測試使用。新代碼請分別用
    env_info_stable_section + git_status_section。
    """
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
        # prompt 注入路徑明確排除已過期 memory(Layer 2 TTL)— UI / extract 仍看全部
        index = scan_memory_dir(paths, exclude_expired=True)
        if not index.memories:
            return ""
        relevant = await rank_memories(
            index.memories,
            conversation_messages,
            provider=provider,
            max_results=max_results,
            memory_dir=paths.memory_dir,
        )
        return render_memories(relevant)
    except Exception:  # noqa: BLE001 — memory 載入失敗不該影響對話
        return ""


def output_style_section(style: str | None = None) -> str:
    """選用的 output style。

    Phase 13:若 `style` 是已註冊的 output style 名(`~/.orion/output-styles/<name>.md`
    或 `<cwd>/.orion/output-styles/<name>.md`),直接用該檔的 prompt body 作 section。
    找不到對應檔則 fallback 到簡易 hint(維持 Phase 0 行為)。
    """
    if not style:
        return ""
    try:
        from orion_sdk.output_styles.loader import find_output_style
        loaded = find_output_style(style)
    except Exception:  # noqa: BLE001 — loader 失敗不該影響對話
        loaded = None
    if loaded is not None:
        return f"# Output style: {loaded.name}\n\n{loaded.prompt.strip()}"
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


def mcp_instructions_section(mcp_manager: object | None) -> str:
    """Phase 5:已連 MCP servers + 工具列表。

    Args:
        mcp_manager: McpManager instance(避免循環 import,型別 object)
    """
    if mcp_manager is None:
        return ""

    summary = getattr(mcp_manager, "server_summary", None)
    if not callable(summary):
        return ""

    body = summary()
    if not body:
        return ""

    return (
        "# MCP servers connected\n\n"
        f"{body}\n\n"
        "Tools from these servers are prefixed `mcp__<server>__<tool>`. "
        "Use them like any other tool — they appear in your tool list."
    )

"""prompt/assembler.py — fetch_system_prompt_parts + build_system_prompt_list。

2026-05-10 結構變更:
- dynamic_blocks 改為 session_stable_blocks(進 system,享 cache)
- 新增 per_turn_text(memory + git_status,不進 system,由 caller 注入 user msg)
"""

from __future__ import annotations

from pathlib import Path

import pytest

from orion_model.types import NormalizedMessage
from orion_agent.prompt.assembler import (
    SystemPromptParts,
    build_system_prompt_list,
    fetch_system_prompt_parts,
    inject_per_turn_into_user_message,
)
from orion_agent.prompt.sections import clear_section_cache


@pytest.fixture(autouse=True)
def clear_cache() -> None:
    clear_section_cache()


@pytest.mark.asyncio
async def test_fetch_returns_parts(tmp_path: Path) -> None:
    parts = await fetch_system_prompt_parts(cwd=tmp_path)
    assert isinstance(parts, SystemPromptParts)
    assert parts.static_block  # 7 段 prompt 拼起來總是有內容
    # session-stable 段至少有 env_info(總有 platform / cwd / date)
    assert any("Environment" in b for b in parts.session_stable_blocks)


@pytest.mark.asyncio
async def test_static_block_cached_across_calls(tmp_path: Path) -> None:
    """第二次 fetch 應拿 cached 靜態段(同字串)。"""
    p1 = await fetch_system_prompt_parts(cwd=tmp_path)
    p2 = await fetch_system_prompt_parts(cwd=tmp_path)
    assert p1.static_block == p2.static_block
    assert p1.static_block is p2.static_block  # cached → 同物件


@pytest.mark.asyncio
async def test_session_stable_changes_with_cwd(tmp_path: Path) -> None:
    """不同 cwd 應產生不同 env_info(在 session_stable 段)。"""
    a = tmp_path / "a"
    a.mkdir()
    b = tmp_path / "b"
    b.mkdir()
    p1 = await fetch_system_prompt_parts(cwd=a)
    p2 = await fetch_system_prompt_parts(cwd=b)
    env1 = next(x for x in p1.session_stable_blocks if "Environment" in x)
    env2 = next(x for x in p2.session_stable_blocks if "Environment" in x)
    assert "/a" in env1
    assert "/b" in env2


@pytest.mark.asyncio
async def test_env_info_in_session_stable_does_not_include_git(tmp_path: Path) -> None:
    """session_stable 的 env_info 不應含 git_status(git 在 per_turn)。"""
    parts = await fetch_system_prompt_parts(cwd=tmp_path)
    env = next(x for x in parts.session_stable_blocks if "Environment" in x)
    assert "branch:" not in env  # git_status 字樣應在 per_turn_text


def test_build_returns_two_element_list() -> None:
    parts = SystemPromptParts(
        static_block="STATIC",
        session_stable_blocks=["env", "instructions"],
    )
    out = build_system_prompt_list(parts)
    assert len(out) == 2
    assert out[0] == "STATIC"
    assert "env" in out[1] and "instructions" in out[1]


def test_build_with_empty_session_stable() -> None:
    parts = SystemPromptParts(static_block="STATIC", session_stable_blocks=[])
    out = build_system_prompt_list(parts)
    assert out == ["STATIC", ""]


def test_per_turn_text_not_in_system_list() -> None:
    """per_turn_text 應該獨立於 system list,不混入。"""
    parts = SystemPromptParts(
        static_block="STATIC",
        session_stable_blocks=["env"],
        per_turn_text="MEMORY:\nfoo\n\n# Git status\nbranch: main",
    )
    out = build_system_prompt_list(parts)
    assert "MEMORY" not in out[0]
    assert "MEMORY" not in out[1]
    assert "branch: main" not in out[0]
    assert "branch: main" not in out[1]
    # 但 parts.per_turn_text 仍可取到
    assert "MEMORY" in parts.per_turn_text


def test_inject_per_turn_into_string_user_message() -> None:
    msg = NormalizedMessage(role="user", content="hello")
    out = inject_per_turn_into_user_message(msg, "MEMORY:\nfoo")
    assert isinstance(out.content, str)
    assert out.content.startswith("MEMORY:\nfoo")
    assert out.content.endswith("hello")


def test_inject_per_turn_empty_returns_original() -> None:
    msg = NormalizedMessage(role="user", content="hello")
    out = inject_per_turn_into_user_message(msg, "")
    assert out is msg  # 原物件回傳


def test_inject_per_turn_whitespace_returns_original() -> None:
    msg = NormalizedMessage(role="user", content="hello")
    out = inject_per_turn_into_user_message(msg, "   \n\n  ")
    assert out is msg


@pytest.mark.asyncio
async def test_use_cache_false_recomputes(tmp_path: Path) -> None:
    """use_cache=False(對應 /clear command)→ 每次重算靜態段。"""
    p1 = await fetch_system_prompt_parts(cwd=tmp_path)
    p2 = await fetch_system_prompt_parts(cwd=tmp_path, use_cache=False)
    # 內容應一致(deterministic),但 p2 沒從 cache 走
    assert p1.static_block == p2.static_block


@pytest.mark.asyncio
async def test_instructions_md_loaded(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """寫 instructions.md → 被載入 session_stable 段。"""
    monkeypatch.setattr(
        "orion_agent.prompt.context.Path.home", lambda: tmp_path / "fakehome"
    )
    cwd = tmp_path / "proj"
    cwd.mkdir()
    (cwd / ".orion").mkdir()
    (cwd / ".orion" / "instructions.md").write_text("haiku format only", encoding="utf-8")

    parts = await fetch_system_prompt_parts(cwd=cwd)
    instructions_block = next(
        (b for b in parts.session_stable_blocks if "User instructions" in b), None,
    )
    assert instructions_block is not None
    assert "haiku" in instructions_block

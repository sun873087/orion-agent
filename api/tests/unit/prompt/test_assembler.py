"""prompt/assembler.py — fetch_system_prompt_parts + build_system_prompt_list。"""

from __future__ import annotations

from pathlib import Path

import pytest

from orion_agent.prompt.assembler import (
    SystemPromptParts,
    build_system_prompt_list,
    fetch_system_prompt_parts,
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
    # 動態段至少有 env_info(總有 platform / cwd / date)
    assert any("Environment" in b for b in parts.dynamic_blocks)


@pytest.mark.asyncio
async def test_static_block_cached_across_calls(tmp_path: Path) -> None:
    """第二次 fetch 應拿 cached 靜態段(同字串)。"""
    p1 = await fetch_system_prompt_parts(cwd=tmp_path)
    p2 = await fetch_system_prompt_parts(cwd=tmp_path)
    assert p1.static_block == p2.static_block
    assert p1.static_block is p2.static_block  # cached → 同物件


@pytest.mark.asyncio
async def test_dynamic_changes_with_cwd(tmp_path: Path) -> None:
    """不同 cwd 應產生不同 env_info(動態段不 cache)。"""
    a = tmp_path / "a"
    a.mkdir()
    b = tmp_path / "b"
    b.mkdir()
    p1 = await fetch_system_prompt_parts(cwd=a)
    p2 = await fetch_system_prompt_parts(cwd=b)
    env1 = next(x for x in p1.dynamic_blocks if "Environment" in x)
    env2 = next(x for x in p2.dynamic_blocks if "Environment" in x)
    assert "/a" in env1
    assert "/b" in env2


def test_build_returns_two_element_list() -> None:
    parts = SystemPromptParts(
        static_block="STATIC",
        dynamic_blocks=["env", "memory"],
    )
    out = build_system_prompt_list(parts)
    assert len(out) == 2
    assert out[0] == "STATIC"
    assert "env" in out[1] and "memory" in out[1]


def test_build_with_empty_dynamic() -> None:
    parts = SystemPromptParts(static_block="STATIC", dynamic_blocks=[])
    out = build_system_prompt_list(parts)
    assert out == ["STATIC", ""]


@pytest.mark.asyncio
async def test_use_cache_false_recomputes(tmp_path: Path) -> None:
    """use_cache=False(對應 /clear command)→ 每次重算靜態段。"""
    p1 = await fetch_system_prompt_parts(cwd=tmp_path)
    p2 = await fetch_system_prompt_parts(cwd=tmp_path, use_cache=False)
    # 內容應一致(deterministic),但 p2 沒從 cache 走
    assert p1.static_block == p2.static_block


@pytest.mark.asyncio
async def test_instructions_md_loaded(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """寫 instructions.md → 被載入動態段。"""
    monkeypatch.setattr(
        "orion_agent.prompt.context.Path.home", lambda: tmp_path / "fakehome"
    )
    cwd = tmp_path / "proj"
    cwd.mkdir()
    (cwd / ".orion").mkdir()
    (cwd / ".orion" / "instructions.md").write_text("haiku format only", encoding="utf-8")

    parts = await fetch_system_prompt_parts(cwd=cwd)
    instructions_block = next(
        (b for b in parts.dynamic_blocks if "User instructions" in b), None,
    )
    assert instructions_block is not None
    assert "haiku" in instructions_block

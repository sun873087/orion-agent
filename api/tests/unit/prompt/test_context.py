"""prompt/context.py — git / env / instructions auto-discovery。"""

from __future__ import annotations

from pathlib import Path
from unittest.mock import patch

import pytest

from orion_agent.prompt.context import (
    find_instructions_files,
    get_env_info,
    get_git_context,
    read_instructions,
)


def test_get_env_info_basic(tmp_path: Path) -> None:
    text = get_env_info(tmp_path)
    assert "platform:" in text
    assert "cwd:" in text
    assert "date:" in text
    assert str(tmp_path) in text


@pytest.mark.asyncio
async def test_get_git_context_in_non_git_dir_returns_empty(tmp_path: Path) -> None:
    """純 tmp dir 沒 .git → git rev-parse 失敗 → 空字串。"""
    text = await get_git_context(tmp_path)
    assert text == ""


def test_find_instructions_no_files(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """沒檔回 [],不 raise。"""
    monkeypatch.setenv("HOME", str(tmp_path))
    found = find_instructions_files(tmp_path)
    assert found == []


def test_find_instructions_in_cwd(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("HOME", str(tmp_path / "fakehome"))
    instr_dir = tmp_path / ".orion"
    instr_dir.mkdir()
    instr = instr_dir / "instructions.md"
    instr.write_text("be brief", encoding="utf-8")

    found = find_instructions_files(tmp_path)
    assert len(found) == 1
    assert found[0] == instr


def test_find_instructions_global_and_cwd(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """~/.orion + cwd/.orion 兩個檔同時存在 → 都找到。"""
    fake_home = tmp_path / "fakehome"
    monkeypatch.setattr("orion_agent.prompt.context.Path.home", lambda: fake_home)
    (fake_home / ".orion").mkdir(parents=True)
    global_instr = fake_home / ".orion" / "instructions.md"
    global_instr.write_text("global rule", encoding="utf-8")

    cwd_dir = tmp_path / "proj"
    cwd_dir.mkdir()
    (cwd_dir / ".orion").mkdir()
    cwd_instr = cwd_dir / ".orion" / "instructions.md"
    cwd_instr.write_text("project rule", encoding="utf-8")

    found = find_instructions_files(cwd_dir)
    paths = [str(f) for f in found]
    assert any("fakehome" in p for p in paths)
    assert any("proj" in p for p in paths)


def test_read_instructions_concatenates(tmp_path: Path) -> None:
    a = tmp_path / "a.md"
    a.write_text("first")
    b = tmp_path / "b.md"
    b.write_text("second")
    text = read_instructions([a, b])
    assert "first" in text
    assert "second" in text


def test_read_instructions_skip_unreadable(tmp_path: Path) -> None:
    good = tmp_path / "good.md"
    good.write_text("ok", encoding="utf-8")
    bad = tmp_path / "binary.md"
    bad.write_bytes(b"\xff\xfe\x00\x01")  # invalid utf-8

    text = read_instructions([good, bad])
    assert "ok" in text


@pytest.mark.asyncio
async def test_git_context_swallows_subprocess_failure(tmp_path: Path) -> None:
    """模擬 git 不存在 → exec FileNotFoundError → 回空字串。"""
    with patch(
        "orion_agent.prompt.context.asyncio.create_subprocess_exec",
        side_effect=FileNotFoundError("git not installed"),
    ):
        text = await get_git_context(tmp_path)
        assert text == ""

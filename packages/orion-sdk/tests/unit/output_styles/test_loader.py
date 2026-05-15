"""Output styles loader + /output-style command。Phase 13。"""

from __future__ import annotations

from pathlib import Path

import pytest

from orion_cli.commands.builtin.output_style import OutputStyleCommand
from orion_sdk.output_styles import (
    find_output_style,
    list_output_style_names,
    load_output_styles_dir,
)


def _write_style(directory: Path, name: str, body: str, description: str = "") -> Path:
    directory.mkdir(parents=True, exist_ok=True)
    fm = "---\n"
    fm += f"name: {name}\n"
    if description:
        fm += f"description: {description}\n"
    fm += "---\n\n"
    p = directory / f"{name}.md"
    p.write_text(fm + body, encoding="utf-8")
    return p


def test_load_dir_basic(tmp_path: Path) -> None:
    _write_style(tmp_path, "concise", "Be terse and use bullet points.")
    styles = load_output_styles_dir(tmp_path)
    assert len(styles) == 1
    assert styles[0].name == "concise"
    assert "bullet" in styles[0].prompt


def test_load_dir_missing(tmp_path: Path) -> None:
    assert load_output_styles_dir(tmp_path / "nope") == []


def test_load_dir_skips_empty_body(tmp_path: Path) -> None:
    p = tmp_path / "empty.md"
    p.write_text("---\nname: empty\n---\n", encoding="utf-8")
    styles = load_output_styles_dir(tmp_path)
    assert styles == []


def test_load_all_merges_dirs(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    home_dir = tmp_path / "home" / "output-styles"
    project_dir = tmp_path / "proj" / ".orion" / "output-styles"
    _write_style(home_dir, "verbose", "expand explanations")
    _write_style(project_dir, "code-review", "focus on diffs")

    monkeypatch.setenv("ORION_HOME", str(tmp_path / "home"))
    monkeypatch.chdir(tmp_path / "proj")

    names = list_output_style_names()
    assert "verbose" in names
    assert "code-review" in names


def test_load_all_project_overrides_home(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    """同 name 在 home 與 project 都有 → project 贏。"""
    home_dir = tmp_path / "home" / "output-styles"
    project_dir = tmp_path / "proj" / ".orion" / "output-styles"
    _write_style(home_dir, "shared", "home version")
    _write_style(project_dir, "shared", "project version")

    monkeypatch.setenv("ORION_HOME", str(tmp_path / "home"))
    monkeypatch.chdir(tmp_path / "proj")

    found = find_output_style("shared")
    assert found is not None
    assert "project version" in found.prompt


def test_find_returns_none_for_unknown(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("ORION_HOME", str(tmp_path / "home"))
    monkeypatch.chdir(tmp_path)
    assert find_output_style("nope") is None


def test_find_empty_name_returns_none() -> None:
    assert find_output_style("") is None


@pytest.mark.asyncio
async def test_command_list_when_empty(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("ORION_HOME", str(tmp_path / "home"))
    monkeypatch.chdir(tmp_path)

    class FakeConv:
        output_style = None

    cmd = OutputStyleCommand()
    res = await cmd.execute("", None, FakeConv())
    assert res.text is not None
    assert "No output styles" in res.text


@pytest.mark.asyncio
async def test_command_switch(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    home = tmp_path / "home"
    _write_style(home / "output-styles", "concise", "be brief")
    monkeypatch.setenv("ORION_HOME", str(home))
    monkeypatch.chdir(tmp_path)

    class FakeConv:
        output_style: str | None = None

    conv = FakeConv()
    cmd = OutputStyleCommand()
    res = await cmd.execute("concise", None, conv)
    assert "→ concise" in (res.text or "")
    assert conv.output_style == "concise"


@pytest.mark.asyncio
async def test_command_unknown(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("ORION_HOME", str(tmp_path / "home"))
    monkeypatch.chdir(tmp_path)

    class FakeConv:
        output_style = None

    res = await OutputStyleCommand().execute("nope", None, FakeConv())
    assert "not found" in (res.text or "").lower()


@pytest.mark.asyncio
async def test_command_clear(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("ORION_HOME", str(tmp_path / "home"))
    monkeypatch.chdir(tmp_path)

    class FakeConv:
        output_style: str | None = "concise"

    conv = FakeConv()
    res = await OutputStyleCommand().execute("none", None, conv)
    assert conv.output_style is None
    assert "(none)" in (res.text or "")

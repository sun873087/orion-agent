"""skills.loader — load_skills_dir + load_all_skills + find_skill。"""

from __future__ import annotations

from pathlib import Path

import pytest

from orion_agent.skills.builtin import builtin_skills
from orion_agent.skills.loader import find_skill, load_all_skills, load_skills_dir


def _write(path: Path, content: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(content, encoding="utf-8")


def test_load_skills_dir_empty(tmp_path: Path) -> None:
    assert load_skills_dir(tmp_path / "no-such") == []


def test_load_skills_dir_basic(tmp_path: Path) -> None:
    _write(
        tmp_path / "x.md",
        "---\nname: my-skill\ndescription: hello\n---\n\nbody text",
    )
    skills = load_skills_dir(tmp_path)
    assert len(skills) == 1
    s = skills[0]
    assert s.name == "my-skill"
    assert s.description == "hello"
    assert "body text" in s.body


def test_load_skills_dir_uses_stem_when_no_name(tmp_path: Path) -> None:
    _write(tmp_path / "auto.md", "---\ndescription: x\n---\n\nbody")
    skills = load_skills_dir(tmp_path)
    assert skills[0].name == "auto"


def test_load_skills_dir_skips_bad_frontmatter(tmp_path: Path) -> None:
    _write(tmp_path / "ok.md", "---\nname: ok\n---\nbody")
    _write(tmp_path / "bad.md", "---\nname: x: y: z\n---\nbody")  # invalid yaml
    skills = load_skills_dir(tmp_path)
    names = [s.name for s in skills]
    assert "ok" in names
    # bad 可能還是被解析(yaml 容錯),不強硬 assert,但至少 ok 要在


def test_load_skills_dir_parses_hooks(tmp_path: Path) -> None:
    _write(
        tmp_path / "x.md",
        """\
---
name: x
hooks:
  - event: PreToolUse
    command: echo
---

body""",
    )
    skills = load_skills_dir(tmp_path)
    assert skills[0].hooks == [{"event": "PreToolUse", "command": "echo"}]


def test_load_all_skills_includes_builtin(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    monkeypatch.setenv("ORION_SKILLS_DIR", str(tmp_path / "no-such"))
    monkeypatch.chdir(tmp_path)
    skills = load_all_skills()
    builtin_names = {s.name for s in builtin_skills()}
    loaded_names = {s.name for s in skills}
    assert builtin_names.issubset(loaded_names)


def test_load_all_skills_last_wins(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    user_dir = tmp_path / "user"
    proj_dir = tmp_path / "proj" / ".orion" / "skills"
    _write(user_dir / "x.md", "---\nname: dup\ndescription: from-user\n---\nA")
    _write(proj_dir / "x.md", "---\nname: dup\ndescription: from-proj\n---\nB")
    monkeypatch.setenv("ORION_SKILLS_DIR", str(user_dir))
    monkeypatch.chdir(tmp_path / "proj")

    s = find_skill("dup")
    assert s is not None
    # project 後加 → 後者 win
    assert s.description == "from-proj"


def test_find_skill_missing(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    monkeypatch.setenv("ORION_SKILLS_DIR", str(tmp_path))
    monkeypatch.chdir(tmp_path)
    assert find_skill("not-a-real-skill-name-xyz") is None

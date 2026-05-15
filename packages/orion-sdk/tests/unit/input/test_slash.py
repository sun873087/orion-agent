"""is_slash_command + parse_slash 邊角。"""

from __future__ import annotations

import pytest

from orion_cli.input.slash import is_slash_command, parse_slash


def test_basic() -> None:
    assert is_slash_command("/help")
    assert is_slash_command("/model claude-haiku-4-5")
    assert is_slash_command("/cmd-with-dash arg1 arg2")


def test_double_slash_is_path_not_command() -> None:
    assert not is_slash_command("//tmp/file")
    assert not is_slash_command("//")


def test_empty_or_lone_slash() -> None:
    assert not is_slash_command("")
    assert not is_slash_command("/")


def test_command_must_start_with_letter() -> None:
    assert not is_slash_command("/123abc")  # 數字開頭
    assert not is_slash_command("/-abc")  # 連字開頭
    assert is_slash_command("/abc-123")


def test_no_slash_prefix() -> None:
    assert not is_slash_command("help")
    assert not is_slash_command(" /help")  # 前面空白


def test_parse_simple() -> None:
    assert parse_slash("/help") == ("help", "")
    assert parse_slash("/model claude-haiku-4-5") == ("model", "claude-haiku-4-5")


def test_parse_multi_word_args() -> None:
    assert parse_slash("/init analyze this codebase") == (
        "init",
        "analyze this codebase",
    )


def test_parse_invalid_raises() -> None:
    with pytest.raises(ValueError):
        parse_slash("not a command")


def test_parse_strips_whitespace() -> None:
    assert parse_slash("/help   ") == ("help", "")
    assert parse_slash("/model  haiku  ") == ("model", "haiku")

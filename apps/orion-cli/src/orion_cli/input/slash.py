"""Slash command 解析。對應 TS processSlashCommand.tsx。"""

from __future__ import annotations

import re

# 命令名只允許字母 / 數字 / 連字 / 底線,後接空白 + 任意 args
_SLASH_PATTERN = re.compile(r"^/([A-Za-z][\w-]*)\s*(.*)$", re.DOTALL)


def is_slash_command(text: str) -> bool:
    """判斷文字是否 slash 命令。

    Rules:
    - 必 `/` 開頭(不是 `//` 路徑)
    - 命令名只允許 `[A-Za-z][\\w-]*`
    - 純 `/` 不算
    """
    if not text:
        return False
    if text.startswith("//"):
        return False
    if len(text) < 2:
        return False
    return _SLASH_PATTERN.match(text) is not None


def parse_slash(text: str) -> tuple[str, str]:
    """解析 `/cmd args` → `(cmd_name, args_stripped)`。

    Raises:
        ValueError: 不是 slash 命令格式。
    """
    m = _SLASH_PATTERN.match(text)
    if m is None:
        raise ValueError(f"not a slash command: {text!r}")
    return m.group(1), m.group(2).strip()

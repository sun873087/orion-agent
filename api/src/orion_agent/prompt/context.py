"""動態 context 蒐集 — git status、env info、user instructions。

對應 spec § 5.3 context.py。

每段失敗都靜默 — 沒 git 不算錯,沒 instructions.md 不算錯,sandbox / CI 環境
無 platform 也不算錯。整段最多回空字串,不 raise。
"""

from __future__ import annotations

import asyncio
import os
import platform
import time
from datetime import UTC, datetime
from pathlib import Path

import anyio

_INSTRUCTIONS_FILE = "instructions.md"
_INSTRUCTIONS_MAX_BYTES = 100 * 1024
_GIT_LOG_LINES = 5
_GIT_TIMEOUT_S = 3.0
_GIT_CONTEXT_TTL_S = 10.0
_git_context_cache: dict[str, tuple[float, str]] = {}


async def get_git_context(cwd: Path | None = None) -> str:
    """回傳 git 分支 + 最近 N 個 commit 摘要。

    沒 git / 不在 repo / git 卡住 → 回空字串。
    Per-cwd TTL cache(10s)— 避免每 turn spawn 兩個 git 子進程,
    workspace dir 本身不是 git repo 時尤其值得快取(每 turn ~50–200ms 沒幫助)。
    """
    cwd = cwd or Path.cwd()
    key = str(cwd)
    now = time.monotonic()
    cached = _git_context_cache.get(key)
    if cached is not None and now - cached[0] < _GIT_CONTEXT_TTL_S:
        return cached[1]

    try:
        with anyio.move_on_after(_GIT_TIMEOUT_S):
            branch = await _run_git(["rev-parse", "--abbrev-ref", "HEAD"], cwd)
            log = await _run_git(
                ["log", f"-{_GIT_LOG_LINES}", "--oneline"], cwd,
            )
    except Exception:  # noqa: BLE001
        _git_context_cache[key] = (now, "")
        return ""

    if not branch:
        _git_context_cache[key] = (now, "")
        return ""

    parts = [f"branch: {branch.strip()}"]
    if log.strip():
        parts.append("recent commits:")
        for line in log.strip().splitlines()[:_GIT_LOG_LINES]:
            parts.append(f"  {line}")
    result = "\n".join(parts)
    _git_context_cache[key] = (now, result)
    return result


async def _run_git(args: list[str], cwd: Path) -> str:
    """run git subcommand,失敗回空字串。"""
    proc = await asyncio.create_subprocess_exec(
        "git",
        *args,
        cwd=str(cwd),
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.DEVNULL,
    )
    stdout, _ = await proc.communicate()
    if proc.returncode != 0:
        return ""
    return stdout.decode("utf-8", errors="replace")


def get_env_info(cwd: Path | None = None) -> str:
    """platform / cwd / today date — 同步,沒 I/O 風險。"""
    cwd = cwd or Path.cwd()
    today = datetime.now(UTC).strftime("%Y-%m-%d")

    return (
        f"platform: {platform.system()} ({platform.release()})\n"
        f"cwd: {cwd}\n"
        f"date: {today} (UTC)"
    )


def find_instructions_files(cwd: Path | None = None) -> list[Path]:
    """搜尋 instructions.md 檔。順序:

    1. ~/.orion/instructions.md(global)
    2. <cwd>/.orion/instructions.md(per-project)

    回找到的 Path list,失敗回 []。
    """
    cwd = cwd or Path.cwd()
    candidates = [
        Path.home() / ".orion" / _INSTRUCTIONS_FILE,
        cwd / ".orion" / _INSTRUCTIONS_FILE,
    ]
    found: list[Path] = []
    for p in candidates:
        try:
            if p.is_file() and p.stat().st_size <= _INSTRUCTIONS_MAX_BYTES:
                found.append(p)
        except OSError:
            continue
    return found


def read_instructions(files: list[Path]) -> str:
    """把所有 instructions.md 內容串接。失敗檔跳過。"""
    chunks: list[str] = []
    for p in files:
        try:
            text = p.read_text(encoding="utf-8")
        except (OSError, UnicodeDecodeError):
            continue
        chunks.append(f"# From {p}\n\n{text.strip()}")
    return "\n\n---\n\n".join(chunks)


# 公開 helper,測試 + assembler 用
__all__ = [
    "find_instructions_files",
    "get_env_info",
    "get_git_context",
    "read_instructions",
]


# 維持 import 連結,避免 lint
_ = os  # for env access in future

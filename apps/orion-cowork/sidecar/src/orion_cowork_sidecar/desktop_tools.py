"""Cowork 專屬 tools — desktop 控制(只在本機桌機 app 內,不放 SDK builtin
因為 chat-api server 不該開 user 的瀏覽器)。

OpenUrlTool:在 user 預設瀏覽器開網址 — 跨平台 via webbrowser stdlib。
OpenPathTool:在系統檔管打開檔案 / 資料夾 / 用預設 app 開(macOS open, Win
              start, Linux xdg-open)。
"""

from __future__ import annotations

import os
import subprocess
import sys
import webbrowser
from collections.abc import AsyncIterator
from pathlib import Path

from pydantic import Field

from orion_sdk.core.state import AgentContext
from orion_sdk.core.tool import ErrorEvent, TextEvent, ToolEvent, ToolInput


class OpenUrlInput(ToolInput):
    url: str = Field(
        ...,
        description="HTTP/HTTPS URL to open in the user's default web browser.",
    )


class OpenUrlTool:
    name = "open_url"
    description = (
        "Open a URL in the user's default web browser. Use this whenever the user "
        "asks you to open a website, navigate to a page, search visually, or look "
        "something up in the browser. This launches the browser window on the user's "
        "local machine — Cowork is a desktop app, you have permission to do this."
    )
    input_schema = OpenUrlInput

    async def call(
        self,
        input: OpenUrlInput,
        ctx: AgentContext,  # noqa: ARG002
    ) -> AsyncIterator[ToolEvent]:
        url = input.url.strip()
        if not (url.startswith("http://") or url.startswith("https://")):
            yield ErrorEvent(message=f"URL must start with http:// or https://: {url!r}")
            return
        try:
            ok = webbrowser.open(url, new=2)
        except Exception as e:  # noqa: BLE001
            yield ErrorEvent(message=f"failed to open browser: {type(e).__name__}: {e}")
            return
        if not ok:
            yield ErrorEvent(message=f"webbrowser.open returned False for {url}")
            return
        yield TextEvent(text=f"Opened {url} in default browser.")

    def is_concurrency_safe(self, input: OpenUrlInput) -> bool:  # noqa: ARG002
        return True

    def is_read_only(self, input: OpenUrlInput) -> bool:  # noqa: ARG002
        return False  # 有 side effect(開窗)

    def max_result_size_chars(self) -> int | float:
        return 1024


class OpenPathInput(ToolInput):
    path: str = Field(
        ...,
        description="Absolute path of a file or folder to open with the OS default app.",
    )


class OpenPathTool:
    name = "open_path"
    description = (
        "Open a local file or folder with the OS default application. "
        "macOS uses `open`, Windows uses `start`, Linux uses `xdg-open`. "
        "Use when the user asks you to open / reveal / show a file or folder."
    )
    input_schema = OpenPathInput

    async def call(
        self,
        input: OpenPathInput,
        ctx: AgentContext,  # noqa: ARG002
    ) -> AsyncIterator[ToolEvent]:
        path_str = input.path.strip()
        path = Path(path_str).expanduser()
        if not path.exists():
            yield ErrorEvent(message=f"path does not exist: {path}")
            return
        try:
            if sys.platform == "darwin":
                subprocess.run(["open", str(path)], check=True)
            elif sys.platform == "win32":
                os.startfile(str(path))  # type: ignore[attr-defined]
            else:
                subprocess.run(["xdg-open", str(path)], check=True)
        except Exception as e:  # noqa: BLE001
            yield ErrorEvent(message=f"failed to open path: {type(e).__name__}: {e}")
            return
        yield TextEvent(text=f"Opened {path}.")

    def is_concurrency_safe(self, input: OpenPathInput) -> bool:  # noqa: ARG002
        return True

    def is_read_only(self, input: OpenPathInput) -> bool:  # noqa: ARG002
        return False

    def max_result_size_chars(self) -> int | float:
        return 1024

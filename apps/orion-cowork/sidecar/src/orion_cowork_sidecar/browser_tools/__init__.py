"""Browser-use tools — 透過 system Chrome(Playwright `channel='chrome'`)做
互動式網頁操作。

**Cowork-only**:Phase 31-H 後從 orion-sdk 搬到 Cowork sidecar,因為只 Cowork
host 用 — SDK 不再背 playwright dep。CLI / chat-api 都不會註冊這組工具。

啟用條件:
- Cowork sidecar `pyproject.toml` 已 list `playwright>=1.40`
- system 安裝 Google Chrome(不下載 playwright 自帶 chromium bundle)

Tools 全 headful — user 看得到 AI 在自己的 Chrome 視窗操作。每個 cowork
session 一個 BrowserSession(共用 Browser + Context + Page),lazy launch。
"""
from __future__ import annotations

import shutil
from pathlib import Path
from typing import Any


def is_browser_available() -> bool:
    """playwright Python client 有裝且 system 有 Chrome 可用。"""
    try:
        import playwright  # noqa: F401
    except ImportError:
        return False
    return find_chrome_executable() is not None


def find_chrome_executable() -> Path | None:
    """嘗試找 OS 上的 Google Chrome / Chromium 執行檔。回 None = 沒裝。"""
    # 走 PATH 一遍
    for name in ("google-chrome", "google-chrome-stable", "chrome", "chromium", "chromium-browser"):
        p = shutil.which(name)
        if p:
            return Path(p)
    # 各 OS 標準路徑
    candidates = [
        # macOS
        "/Applications/Google Chrome.app/Contents/MacOS/Google Chrome",
        "/Applications/Chromium.app/Contents/MacOS/Chromium",
        # Linux
        "/usr/bin/google-chrome",
        "/usr/bin/google-chrome-stable",
        "/usr/bin/chromium",
        "/usr/bin/chromium-browser",
        "/snap/bin/chromium",
        # Windows
        "C:/Program Files/Google/Chrome/Application/chrome.exe",
        "C:/Program Files (x86)/Google/Chrome/Application/chrome.exe",
    ]
    for c in candidates:
        p = Path(c)
        if p.exists():
            return p
    return None


from orion_cowork_sidecar.browser_tools.click import BrowserClickTool
from orion_cowork_sidecar.browser_tools.navigate import (
    BrowserBackTool,
    BrowserForwardTool,
    BrowserNavigateTool,
)
from orion_cowork_sidecar.browser_tools.read import BrowserReadPageTool
from orion_cowork_sidecar.browser_tools.screenshot import BrowserScreenshotTool
from orion_cowork_sidecar.browser_tools.scroll import BrowserScrollTool
from orion_cowork_sidecar.browser_tools.session import (
    BrowserSession,
    close_all_browser_sessions,
    get_browser_session,
)
from orion_cowork_sidecar.browser_tools.session_close import BrowserCloseTool
from orion_cowork_sidecar.browser_tools.type_tool import BrowserTypeTool
from orion_cowork_sidecar.browser_tools.wait import BrowserWaitForTool


def build_browser_tools() -> list[object]:
    """所有 browser tools 一次回。Caller(handlers.py)再 extend 進 extra_tools。"""
    return [
        BrowserNavigateTool(),
        BrowserScreenshotTool(),
        BrowserReadPageTool(),
        BrowserClickTool(),
        BrowserTypeTool(),
        BrowserScrollTool(),
        BrowserWaitForTool(),
        BrowserBackTool(),
        BrowserForwardTool(),
        BrowserCloseTool(),
    ]


def browser_tool_group() -> dict[str, Any]:
    """Browser group metadata,Cowork sidecar `tools.list_builtin` 注 SDK
    `list_builtin_tool_groups(extra_groups=...)`。"""
    return {
        "group": "Browser",
        "tools": [{"name": t.name, "description": t.description} for t in build_browser_tools()],  # type: ignore[attr-defined]
    }


__all__ = [
    "is_browser_available",
    "find_chrome_executable",
    "build_browser_tools",
    "browser_tool_group",
    "BrowserSession",
    "get_browser_session",
    "close_all_browser_sessions",
]

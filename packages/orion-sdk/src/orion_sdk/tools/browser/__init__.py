"""Browser-use tools — 透過 system Chrome(Playwright `channel='chrome'`)做
互動式網頁操作。

啟用條件:
- pip install 'orion-sdk[browser]'(playwright Python client)
- system 安裝 Google Chrome(不下載 playwright 自帶 chromium bundle)

Tools 全 headful — user 看得到 AI 在自己的 Chrome 視窗操作。每個 cowork
session 一個 BrowserSession(共用 Browser + Context + Page),lazy launch。
"""
from __future__ import annotations

import shutil
from pathlib import Path


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


from orion_sdk.tools.browser.click import BrowserClickTool
from orion_sdk.tools.browser.navigate import BrowserBackTool, BrowserForwardTool, BrowserNavigateTool
from orion_sdk.tools.browser.read import BrowserReadPageTool
from orion_sdk.tools.browser.screenshot import BrowserScreenshotTool
from orion_sdk.tools.browser.scroll import BrowserScrollTool
from orion_sdk.tools.browser.session import (
    BrowserSession,
    close_all_browser_sessions,
    get_browser_session,
)
from orion_sdk.tools.browser.session_close import BrowserCloseTool
from orion_sdk.tools.browser.type_tool import BrowserTypeTool
from orion_sdk.tools.browser.wait import BrowserWaitForTool


def build_browser_tools() -> list[object]:
    """所有 browser tools 一次回。Caller(builtin_set.py)再 extend 進 conv.tools。"""
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


__all__ = [
    "is_browser_available",
    "find_chrome_executable",
    "build_browser_tools",
    "BrowserSession",
    "get_browser_session",
    "close_all_browser_sessions",
]

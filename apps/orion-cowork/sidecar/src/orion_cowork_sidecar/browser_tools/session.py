"""BrowserSession — playwright Chrome 實例管理。

Lifecycle:
- Lazy launch:第一次有 tool 呼叫該 session_id 才開 Chrome
- Per-session 隔離:dict[session_id, BrowserSession],跨 tool call 共用同個 page
- 啟動參數:`channel='chrome'`(用 OS 已裝的 Chrome,不下載 chromium bundle)
- `headless=False`(user 看得到視窗)
- Sidecar shutdown 時 close_all_browser_sessions() 全關
"""
from __future__ import annotations

import asyncio
import logging
from typing import TYPE_CHECKING
from uuid import UUID

if TYPE_CHECKING:
    from playwright.async_api import Browser, BrowserContext, Page, Playwright

_log = logging.getLogger(__name__)


class BrowserSession:
    """一個 Chrome instance + BrowserContext + 當前 active page。

    多 page 暫不支援(第一版),所有操作對 self.page。
    """

    def __init__(
        self,
        playwright: "Playwright",
        browser: "Browser",
        context: "BrowserContext",
        page: "Page",
    ) -> None:
        self._playwright = playwright
        self.browser = browser
        self.context = context
        self.page = page

    async def close(self) -> None:
        try:
            await self.context.close()
        except Exception:  # noqa: BLE001
            pass
        try:
            await self.browser.close()
        except Exception:  # noqa: BLE001
            pass
        try:
            await self._playwright.stop()
        except Exception:  # noqa: BLE001
            pass


_sessions: dict[UUID, BrowserSession] = {}
_locks: dict[UUID, asyncio.Lock] = {}


def _get_lock(session_id: UUID) -> asyncio.Lock:
    if session_id not in _locks:
        _locks[session_id] = asyncio.Lock()
    return _locks[session_id]


async def get_browser_session(session_id: UUID) -> BrowserSession:
    """取得 session 的 BrowserSession,沒就 lazy launch system Chrome。"""
    async with _get_lock(session_id):
        existing = _sessions.get(session_id)
        if existing is not None:
            return existing

        # Lazy import — 避免 playwright 沒裝時整個 sdk 載不起來
        from playwright.async_api import async_playwright

        p = await async_playwright().start()
        try:
            browser = await p.chromium.launch(
                channel="chrome",  # 用 system Chrome,不下載 chromium bundle
                headless=False,  # User 看得到視窗
                args=["--disable-blink-features=AutomationControlled"],
            )
        except Exception as e:  # noqa: BLE001
            await p.stop()
            raise RuntimeError(
                f"無法啟動 system Chrome(channel='chrome'):{e}。"
                "請確認系統已安裝 Google Chrome,或改用 `playwright install chromium`。"
            ) from e

        context = await browser.new_context(
            viewport={"width": 1280, "height": 800},
        )
        page = await context.new_page()
        sess = BrowserSession(p, browser, context, page)
        _sessions[session_id] = sess
        _log.info("browser session %s launched", session_id)
        return sess


async def close_browser_session(session_id: UUID) -> bool:
    """關掉指定 session 的 browser。回 True 表示有東西關;False = 本來就沒開。"""
    async with _get_lock(session_id):
        sess = _sessions.pop(session_id, None)
        if sess is None:
            return False
    await sess.close()
    _log.info("browser session %s closed", session_id)
    return True


async def close_all_browser_sessions() -> None:
    """Sidecar shutdown 時呼,把所有開著的 Chrome 全關。"""
    for sid in list(_sessions.keys()):
        await close_browser_session(sid)

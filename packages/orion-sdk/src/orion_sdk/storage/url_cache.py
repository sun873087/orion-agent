"""WebFetchTool URL cache(per-session in-memory)。

模型多輪 reasoning 常反覆 fetch 同 URL — 每次都打網既慢又燒 quota。
本模組提供短 TTL in-memory cache(預設 5 分鐘),配 LRU 上限避免無界長。

設計:
- 每個 AgentContext 一個 UrlCache(ctx.url_cache 持有,WebFetchTool lazy init)
- 存 raw response(body bytes + content_type),cache hit 跑相同 HTML 處理路徑
- TTL `ORION_WEBFETCH_TTL_SECONDS`(預設 300)
- LRU 上限預設 100;OrderedDict.move_to_end 維護 recency

不做:跨 session 共享、disk 持久化(spec 列為可選,複用不必要)。
"""

from __future__ import annotations

import os
import time
from collections import OrderedDict
from dataclasses import dataclass

_DEFAULT_TTL_SECONDS = 300.0
_DEFAULT_MAX_ENTRIES = 100


@dataclass(frozen=True)
class CachedResponse:
    """已 cache 的 fetch 回應(原始 body + content_type)。"""

    body: bytes
    content_type: str
    fetched_at: float
    """time.monotonic() 寫入時刻。TTL 用。"""


def _ttl_from_env() -> float:
    raw = os.environ.get("ORION_WEBFETCH_TTL_SECONDS")
    if raw:
        try:
            v = float(raw)
            if v >= 0:
                return v
        except ValueError:
            pass
    return _DEFAULT_TTL_SECONDS


class UrlCache:
    """Per-session URL → CachedResponse 對映,含 TTL 與 LRU。"""

    def __init__(
        self,
        ttl_seconds: float | None = None,
        max_entries: int = _DEFAULT_MAX_ENTRIES,
    ) -> None:
        self.ttl_seconds = ttl_seconds if ttl_seconds is not None else _ttl_from_env()
        self.max_entries = max_entries
        self._store: OrderedDict[str, CachedResponse] = OrderedDict()

    def get(self, url: str) -> CachedResponse | None:
        """命中且未過期 → 回 CachedResponse;否則 None(過期 entry 同時清掉)。"""
        entry = self._store.get(url)
        if entry is None:
            return None
        if time.monotonic() - entry.fetched_at > self.ttl_seconds:
            del self._store[url]
            return None
        # LRU:每次 get 後 bump 到尾端
        self._store.move_to_end(url)
        return entry

    def put(self, url: str, body: bytes, content_type: str) -> None:
        """寫入或覆蓋。超 max_entries 從 LRU 端 evict。"""
        if url in self._store:
            del self._store[url]
        self._store[url] = CachedResponse(
            body=body,
            content_type=content_type,
            fetched_at=time.monotonic(),
        )
        while len(self._store) > self.max_entries:
            self._store.popitem(last=False)

    def __len__(self) -> int:
        return len(self._store)

    def clear(self) -> None:
        self._store.clear()


def get_or_create_url_cache(ctx_obj: object) -> UrlCache:
    """取 ctx.url_cache,若 None 則 lazy 建立並掛回。

    參數型別用 `object` 避免循環 import(AgentContext 在 core/state.py)。
    Caller(WebFetchTool)保證傳入是 AgentContext。
    """
    existing = getattr(ctx_obj, "url_cache", None)
    if isinstance(existing, UrlCache):
        return existing
    cache = UrlCache()
    # ctx 是 dataclass,欄位已存在;直接 setattr 即可
    setattr(ctx_obj, "url_cache", cache) # noqa: B010
    return cache

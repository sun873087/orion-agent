# Phase 18 — WebFetchTool URL caching 完工記錄

**完成日期**:2026-05-12
**Plan doc**:`docs/phases/18-webfetch-cache.md`(原 `docs/phases/plan/18-...`,完工後搬出)
**狀態**:✅ **871 unit tests passed, 2 skipped**(本 phase 新增 **9 tests**),mypy --strict 3 修改檔 0 issues。

模型多輪 reasoning 反覆 fetch 同 URL 是常見場景。Phase 18 加 per-session in-memory cache(預設 5 min TTL + LRU 100 entries),命中時跳過 HTTP 直接送處理過的內容並標 `[cached]`。

---

## 交付清單

### 新增模組

```
src/orion_agent/storage/url_cache.py            [全新]
├── CachedResponse                              raw body + content_type + fetched_at
├── UrlCache                                    OrderedDict-backed,TTL + LRU
├── _ttl_from_env()                             ORION_WEBFETCH_TTL_SECONDS(預設 300)
└── get_or_create_url_cache(ctx)                lazy init,首次 WebFetch 時掛到 ctx.url_cache
```

### Tests(新增 1 檔,共 9 案例)

```
tests/unit/tools/test_web_fetch_cache.py        [全新]
├── test_second_fetch_does_not_hit_network      重複 fetch → call_count 仍 1、輸出含 [cached]
├── test_different_urls_each_hit_network        不同 URL 各自打網,A 第二次走 cache
├── test_cache_is_per_session                   兩個 AgentContext 不共享 cache
├── test_ttl_expiry                             monkeypatch time.monotonic → 過期 entry 重打
├── test_lru_eviction                           max_entries=3,第 4 個 put 把最舊 entry 踢
├── test_lru_recency_on_get                     get 觸發 move_to_end,被訪問的 entry 不會被先踢
├── test_ttl_env_override                       ORION_WEBFETCH_TTL_SECONDS=42 → ttl_seconds=42
├── test_ttl_env_invalid_falls_back             ORION_WEBFETCH_TTL_SECONDS="garbage" → 300
└── test_get_or_create_idempotent               同 ctx 多次呼叫回同一物件
```

### 修改檔

| 檔 | 變更 |
|---|---|
| `core/state.py` | AgentContext 加 `url_cache: object \| None = None`(Phase 18 marker) |
| `tools/web/fetch.py` | call() 先查 cache,hit 跳過 HTTP;raw body/content_type 處理路徑抽 `_render` 共用 |

---

## 設計決策

### 1. 存 raw body + content_type,不存處理過的字串
快取單元是 `(body: bytes, content_type: str)`,不是輸出的 `TextEvent.text`。理由:
- 若未來改進 HTML 處理(spec 提的 readability 抽精華),不需重抓網頁
- `[cached]` 標籤直接由 `_render(..., cached=True)` 在 title 行加,流程乾淨

### 2. Per-session,不做 global
Spec 設計決策一致。global cache 要處理 user-isolation(不同 user 同 URL 內容不同 — 例如登入後頁面 / per-region content),invalidation 邏輯複雜。per-session 隨 AgentContext lifecycle 自然清。

### 3. Lazy init by tool,不在 AgentContext 預先建
AgentContext 是 dataclass,如果直接給 `field(default_factory=UrlCache)`,每個測試的空 ctx 都會跑 UrlCache 建構;對沒用到 WebFetch 的測試是浪費。改用 `get_or_create_url_cache(ctx)` lazy attach。

### 4. OrderedDict 同時做 TTL 與 LRU
`get()` 先檢查 `fetched_at` 對比 monotonic 過期就 `del` + 回 None;沒過期就 `move_to_end(url)` 提到 MRU。`put()` 進來新 entry 後 while `len > max_entries`: `popitem(last=False)` 從 LRU 端踢。所有操作 O(1) amortized。

### 5. 不做 disk 持久化(spec 列為可選)
Spec § 2 把 disk 寫到 `~/.orion/sessions/<id>/url-cache/` 列為「可選 — 讓 resume 也命中 cache」。實作評估:
- 模型在 single session 內反覆 fetch 是 95% 場景
- resume 的 session 通常重新規劃,fetch 模式會變
- disk IO + content_type 編碼處理 + LRU 上限與 disk 配額對齊,複雜度跳級

留 TODO,未來真有 cross-session 需求(例如離線復現)再加。

### 6. TTL 用 `time.monotonic()` 不用 wall clock
`time.time()` 會被系統時間調整影響(NTP / 手動改 / 跨時區)。`monotonic` 只前進不倒退,適合 TTL 計時。代價是測試 monkeypatch 要 patch `time.monotonic` 而非 `time.time`。

### 7. `get_or_create_url_cache` 參數型別用 `object` 不用 `AgentContext`
`url_cache.py` 在 `storage/` 層,`AgentContext` 在 `core/state.py`。直接 type-hint AgentContext 會形成 storage → core 的反向依賴。`object` + `getattr` 保持單向相依(`core` 不必 import `storage`)。

### 8. cache miss 才 `cache.put`;HTTP error / abort 都不存
plan 只說「打 HTTP 前查 cache」,沒明說 error 行為。實作選擇:`resp.status_code >= 400` 或 abort 都直接 yield ErrorEvent 並 return,**不**進 cache。這樣下次同 URL 還會重打(很可能是 transient error,二次 fetch 該再試)。

---

## REST API 變更

無。WebFetch 是 internal tool,輸出格式只新增 title 行的 `[cached]` 標籤(模型 prompt 文字)。

---

## 環境變數

| 變數 | 預設 | 說明 |
|---|---|---|
| `ORION_WEBFETCH_TTL_SECONDS` | `300`(5 分) | UrlCache entry TTL 秒數;`0` 表示永遠新鮮(不做 TTL 失效);非數字 fallback 預設 |

`max_entries` 目前 hard-code 100,理由:per-session 100 個不同 URL 已遠超實務上限,加 env 反而徒增配置面;真有需要再開。

---

## Verification

```bash
cd orion-agent/api/

# 新測試集
.venv/bin/python -m pytest tests/unit/tools/test_web_fetch_cache.py -xvs
# → 9 passed

# 全套不退步
.venv/bin/python -m pytest tests/unit/
# → 871 passed, 2 skipped(+9 vs Phase 16 完工時的 862)

# typecheck 修改檔
.venv/bin/python -m mypy \
    src/orion_agent/storage/url_cache.py \
    src/orion_agent/tools/web/fetch.py \
    src/orion_agent/core/state.py
# → Success: no issues found in 3 source files
```

### 手動驗證

```bash
# 設短 TTL,連續兩次 fetch 同 URL 看模型輸出含 [cached]
ORION_WEBFETCH_TTL_SECONDS=600 .venv/bin/orion run --provider anthropic \
    "fetch https://example.com twice and tell me what you see each time"

# 預期:第一次回 "# Example Domain ..."
# 第二次回 "# Example Domain [cached] ..."(同 ctx 共享 cache)
```

---

## Tests 摘要

| Suite | 數量 | 說明 |
|---|---|---|
| Phase 0–16 既有 | 862 | 全綠不動 |
| **Phase 18 url_cache 行為** | 5 | network call_count / different URLs / per-session / TTL / lru eviction & recency |
| **Phase 18 env 配置** | 2 | TTL env override / invalid fallback |
| **Phase 18 helper** | 1 | get_or_create 冪等 |
| **既有 WebFetch tests** | 3 | 不退步:fetch_html / invalid scheme / http error |
| **總計** | **871 passed / 2 skipped** | mypy 修改檔 0 issues |

---

## 風險與已緩解

| 風險 | 緩解 |
|---|---|
| 同 URL 內容變動但 cache 未過期 → 模型看到舊資料 | TTL 預設 5 分;改進方向(未做):respect HTTP `Cache-Control` / `ETag` |
| LRU 上限太低,熱門 URL 反覆 fetch 不命中 | max_entries=100,常見 conversation 規模綽綽有餘;真不夠用再開 env |
| 不同 user(共享 backend)同 ctx 看到同 URL 結果 | per-session 隔離,每個 AgentContext 一份 cache(session_id 對應) |
| cache miss path 把 4xx/5xx 也存進 cache | 只在 `resp.status_code < 400` 才 `cache.put`(設計決策 #8) |
| disk persistence 未做 → resume 沒命中 cache | 可接受(設計決策 #5);若日後真有跨 session 重抓需求再加 disk layer |
| time.monotonic patch 在不同 platform 行為差異 | TTL test 用 monkeypatch 推進 monotonic 而非 sleep,跨 platform 穩定 |

---

## 內部對應 plan 的差異

| Plan 章節 | 差異 | 為何 |
|---|---|---|
| § 2 第 4 條 disk persistence | **不做** | spec 自述為可選;cross-session 重抓需求未驗證,複雜度跳級(設計決策 #5)|
| § 5 「`storage/paths.py` 加 `url_cache_dir` 屬性」 | **不加** | 沒做 disk,paths 不需動;留乾淨 |
| § 3 「per-session 簡單(隨 session 結束釋放)」 | 用 lazy init by tool(設計決策 #3),不在 AgentContext default_factory | dataclass field 預設 factory 對所有 ctx 都建,測試浪費;lazy 跑出來行為等效 |
| § 4 驗收標準 `mock_transport.call_count == 1` | 用 closure counter dict 而非 transport 屬性 | httpx MockTransport 沒 call_count attr;包 wrapped handler 自己數,行為等價 |

---

## 實作中發現的坑

### 1. dataclass field 加新欄位後既有測試可能炸 frozen 假設
AgentContext 多了 `url_cache: object | None`。確認 AgentContext **非** frozen(可動態 setattr),`get_or_create_url_cache` 才能 lazy 掛上去。回看 `state.py:27`(`@dataclass` 沒 frozen=True),OK。

### 2. monkeypatch `time.monotonic` 要在 cache 內部使用後生效
`UrlCache.get()` 才 call `time.monotonic()`。若在 `cache.put` 後立刻 patch,patch 對 put 寫入時的 `fetched_at` 沒影響(已 captured)。test_ttl_expiry 先 put 再 patch,模擬「時間推進到未來」的語意,正確。

### 3. `get_or_create_url_cache` 不能用 `ctx.url_cache or cache`
`isinstance` 才能判斷現有的是不是 `UrlCache` 物件 — 防止其他 phase 把 object 塞進這欄位時誤覆蓋。

### 4. content-type 比對小寫化
`resp.headers.get("content-type", "").lower()` — Server 可能回 `Text/HTML` / `TEXT/html`,既有程式碼已 `.lower()`,cache 跟著存 lowered 版,`_render` 直接用不再 lower。

### 5. venv 不穩(無關 Phase 18)
本機 venv 在跑全套 pytest 時偶發 site-packages 子目錄消失(anyio、bs4、pydantic.v1)。用 `uv pip install --reinstall --no-cache --link-mode=copy <pkg>` 復原。**不是** Phase 18 引入。

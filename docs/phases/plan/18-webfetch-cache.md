# Phase 18:WebFetchTool URL caching

## 速覽

- **預計時程**:半天
- **前置 Phase**:Phase 2(storage 層基礎)
- **觸發來源**:Phase 1 完工後觀察:`WebFetchTool` 每次叫都打 HTTP,同 URL 多次 fetch 浪費 quota / 慢
- **主要交付物**:
  - per-session in-memory cache:URL → (timestamp, content_for_model)
  - TTL(預設 5 min)
  - 可選 disk persistence(複用 `storage/tool_result.py` 機制)

## 1. 為何要做

agent 在同一 conversation 多次 fetch 同 doc 是常見場景(模型多輪 reasoning 反覆 query 同 URL)。
目前每次都打網,慢且燒 fetch quota。

## 2. 任務拆解

- [ ] 新建 `storage/url_cache.py`:
  - in-memory dict:URL → (timestamp, response_text, content_type)
  - TTL 檢查(`ORION_WEBFETCH_TTL_SECONDS` 環境變數,預設 300)
  - 可選 LRU(預設 max 100 entries / session)
- [ ] `tools/web/fetch.py:WebFetchTool` 在打 HTTP 前查 cache
- [ ] cache hit 時加 `(cached)` 標籤到回給模型的 envelope
- [ ] 可選:落到 `~/.orion/sessions/<id>/url-cache/` 持久化(讓 resume 也命中 cache)
- [ ] 加 unit test(httpx mock transport assert 第二次 call 沒打網)

## 3. 設計決策

### per-session vs global

per-session 簡單(隨 session 結束釋放),夠用。
global cache 要處理 invalidation(同 URL 不同 user 看到的可能不同),太複雜不做。

### 為何不用 httpx 內建 cache?

httpx 沒內建 disk cache。`hishel` library 是 add-on,但對「短 TTL in-memory」過殺。

## 4. 驗收標準

```python
async def test_webfetch_cache_hit():
    tool = WebFetchTool()
    # 第一次:打 HTTP
    r1 = [e async for e in tool.call(WebFetchInput(url="https://x"), ctx)]
    # 第二次同 URL:不打 HTTP(httpx mock 計數驗)
    r2 = [e async for e in tool.call(WebFetchInput(url="https://x"), ctx)]
    assert mock_transport.call_count == 1
    assert "(cached)" in r2[0].text
```

## 5. 相關 code

- 新建 `orion_agent/storage/url_cache.py`
- `orion_agent/tools/web/fetch.py:WebFetchTool.call` — 加 cache 查詢分支
- `orion_agent/storage/paths.py` — 加 `url_cache_dir` 屬性(若做 disk 版)

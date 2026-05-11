# Phase 19:File history garbage collection

## 速覽

- **預計時程**:半天
- **前置 Phase**:Phase 2(file history snapshot 已實作)
- **觸發來源**:Phase 2 完工後觀察:長 conversation 會在 `~/.orion/sessions/<id>/file-history/` 累積大量 snapshot 檔
- **主要交付物**:
  - `file-history/` 目錄 LRU 或 max-snapshots 限制
  - 每 session 可設上限(預設 100 snapshots)
  - 達到上限時刪最舊的(by mtime)
  - 環境變數 `ORION_FILE_HISTORY_MAX_SNAPSHOTS`(預設 100)

## 1. 為何要做

目前 `make_snapshot()` 不停寫(同 hash dedupe,但不同內容無上限)。一個跑數小時的 session 反覆編輯
50 個檔可能累積 500+ snapshot。雖然 dedupe 救了 disk size,但 inode 浪費 + 列目錄變慢。

## 2. 任務拆解

- [ ] `storage/file_history.py` 加 `prune_old_snapshots(session_id, max_count)`:按 mtime 排序,刪超量
- [ ] `make_snapshot` 寫成功後 call prune(若超 threshold 才實際刪)
- [ ] 環境變數 `ORION_FILE_HISTORY_MAX_SNAPSHOTS` 控制 threshold(預設 100)
- [ ] 加 unit test:寫 150 個 snapshot,驗證最後只剩 100

## 3. 設計決策

### LRU vs max-count

LRU 需要追蹤 access time,複雜。**max-count + 按 mtime 刪舊**就夠用 — 反正 snapshot
是審計 / undo 用,通常只關心「最近 N 個」。

### 為何不刪 transcript 提到的 snapshot?

transcript 紀錄了寫過哪些檔,但**沒記**對應 snapshot 路徑。簡單起見不關聯,純按 mtime LRU。
若 user 真要 undo 老 snapshot,需要在還沒被 prune 前手動備份。

## 4. 驗收標準

```python
async def test_prune_removes_oldest_when_over_limit():
    # 寫 150 個不同內容的檔 + snapshot
    for i in range(150):
        path = tmp / f"f{i}.txt"
        path.write_text(f"version {i}")
        make_snapshot(sid, path)
    # 應只剩 ORION_FILE_HISTORY_MAX_SNAPSHOTS=100 個
    snaps = list((sp.file_history_dir).glob("*.snap"))
    assert len(snaps) == 100
```

## 5. 相關 code

- `orion_agent/storage/file_history.py`
- `orion_agent/storage/paths.py:SessionPaths.file_history_dir`

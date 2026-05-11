# Phase 19 — File history snapshot GC 完工記錄

**完成日期**:2026-05-12
**Plan doc**:`docs/phases/19-file-history-gc.md`(原 `docs/phases/plan/19-...`,完工後搬出)
**狀態**:✅ **881 unit tests passed, 2 skipped**(本 phase 新增 **10 tests**),mypy --strict 修改檔 0 issues。

Phase 2 的 `make_snapshot` 對相同 hash 已 dedupe,但不同內容無上限。長 session 多檔反覆編輯會累積上千個 `.snap` — disk 沒爆但 inode 浪費、列目錄變慢、備份成本上升。Phase 19 加 mtime LRU prune,預設每 session 上限 100。

---

## 交付清單

### 修改檔

| 檔 | 變更 |
|---|---|
| `storage/file_history.py` | +`_max_snapshots_from_env()` 讀 `ORION_FILE_HISTORY_MAX_SNAPSHOTS`(預設 100、無效 fallback);+`prune_old_snapshots(session_id, max_count)` 按 mtime 升冪刪超量;`make_snapshot` 寫成功尾巴 call prune(dedupe 路徑早 return 不觸發) |
| `.env.example` | 新增 Phase 19 段註明 `ORION_FILE_HISTORY_MAX_SNAPSHOTS=100`(per memory rule:env 變數一律寫進 example) |

### Tests(新增 1 檔,共 10 案例)

```
tests/unit/storage/test_file_history_prune.py    [全新]
├── test_prune_keeps_default_cap                  150 入 / 預設 100 出
├── test_prune_drops_oldest_keeps_newest          砍最舊 mtime → 留 version 15..24
├── test_env_override                             ORION_FILE_HISTORY_MAX_SNAPSHOTS=5 → 5
├── test_env_invalid_falls_back                   "not-a-number" → 預設 100
├── test_env_zero_disables_prune                  "0" → fallback 100(避免 0 誤踩無上限)
├── test_under_cap_noop                           30 個 + 上限 100 → 不動
├── test_prune_helper_direct                      prune_old_snapshots() 返回刪除數
├── test_prune_no_dir_safe                        file_history dir 不存在 → 0
├── test_prune_max_count_zero_or_negative         max_count <= 0 → no-op
└── test_dedupe_does_not_trigger_prune            同 hash 寫 100 次 → 仍 5 個 snap
```

---

## 設計決策

### 1. mtime LRU,不做 access-time LRU
Plan 設計決策 #1。snapshot 是審計 / undo 用,user 只關心「最近 N 個」。access-time tracking 要每次 read 更新 mtime 或維護 sidecar,複雜度遠超收益。

### 2. dedupe 路徑早 return,不觸發 prune
`make_snapshot` 在 hash 已存在時就 return,不 fall-through 到 prune。理由:
- dedupe 沒寫新檔 → 沒有「超量」可能
- 同 session 反覆 snap 同檔(無變更)若每次都 prune → CPU 浪費
- test_dedupe_does_not_trigger_prune 鎖此 invariant

### 3. env 「0」當無效值處理,不當「無上限」
Plan 沒指定 0 的語意。實作選擇:`v > 0` 才接受,否則 fallback 預設 100。理由:
- 「0 = 無上限」對使用者太反直覺(0 通常 = 關掉 / disable)
- 真要關 prune,該用很大的數(例如 1_000_000),意圖明確
- prune_old_snapshots 本身 `max_count <= 0` 直接 no-op(層次分明)

### 4. 不關聯 transcript
Plan 設計決策 #2。transcript 沒記對應 snapshot 路徑,純按 mtime 砍。若 user 要 undo 老 snapshot,得在被 prune 前手動備份;這在 spec 是 acceptable trade-off。

### 5. prune 內 `OSError` 跳過、不擋下其他刪除
`p.unlink()` 包 try/except OSError(檔案可能同時被 GC / 其他 process 刪)。記錄已刪數,失敗的不算。不 raise — prune 是 best-effort 清理,不該因單檔失敗破壞 `make_snapshot` 主流程。

---

## REST API 變更

無。Phase 19 純 fs 內部 housekeeping。

---

## 環境變數

| 變數 | 預設 | 說明 |
|---|---|---|
| `ORION_FILE_HISTORY_MAX_SNAPSHOTS` | `100` | 每 session 的 `.snap` 上限;超過按 mtime 砍最舊。非正整數 / 非數字 fallback 預設 |

已寫進 `api/.env.example`(per 「新增環境變數必同步 .env.example」memory rule)。

---

## Verification

```bash
cd orion-agent/api/

# 新測試集
.venv/bin/python -m pytest tests/unit/storage/test_file_history_prune.py -xvs
# → 10 passed

# 全套不退步
.venv/bin/python -m pytest tests/unit/
# → 881 passed, 2 skipped(+10 vs Phase 18 完工時的 871)

# typecheck 修改檔
.venv/bin/python -m mypy src/orion_agent/storage/file_history.py
# → Success: no issues found in 1 source file
```

### 手動驗證(plan § 4)

```bash
# 寫 150 個不同內容 → 確認剩 100
.venv/bin/python -c "
from pathlib import Path
import tempfile, time
from uuid import uuid4
from orion_agent.storage.file_history import make_snapshot
from orion_agent.storage.paths import session_paths

sid = uuid4()
with tempfile.TemporaryDirectory() as tmp:
    for i in range(150):
        p = Path(tmp) / f'f{i}.txt'
        p.write_text(f'version {i}')
        make_snapshot(sid, p)
        time.sleep(0.001)
    sp = session_paths(sid)
    snaps = list(sp.file_history_dir.glob('*.snap'))
    print(f'snapshots after 150 writes: {len(snaps)}')  # 應為 100
"
```

---

## Tests 摘要

| Suite | 數量 | 說明 |
|---|---|---|
| Phase 0–18 既有 | 871 | 全綠不動 |
| **Phase 19 prune 行為** | 6 | default cap / drops oldest / env override / invalid fallback / zero fallback / under cap noop |
| **Phase 19 helper 直接呼叫** | 4 | prune_helper / no dir / max_count<=0 / dedupe 不觸發 |
| **總計** | **881 passed / 2 skipped** | mypy 修改檔 0 issues |

---

## 風險與已緩解

| 風險 | 緩解 |
|---|---|
| 同一秒寫多檔 mtime 撞 tie,prune 順序非定 | 測試 `time.sleep(0.001)` 強制 mtime 差;生產上同秒寫 100+ 個檔本身罕見 |
| user 用 undo 想還原老版本,結果被 prune 掉 | plan 設計決策 #2 接受;上限 100 已超過正常 session 編輯量;真要長期保留,手動備份 |
| prune 與 make_snapshot 競態 (同 session 不同 thread 同時寫) | OSError 跳過、不擋主流程(設計決策 #5);Phase 19 沒上鎖 — 後續若有真實 contention 再加 |
| env `0` 被誤當「無上限」 | fallback 預設 100;test_env_zero_disables_prune 鎖此 invariant |
| 大量 snapshot 跑 prune 慢 | `glob + sort + unlink` 都 O(n),n=幾百級 → ms 級;不影響 user 感知 |

---

## 內部對應 plan 的差異

| Plan 章節 | 差異 | 為何 |
|---|---|---|
| § 4 驗收 `assert len(snaps) == ORION_FILE_HISTORY_MAX_SNAPSHOTS=100` | test 用 monkeypatch 而非 env 直接設 | pytest 環境一致性;monkeypatch 自動 teardown 不污染其他測試 |
| § 2 「prune (若超 threshold 才實際刪)」 | 實作改成「未超就 return 0」 | 等價;return 數量讓 caller 知道做了多少工 |

---

## 實作中發現的坑

### 1. substring match 假陽性(自寫測試踩到)
test_prune_drops_oldest_keeps_newest 第一版用 `f"version {v}" in body` 檢查 — `version 1` substring 會匹到 `version 15`,version 集合誤判全包含。改用 `re.compile(r"version (\d+)\b")` + 拆 `---SNAPSHOT---` header 後才搜。

### 2. dedupe 路徑早 return 阻止無意義 prune
`make_snapshot` 內 `if snap_path.exists(): return ...` 在 prune call 之前;dedupe 不寫新檔自然不需 prune。寫測試時刻意鎖此行為(test_dedupe_does_not_trigger_prune)— 避免未來重構誤把 prune 拉到 dedupe path 上方。

### 3. env 「0」三種可能語意,選 fallback 預設
- 「0 = 無上限」(常見 cache 系統慣例,例如 `maxsize=0` for unlimited cache)
- 「0 = 立刻 prune 到 0」(字面意思)
- 「0 = 無效,走預設」(本實作選此)

決策依據:使用者輸入 0 大多是想 disable,但「無上限」對 file_history 來說違背本 phase 動機。明確 fallback 預設 + 文件說明最不踩雷。

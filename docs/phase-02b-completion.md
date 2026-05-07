# Phase 2b — 補完 Phase 0 / 1 / 2 留下的小債

**完成日期**:2026-05-07
**前置**:Phase 2(commit `5709a26`)+ Phase 1b(commit `12cf363`)
**狀態**:✅ make check 全綠(152 tests + ruff + mypy --strict)

User audit phase-00 / phase-01 完工文件後發現三項漏網之魚。本次補完。

---

## 三項漏網的 TODO

### 1. ✅ `uv pip install -e .` 偶爾沒裝 source 的 root cause

**根因**:`~/Desktop` 與 `~/Documents` **被 macOS iCloud Drive 自動同步**(`FXICloudDriveDesktop = 1`)。
`uv pip install --reinstall` 寫 `.venv/.../site-packages/orion_agent-0.1.0.dist-info/` 時,iCloud
偶發 file conflict → **auto-rename 加 " 2"、" 3" 後綴**。

實測:污染後的 dist-info 內有 `RECORD 2`、`METADATA 5`、`uv_cache 7.json` 等 dupe。
真 RECORD 失效 → `import orion_agent` 失敗。

**修復**:
- `Makefile install` 改成連跑兩步(`uv sync` + `uv pip install -e . --reinstall`)
- `Makefile fix-install` 新 target,清掉 `* [2-9]*` 殘檔再重裝
- `Makefile clean-venv` 暴力刪整個 .venv
- 寫 `TROUBLESHOOTING.md` 記錄根因 + 三條解法(搬離 Desktop / 關 iCloud sync / `.nosync`)

### 2. ✅ GlobTool 大目錄記憶體控制

原:`list(base.glob(...))` 一次性載入所有 Path → 1M 檔目錄記憶體爆。

**修復**(`tools/search/glob.py`):用 `heapq` min-heap of size `_MAX_RESULTS=500`,
iterate `base.glob()` generator 逐一處理。記憶體用量 = O(_MAX_RESULTS) 而非 O(總檔數)。

關鍵程式碼:
```python
heap: list[tuple[float, str, Path]] = []
for p in base.glob(input.pattern):
    if not p.is_file(): continue
    try: mtime = p.stat().st_mtime
    except OSError: continue
    if len(heap) < _MAX_RESULTS:
        heapq.heappush(heap, (mtime, str(p), p))
    else:
        truncated = True
        if mtime > heap[0][0]:
            heapq.heapreplace(heap, (mtime, str(p), p))
```

stat 失敗(broken symlink / permission)現在優雅 skip,而非整批 sort 抑或 sort 失敗。

新增 2 測試:`test_truncates_at_max_results_and_keeps_newest` 建 600 檔驗 heap、
`test_handles_unreadable_file_gracefully` 用 broken symlink 驗 OSError 不炸。

### 3. ✅ tool_use_id ↔ tool_result 強配對 + auto-repair

**問題**:transcript 中途 kill 在 tool 執行中 → assistant 已 emit `ToolUseBlock`,但 user 的
`ToolResultBlock` 還沒寫入。Resume 後送進 model,Anthropic / OpenAI 都會 reject「dangling tool_use」。

**修復**:`storage/resume.py` 新 `validate_and_repair_messages(messages)`:
1. 掃 messages 蒐集所有 `ToolUseBlock.id` 與 `ToolResultBlock.tool_use_id`
2. 找 dangling(set 差集)
3. 在每個有 dangling 的 assistant message 後**插一則 synthetic user message**,內含對應
   `ToolResultBlock(is_error=True, content="(tool ... did not complete — interrupted)")`
4. 累積 warnings list,SessionSnapshot.warnings 對外曝露
5. `Conversation.resume()` 把 warnings 印 stderr 讓使用者知道

新增 5 測試:dangling-at-end、dangling-in-middle、multiple-in-one-assistant、
load_session-end-to-end-repair、no-dangling-unchanged。

---

## 改動的檔

| 檔 | 改動 |
|---|---|
| `Makefile` | install / fix-install / clean-venv targets |
| `TROUBLESHOOTING.md` | NEW — iCloud 根因 + 三條解法 |
| `tools/search/glob.py` | heapq-based,記憶體 O(MAX_RESULTS) |
| `storage/resume.py` | validate_and_repair_messages + SessionSnapshot.warnings |
| `core/conversation.py` | Conversation.resume() 印 warnings 到 stderr |
| `tests/unit/tools/test_glob.py` | +2 tests |
| `tests/unit/storage/test_resume.py` | +5 tests |

---

## 驗證

| 檢查 | 結果 |
|---|---|
| `ruff check` | ✅ |
| `mypy --strict` | ✅ no issues found in 54 source files |
| `pytest tests/unit/` | ✅ **152 passed**(145 → 152,+7) |

---

## 留下的(沒承諾,不算漏)

phase-01 完成記錄末尾「觀察到的後續優化機會」三項仍未做:
- `final_messages` 滾雪球 → Phase 3 compaction 解決(本就如此規劃)
- AgentTool max_concurrent_sub_agents limit
- WebFetchTool caching

這三項都是「nice-to-have」非「TODO」,不阻塞 Phase 3。

phase-00 完成記錄的「Abort 機制中斷 stream」目前**部分**做(turn 邊界 + BashTool 監看)。
中途 ctrl-C 即時中止 stream 留給 Phase 3 / 7 配合 anyio cancel scope 重做。

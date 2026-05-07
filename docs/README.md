# orion-agent / docs

每個 phase **完工後**寫一份完成記錄到這裡。

| 檔案 | 內容 |
|---|---|
| `phase-NN-completion.md` | Phase N 的:交付清單、驗證結果、與 spec 的差異、實作中發現的坑 |

## 文件規則

- **completion 文件 = 純粹完工記錄**,內容只能是已做的事
- **不可**含 `- [ ]` 未完成 TODO,也不可有「留給下個 phase」、「觀察到的優化機會」之類的 section
- 任何延後 / nice-to-have 工作 → **升級為新 phase plan**(`/Users/yuan-sencheng/Desktop/claude-code-source-main/docs/phases/<N>-<name>.md`)

## 與 spec doc 的關係

- **Spec(forward-looking)**:`/Users/yuan-sencheng/Desktop/claude-code-source-main/docs/phases/NN-*.md` — 實作**前**的計畫
- **Completion(backward-looking)**:本資料夾 — 實作**後**的記錄

## 已完成

- [x] [Phase 0 — Foundation](phase-00-completion.md)(2026-05-07)
- [x] [Phase 1 — Agent Loop](phase-01-completion.md)(2026-05-07)
- [x] [Phase 2 — Storage / Resume](phase-02-completion.md)(2026-05-07)
- [x] [Phase 1b — 補完 Phase 1 小債](phase-01b-completion.md)(2026-05-07)
- [x] [Phase 2b — 補完 Phase 0/1/2 漏網](phase-02b-completion.md)(2026-05-07)
- [x] [Phase 3 — Memory / Compaction](phase-03-completion.md)(2026-05-07)

## 從本專案衍生的新 phase plan

實作中觀察到的延後 / nice-to-have 工作,均升級為獨立 phase plan(在上層 `docs/phases/`):

- `phases/16-abort-stream-mid-flight.md` — stream 中途即時 abort(來源:Phase 0)
- `phases/17-agenttool-concurrency-limit.md` — AgentTool 全域並發上限(來源:Phase 1)
- `phases/18-webfetch-cache.md` — WebFetchTool URL caching(來源:Phase 1)
- `phases/19-file-history-gc.md` — file history snapshot GC / LRU(來源:Phase 2)
- `phases/20-transcript-compression.md` — transcript JSONL gzip(來源:Phase 2)

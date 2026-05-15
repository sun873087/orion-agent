# Phase 31-G:Memory Layer 3 + Layer 4

## 速覽

- **預計時程**:1 週
- **前置 Phase**:無(Track 3 獨立)
- **狀態**:📝 spec only,**未實作**
- **目標**:補完 memory 防膨脹四層的後兩層。Layer 1+2 已實作(寫入端去重、TTL),Layer 3+4 處理「累積」(使用模式、總量)。

詳細 design 已在 [`../../features/memory.md`](../../features/memory.md) — 本 plan 是執行版本。

## 1. Layer 3:使用率追蹤

### 1.1 解的問題

「殭屍 memory」— 沒過期、沒重複、但實際上沒人在用:

- 三年前的 `feedback_zsh_quirk_macos12.md`
- 結束的專案 `project_xxx_decision.md`
- 偏好已改變但舊 `feedback_*` 沒被取代

### 1.2 設計:Sidecar 事件 log

不動 memory 檔本身,在 memory 目錄下加 append-only 事件檔:

```
~/.orion/users/<uid>/memory/
├── MEMORY.md                       # 既有索引
├── feedback_zsh.md                 # 既有 memory 檔
├── ...
└── _events.jsonl                   # ★ 新:每次 ranker hit / write 一筆
```

事件格式:
```json
{"ts": "2026-05-16T...", "type": "ranker_hit", "memory": "feedback_zsh.md", "session": "<uuid>"}
{"ts": "2026-05-16T...", "type": "write", "memory": "feedback_zsh.md", "op": "create|update"}
```

### 1.3 計算 score

`memory/usage.py`(新):

```python
def compute_usage_score(memory_filename: str, today: date) -> float:
    events = load_events()
    hits = [e for e in events if e["memory"] == memory_filename and e["type"] == "ranker_hit"]
    if not hits:
        return 0.0
    # exponential decay:近期 hit 權重高
    score = sum(0.95 ** (today - parse_date(h["ts"]).date()).days for h in hits)
    return score
```

### 1.4 整合進 ranker

Existing `memory/relevance.py:rank_memories()` 多收一個 weight:

```python
def rank_memories(memories, query, *, today, usage_weight=0.3):
    for m in memories:
        m.score = (1 - usage_weight) * semantic_score(m, query) \
                + usage_weight * compute_usage_score(m.filename, today)
    return sorted(memories, key=lambda m: m.score, reverse=True)
```

低 usage score 的 memory 即使語意 match 也排後面。

### 1.5 UI:顯示 usage stat

REST endpoint `GET /me/memories` 回傳多加 `usage: { hits_30d, hits_90d, last_hit }`。前端 UI 可顯示「殭屍指示」。

### 1.6 任務

- [ ] `memory/usage.py` 寫入 + 讀取 events.jsonl
- [ ] `memory/relevance.py:rank_memories()` 接 usage_weight
- [ ] `Conversation` 在 ranker 選出 memory 時,emit ranker_hit event
- [ ] `extract.py` 在 create/update memory 時 emit write event
- [ ] REST `/me/memories` 回傳含 usage stat
- [ ] Web UI 加 usage 顯示
- [ ] events.jsonl GC:>90 天 events 移到 archive(避免無限長)

## 2. Layer 4:配額 + 建議合併

### 2.1 解的問題

同類型 memory 量級爆量,語意重複但 description 不同:

- `feedback_concise_response_1.md`、`feedback_be_brief.md`、`feedback_no_padding.md` 其實同條規則
- `project_X_decision_2026q1.md`、`project_X_constraints.md`、`project_X_goals.md` 可能重疊

### 2.2 設計:per-type quota + LLM-suggested merge

#### Quota

每個 memory type 軟 quota(default):
- `user` — 50
- `feedback` — 100
- `project` — 30 per project
- `reference` — 50

超過 quota → trigger merge suggestion job(不阻擋寫入,只通知)。

#### Merge suggestion job

跑在背景(`apscheduler` daily):

1. 找出 quota 超量的 type
2. 同 type 內,用 embedding cluster 找相似度高的 group
3. 對每個 group 跑 LLM call:「以下 N 筆 memory 看起來相關,可以合併成一篇嗎?」
4. LLM 回 `{"merge": true, "merged_content": "..."}` 或 `{"merge": false}`
5. 寫到 `~/.orion/users/<uid>/memory/_suggestions.jsonl`
6. UI 顯示「建議合併」icon,user 點 → 看到原 N 筆 + 建議新版 → 接受或拒絕

### 2.3 任務

- [ ] `memory/quota.py`:per-type count + soft quota config
- [ ] `memory/merge_suggester.py`:embedding cluster + LLM call
- [ ] APScheduler job daily(在 SDK 既有的 scheduler 內)
- [ ] REST `GET /me/memories/suggestions` + `POST /me/memories/suggestions/<id>/accept` (or reject)
- [ ] Web UI 加 suggestions panel
- [ ] Embedding model:用 OpenAI text-embedding-3-small(便宜)或 SDK 內建小模型(若有)

### 2.4 Embedding choice

`text-embedding-3-small` 一筆 ~5 token,~$0.00001/1K tokens。100 個 memory × 50 token avg = 5000 token = $0.05。可接受。

## 3. 風險

| 風險 | 緩解 |
|---|---|
| events.jsonl 無限長 | GC > 90 天 events 移 archive |
| Layer 3 加入 ranker 改變既有行為,user 不喜歡 | 預設 `usage_weight=0`,opt-in 才啟用 |
| Merge suggest false positive(合併不該合併的)| 只 suggest 不自動合併;user 必須明確 accept |
| Embedding API call 成本 | rate limit:每 user 每天最多 1 次 merge suggest job |
| `_events.jsonl` write 競爭(多 conversation 同時 hit) | append-only + file lock(短暫)|

## 4. 驗收

- [ ] 跑 5 個 conversation,讓 ranker hit 某些 memory → `_events.jsonl` 有對應紀錄
- [ ] 啟用 usage_weight → 觀察殭屍 memory 排名下降
- [ ] 灌 200 筆 feedback memory → 跑 merge suggest job → 拿到 N 個建議
- [ ] UI 接受合併 → 原 N 筆 → 1 筆,內容合理

## 5. 完成後

Phase 31-G 完成 = memory 系統四層防膨脹全到位。

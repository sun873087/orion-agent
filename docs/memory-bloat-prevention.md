# Memory Bloat Prevention — 四層防護設計

跨多次 commit 的 memory 系統 anti-entropy 設計專題。本文記錄四層防護的動機、權衡、實作狀態,以及未實作層的觸發條件與設計草案,供後續維護決策參考。

| 層 | 解的問題 | 狀態 | Commit |
|---|---|---|---|
| **Layer 1**:寫入端去重 | LLM extract 重複建立相似 memory | ✅ 完成 | `5cab15f` |
| **Layer 2**:TTL / 過期淘汰 | 過時 memory(如已過 deadline)污染 prompt | ✅ 完成 | `852efff` |
| **Layer 3**:使用率追蹤 | 沒過期、沒重複但沒人在用的「殭屍 memory」 | ⏸ 未做 | — |
| **Layer 4**:配額 + 建議合併 | 同類型過多、語意重複但 description 不同 | ⏸ 未做 | — |

四層**獨立解不同問題**,不是替代關係。Layer 1+2 處理「源頭」(寫入時 / 內容時效),3+4 處理「累積」(使用模式 / 量級爆量)。

---

## Background:為什麼 memory 會膨脹

Phase 3 的 memory 系統把對話結束後 LLM 認為值得記的內容,以 markdown 檔形式存到 `~/.orion/users/<id>/memory/`。每輪對話開始時,relevance ranker 選出 top-N 注入 system prompt。

沒做防護時,膨脹來源有四個:

1. **Extract 不斷存類似內容**(寫入端) — LLM 看到既有 memory 跟新發現「有點像」時,只能選新增或不存,實務上多半選新增 → 同 topic 多筆。
2. **過時資訊持續注入**(內容時效) — Q3 deadline 過了,memory 還在,但 LLM 仍把 6/30 當有效日期。
3. **沒人用的舊 memory 永遠在**(使用模式) — 三年前救過你的 zsh quirk fix,你早不用那版 macOS,沒過期、也沒重複,但 ranker 偶爾還是會撈出來干擾。
4. **同類型量級爆量**(總量) — feedback 累積 100+ 筆,有些其實是同一條規則的不同表述。

不防護的後果:
- LLM ranker token 成本線性成長
- 注入過時或無關的 memory 讓回應品質變差
- UI 上 memory 清單變難管理,使用者沒辦法 maintain

---

## Layer 1:寫入端去重(已完成)

**Commit**:`5cab15f` — `feat(memory): teach extractor to UPDATE existing memories instead of duplicating`

### 設計

改 extract 流程,讓 LLM 在發現既有 memory 跟新內容重疊時 emit `UPDATE: <filename>` 而非新建 `FILE:`。

關鍵變動:
- `extract_prompts.py` system prompt 加 UPDATE 區塊說明,並明確指示「emit FILE 前先掃既有清單,重疊就用 UPDATE」
- `extract.py:_summarize_existing_memories()` 既有 memory 清單從只有 `description` 升級為 `filename + description + body preview(前 200 字)`,讓 LLM 真的能判斷是否重複
- `extract.py:parse_extract_output()` 回 `(op, filename, content)` 三元組,`op ∈ {"create", "update"}`
- `extract.py:extract_memories()` UPDATE 必須對應實際存在檔案才寫入(防 LLM 編造 filename 污染);MEMORY.md 索引以 in-place 取代而非 append

### 為何選這個層為第一步

寫入端去重解決**根本原因**:沒有重複寫入,後面三層的問題自然降低。改動最小、不需新欄位、不破壞既有 frontmatter schema、零 LLM 額外成本。

### 限制(Layer 1 救不到的)

- 依賴 LLM 自己判斷重疊。LLM 保守時仍會建新檔(false negative)
- 對「語意相同但 description 詞彙不同」的 case 偵測力弱
- 不處理時效問題(Layer 2 才管)

---

## Layer 2:TTL / 過期淘汰(已完成)

**Commit**:`852efff` — `feat(memory): add expires_at TTL so stale memories stop polluting prompts`

### 設計

Frontmatter 加可選 `expires_at: YYYY-MM-DD`。`scan_memory_dir()` 加 `exclude_expired` flag,只有 **prompt 注入路徑**設為 True,其他 caller(REST UI、extract)仍看到全部 memory。

關鍵變動:
- `types.py:MemoryFrontmatter` 加 `expires_at: date | None`
- `types.py:Memory.is_expired(today)` helper
- `scan.py:parse_frontmatter()` 讀 `expires_at`;壞日期格式 log warning 視為 None,不卡死整個 scan
- `scan.py:scan_memory_dir(paths, *, exclude_expired=False, today=None)`
- `prompt/dynamic_sections.py:memory_section()` 明確傳 `exclude_expired=True`
- `extract_prompts.py` 教 LLM 為 `project` 類型(~90 天)和 `reference` 類型(~180 天)設 `expires_at`;`user` / `feedback` 省略
- `api/routes/memories.py` REST schemas 暴露 `expires_at` 欄位讓前端能讀寫

### 關鍵設計選擇

| 抉擇 | 結果 | 理由 |
|------|------|------|
| 過期 = 排除注入 vs 刪檔 | **只排除,不刪** | 可逆;使用者可手動續期 |
| `expires_at == today` | **視為仍有效** | 隔天才算過期,避免時區邊界 |
| 預設 `exclude_expired=False` | **向後相容** | 既有 caller 行為不變 |
| 壞日期 | **log warning + None** | 單筆壞 frontmatter 不卡死全 scan |
| 各 caller 行為 | UI / extract / index 看全部;只有 prompt 注入排除 | 過期 memory 可從 UI 復活,extract 可 UPDATE 它 |

### 限制(Layer 2 救不到的)

- `user` / `feedback` 類型本來就不該有 TTL,但實際上某些 user 事實會過期(例:「user 在 X 公司」,X 公司離職後該 memory 過時但沒人會去刪)
- 依賴 LLM 主動設 `expires_at`,沒設就視為永久
- 不解決「使用率」維度的問題(Layer 3 才管)

---

## Layer 3:使用率追蹤(未實作)

### 解的問題

Layer 1+2 都救不到的「殭屍 memory」:沒過期、沒重複、但實際上沒人在用。例:

- 三年前的 `feedback_zsh_quirk_macos12.md`,使用者早不用 macOS 12,但 memory 沒過期、沒重複
- 舊專案的 `project_xxx_decision.md`,專案結束但沒有 `expires_at`(忘記設)
- 使用者改變偏好後,舊 `feedback_*` 沒被取代

也解決使用者面對 50+ memory 時「我哪知道哪個還在用」的能見度問題。

### 設計草案:Sidecar 事件 log(推薦)

不動 memory 檔本身,在 memory 目錄下放 append-only 事件檔:

```
~/.orion/users/<id>/memory/
├── feedback_terse.md
├── feedback_terse.md
├── user_role.md
└── .usage.jsonl                    ← append-only
```

`.usage.jsonl` 每次 ranker 選中時 append:

```json
{"ts":"2026-05-11T14:32:00Z","file":"feedback_terse.md","reason":"ranked"}
{"ts":"2026-05-11T14:35:12Z","file":"user_role.md","reason":"ranked"}
```

UI 讀全 log + 聚合,給每筆 memory 算出 `last_used_at` / `used_count_30d` / `used_count_total`。

### 為何選 Sidecar 而非改 frontmatter

| 方案 | 優點 | 缺點 |
|------|------|------|
| Sidecar `.usage.jsonl` | append-only → 零 race condition;不破壞檔案格式;關了零影響 | 需要 rotation(每月切檔保留 90 天) |
| Frontmatter `last_used_at` | 不用 sidecar | 每次寫 = 改既有檔,需 atomic write + 避開讀寫衝突,race condition 風險高 |

選 sidecar。讀取/聚合 5 分鐘 LRU cache。

### Cost 拆解

| 維度 | 評估 |
|------|------|
| 錢 | 0 |
| 複雜度 | 中:append 函式 + 聚合函式 + rotation + UI 排序與 badge |
| 延遲 | 微(每輪一次 fire-and-forget append) |
| 風險 | 低(append-only;壞了刪 sidecar 重來) |

### 觸發條件(何時做)

當以下任一條件滿足:

- 使用者的 `~/.orion/users/<id>/memory/` 超過 **50 筆 memory**
- 使用者打開 MemoryPanel 第一個想法是「我哪知道哪些還在用」
- LLM ranker 的月成本超過可接受門檻(目前 Haiku ranker 大約 N=100 時 $0.0028/輪,還很低)

目前都不到。

---

## Layer 4:配額 + 建議合併(未實作)

### 解的問題

Layer 1+2+3 都救不到的長尾情況:

- **語意相同但 description 詞彙不同 → Layer 1 抓不到**
  - `feedback_test_no_mock.md`: "不要 mock database"
  - `feedback_integration_real_db.md`: "integration test 必須打真 DB"
- **同類型過多 → ranker token 成本爆**:100 筆 feedback 全進 ranker payload

### 三種子方案

#### 4A:自動 LLM 合併(不推薦)

背景 job 偵測高相似度 pair → Haiku 合併 → 覆蓋舊檔。

**致命缺陷**:LLM 合併會丟「為什麼」這個關鍵脈絡。

```
合併前:
  Memory 1: "Q3 deadline 是 6 月 30 — 因為 legal compliance 要趕"
  Memory 2: "Q3 deadline 延到 9 月 30 — 因為 legal 改要求"

合併後可能變:
  "Q3 deadline 9 月 30"               ← 為什麼延掉了
```

不可逆的資訊流失。**不採用此方案。**

#### 4B:純警示通知

不做合併,只在 memory count 超過 quota 時跳通知:

```
[Memory] 你有 35 筆 feedback memory(soft cap = 30)。
        最相似的 3 對:
          - feedback_test_no_mock.md ↔ feedback_integration_real_db.md
          - ...
        [Review now]   [Dismiss]
```

只用 heuristic(bag-of-words / cosine on description+body)算相似度,**完全不跑 LLM**。

#### 4C:「建議合併」UI(推薦最終形態)

4B 的延伸:點 [Review now] 跳 diff 介面,使用者拍板:

```
┌───────────────────────────────────────────────────────┐
│  Memory 1 (left)          │  Memory 2 (right)         │
│  feedback_test_no_mock.md │  feedback_integration...  │
│  ...                      │  ...                      │
├───────────────────────────────────────────────────────┤
│  [Generate merged draft (Haiku)]                      │
│  [Delete left, keep right]                            │
│  [Delete right, keep left]                            │
│  [Cancel]                                             │
└───────────────────────────────────────────────────────┘
```

LLM 只在使用者**明確點按**時介入,給草稿。使用者拍板。

### 設計選擇

| 抉擇 | 結果 | 理由 |
|------|------|------|
| 自動 vs 人工觸發合併 | **永遠人工** | LLM 合併資訊流失不可逆 |
| 相似度演算法 | heuristic 先,LLM 二次過濾(可選) | heuristic 免費;若想加強再加 |
| Per-type quota | soft cap 警示,不 hard reject 寫入 | 強制 reject 會中斷 extract 流程 |
| 預設 quotas | user: 20 / feedback: 30 / project: 50 / reference: ∞ | reference 是 URL,便宜不限制 |

### Cost 拆解(以 4B + 4C 為例)

| 維度 | 評估 |
|------|------|
| 錢 | 低(LLM 只在使用者點「Generate merged」時跑,用 Haiku) |
| 複雜度 | 高:相似度演算法 + diff UI + merge action + rollback + quota 設定面 |
| 延遲 | 0(全部使用者觸發) |
| 風險 | 低-中(全部有人類確認) |

### 觸發條件(何時做)

當以下任一條件滿足:

- 任一 type 的 memory 數量 > 50 筆
- 使用者實際遇到「相同規則寫兩遍但找不到」
- LLM ranker 月成本因 memory 量大幅成長(目前 Haiku 在 N=500 時約 $0.04/輪,仍可接受)

單人用 orion 大概永遠不會撞到。**多人多租戶部署才可能有商業必要。**

---

## 決策準則:何時做下一層

每層都解不同維度的問題,**不該預先實作**:

1. **量沒到別動** — Layer 3+4 都是「累積問題」的解,memory 不到 50 筆做也沒效果驗證
2. **觀察先於實作** — 真要做 Layer 3+4 之前,先手動掃自己的 `memory/` 目錄看狀況。可能根本不需要
3. **每層應有清楚的「觸發條件」** — 上面每層都列了。沒撞到就先放著

這與 `feedback_cost_optimization.md`(成本優化第一級)記下的偏好一致:
- 已做的 Layer 1+2 都是 **零 LLM 額外成本** 的結構性優化
- 未做的 Layer 3+4 多半是「未來能見度工具」,提前做就是 over-engineering
- 真要做 Layer 4,選 4C(人工拍板)而非 4A(自動合併),避免不可逆損失

---

## 相關位置

- 程式碼:`api/src/orion_agent/memory/`
- REST:`api/src/orion_agent/api/routes/memories.py`
- 前端:`frontend/src/components/MemoryPanel.tsx`
- Phase 3 spec:`docs/phases/03-memory-compaction.md`
- Phase 3 completion:`docs/phase-03-completion.md`
- REST endpoints plan:`docs/phases/plan/25-memory-mcp-rest-endpoints.md`

# Multi-mode collab — Coordinator / Swarm 接 Cowork GUI

把 SDK 既有的 **headless 多 agent pattern** 接進 Cowork。User 在
NewCollaborationModal 選「並排 pane(現有)/ 平行加速(coordinator)/ 自由
辯論(swarm)」三模式之一。**目前不在實作範圍**,設計討論收檔。

> Cowork 既有「並排 pane」是 user 主導 — 適合邊看邊調。Coordinator / Swarm
> 是 agent 主導 — 適合「丟出去自動跑」。把後兩個 GUI 化,user 可看著過程
> 而不是「等到結果出來才見」。

---

## 動機

| Mode | 目前狀態 | 接 GUI 帶來什麼 |
|---|---|---|
| 並排 pane(collab) | ✅ 已實作 | — |
| Coordinator | SDK Python class 已有 / GUI 看不到過程 | **可視化 fan-out 過程**(對比 `AgentTool` 是黑箱) |
| Swarm | SDK Python class 已有 / GUI 看不到過程 | 實驗 sandbox(看 N agents 怎麼互動) |

---

## 決策一覽

6 個關鍵問題全部已決,reviewer 看一眼就懂走哪條:

| # | 問題 | 決策 | 詳細段 |
|---|---|---|---|
| 1 | SDK Coordinator/Swarm 是 batch-return,GUI 要 streaming | 改 SDK API 變 async generator | [Streaming](#streaming-架構決策) |
| 2 | Workers 跑完的 sessions 要不要存 DB | 存 DB + 隱藏 + 7 天 auto-GC | [Worker session](#worker-session-儲存決策) |
| 3 | Coordinator hierarchy 讓 user 誤判 cost | 三層級顯式(collab total / leader+workers / per-worker) | [Cost 顯示](#cost-顯示決策) |
| 4 | Swarm 何時停 | `max_rounds + budget + manual` + 5 個額外(convergence、DONE signal、graceful taper 等) | [Swarm 終止](#swarm-終止條件決策) |
| 5 | Multi-worker 同檔衝突 | 沿用 optimistic + 3 safeguards(分工提示、3 次撞 halt、destructive Bash dry-run) | [Tool concurrency](#tool-concurrency-決策) |
| 6 | Swarm 標實驗性後怎防 user 踩坑 | Safe mode default on(disable Edit/Write/Bash/NotebookEdit) | [Safe mode](#實驗性-safe-mode-決策) |

---

## 設計總覽

### IA — 1 個「協作」tab + mode picker

Sidebar 仍是 1 個「協作」tab。NewCollaborationModal 加 mode picker:

```
新協作
─────────────────
名稱: [_______]
模式:
  ● 並排多 pane(預設)
       N 個 agent 同畫面,你切焦點主動操控
  ○ 平行加速 ⚡
       一個 prompt 丟給 leader,leader fan-out N workers 平行跑
  ○ 自由辯論 🌐 [實驗中]
       N agents 自己互傳訊息,你看著對話流動
─────────────────
```

Sidebar collab row icon 區分:
- 👥 並排
- ⚡ 平行加速
- 🌐 自由辯論 + 紅色「實驗」badge

### Schema — 不開新表,加一欄

```sql
ALTER TABLE cowork_collaborations ADD COLUMN mode TEXT NOT NULL DEFAULT 'pane';
-- 'pane' / 'coordinator' / 'swarm'
```

避免 3 張表複製概念。`mode` 決定 view 渲染 + sidecar 怎麼 wire SDK runner。

### UI 形狀

**Coordinator** — leader 上,workers 下方並排:

```
┌─ Leader pane ─────────────────────────────────┐
│ user: 找 5 個 file 各自 summary               │
│ assistant: 我來分派...                         │
│ [spawning 5 workers]  ▼ 展開                   │
└────────────────────────────────────────────────┘
┌─ @w1 ──┬─ @w2 ──┬─ @w3 ──┬─ @w4 ──┬─ @w5 ──┐
│ stream │ stream │ stream │ stream │ stream │
└────────┴────────┴────────┴────────┴─────────┘
```
共用既有 react-resizable-panels 結構。**否決的替代方案**:inline card(沒解決
「看過程」核心)、tree view(streaming 多 node 太糟)。

**Swarm** — 在 multi-pane 上加 message-bus 視覺:

```
┌─ Multi-pane(沿用 collab UI) ────────────────┐
│ @a │ @b │ @c                                   │
└─────┴─────┴─────────────────────────────────────┘
↓ 訊息流 toast / 側欄 timeline
[@a → @b: "I think we need to refactor..."]
[@c → @a: "agree, but consider..."]
```
每 pane header 加「sent N / recv N」counter。靠 SDK 既有 `MessageBus`。

### SDK 怎麼接

| Mode | SDK 對應 | Sidecar 怎麼 wire |
|---|---|---|
| pane | 既有 multi-pane logic | 已實作 |
| coordinator | `multi_agent/coordinator.py` `run_coordinator()` | 走新 streaming API,routing N worker streams 給 renderer(`worker_id` frame routing) |
| swarm | `multi_agent/swarm.py` `run_swarm()` | 走新 streaming API + `message_bus` 訂閱 → emit `swarm_message` frames 給 renderer |

---

## Streaming 架構決策

### 問題
SDK `run_coordinator()` 是 batch-return,跑完才返 dict。GUI 要的是 N 個
worker stream 同時可見(@w1 寫到第 3 段、@w2 卡 tool call、@w3 已完成)。

### 走 A — 改 SDK API 變 async generator

```python
# Before
async def run_coordinator(...) -> CoordinatorResult: ...

# After
async def run_coordinator(...) -> AsyncIterator[CoordinatorEvent]: ...
# CoordinatorEvent 例:
#   {worker_id, type: "text_delta", text}
#   {worker_id, type: "tool_call", name, input}
#   {worker_id, type: "done", result}
#   {type: "leader_summary", summary}
```

### 為何選 A 不選 B(sidecar wrap)

| | A 改 SDK | B sidecar wrap |
|---|---|---|
| 工程量 | ~5d | ~2d |
| 技術債 | 無 — SDK 變 stream-first,跟 `Conversation.send()` 一致 | 兩份 coordinator 邏輯 |
| 跨 host 受惠 | CLI / chat-api / Cowork 全受惠 | 只 Cowork |
| SDK API 完整 | ✓ | ✗ `run_coordinator` 變 dead code |

### 為何敢改 SDK API
1. **沒 production caller** — SDK doc 標「Phase 15,Cowork 還沒接」
2. **對齊既有 pattern** — `Conversation.send()` 本來就是 async generator
3. **未來 CLI / chat-api 真要接直接拿**

### Streaming-specific 子問題
- **Backward compat 破壞**:現有 caller 全壞,但 SDK 內外都沒這種 caller,可大膽改
- **Worker 失敗**:emit `worker_error` event 讓 leader 自己 decide,不終止整個 generator
- **Cancellation**:用 `anyio.CancelScope` 包,每 worker 起 task group

---

## Worker session 儲存決策

### 問題
Coordinator fan-out N workers,sub-Conversation 的 messages / cost / state
要不要存 DB?

### 走 C — 存 DB + 隱藏 sidebar + 7 天 auto-GC

| | A. Ephemeral | B. 完整存 | **C. 存但隱藏 + auto-GC** |
|---|---|---|---|
| Replay worker 細節 | ❌ | ✅ | ✅(GC 期間內) |
| Cost 準確 | ❌(workers tokens 丟了) | ✅ | ✅ |
| DB 爆量 | 0 | 線性 | 上限可控 |
| Sidebar 雜訊 | 0 | 多 N 倍 row | 0(filter 掉) |
| 跨 restart | 不保留 | 完整保留 | GC 內保留 |

**為何不 A**:replay 真有用 + cost 對不上既有 `cum_*` 持久化(退步)+ debug 困難。
**為何不 B**:DB 爆量(10 次/天 × 5 workers = 半年 ~9000 rows)+ sidebar 雜訊。

### Schema 擴

```sql
-- cowork_session_ext 加(沿用 fork lineage 同 pattern)
parent_collab_session_id TEXT     -- 指向 leader,NULL = 非 worker
worker_index INTEGER              -- 0, 1, 2, ... 排序用

-- cowork_collaborations 加
worker_retention_days INTEGER NOT NULL DEFAULT 7
```

### 重要 SQL pattern

```sql
-- Sidebar filter:只顯 top-level
WHERE parent_collab_session_id IS NULL

-- Leader cost rollup:把 workers 加總
SELECT SUM(cum_*)
FROM cowork_session_ext
WHERE session_id = ? OR parent_collab_session_id = ?

-- GC job:刪超過 retention 的
DELETE WHERE parent_collab_session_id IS NOT NULL
  AND created_at < NOW() - retention_days
```

### Edge cases
| 情境 | 處理 |
|---|---|
| 想留特定 worker 不被 GC | Pin 按鈕 → 跳過 GC |
| Worker abort 沒跑完 | 仍存(part-done 有 debug 價值)+ 標 `status: aborted` |
| Leader 被刪 | Cascade 刪 workers(沿用既有 `delete_sessions=true`) |
| Crash recovery resume | Worker sessions 還在 → 可看中斷狀態 |

### Settings 進階 user 逃生口
**Worker session retention**:`7 days`(預設)/ `30 days` / `90 days` / `forever` / `不存`

「不存」= 退回 A 方案,給超頻繁 + 不在乎 replay 的 user。

---

## Cost 顯示決策

### 問題
Coordinator leader pane 顯「$0.15」,user 誤以為這次跑 $0.15,實際 5 個
workers 燒完 $1.23。帳單嚇到。

> **這決策只針對 Coordinator**。Swarm 跟 pane mode 沒 hierarchy,各 pane 顯
> 各自 cost 即可。

### 走 D — 三層級全部顯式

```
┌─ Collab: 重構 query loop     [ Total: $1.23 ▾ ]    [+] [X] ┐  Layer 1
├──────────────────────────────────────────────────────────────┤
│ ● @leader (Opus)   Leader: $0.15 · with workers: $1.23  X  │  Layer 2
│ ┌──────────────────────────────────────────────────────────┐│
│ │ Messages...                                              ││
│ └──────────────────────────────────────────────────────────┘│
├──────────────────────────────────────────────────────────────┤
│ @w1 ($0.21) │ @w2 ($0.18) │ @w3 ($0.31)⚠ │ @w4 ($0.15) │... │  Layer 3
└──────────────────────────────────────────────────────────────┘

點 Total ▾ 展開 breakdown:
┌─ Cost breakdown ─────────────┐
│ @leader      $0.15  ( 12% )  │
│ @w1          $0.21  ( 17% )  │
│ @w2          $0.18  ( 15% )  │
│ @w3          $0.31  ( 25% )⚠ │ ← cost outlier 紅色
│ @w4          $0.15  ( 12% )  │
│ @w5          $0.23  ( 19% )  │
│ ───────────────────────────  │
│ Total        $1.23           │
└──────────────────────────────┘
```

| Layer | 給誰看 | 為什麼 |
|---|---|---|
| L1 collab header total | 撇一眼的 user | 一秒看到「這場花多少」 |
| L2 leader header 雙顯 | 跑 Coordinator 的 user | 一眼看出 leader 跟總和差很多 — **消除誤導** |
| L3 per-worker | 找元兇 | 看哪 worker 燒最多 |

### 視覺強化
- **「with workers」字眼粗體**(對比 leader 是次要)
- Workers cost > leader **4×** → leader header 加 ⚠ + tooltip「workers 佔 88%」
- 單一 worker > 平均 **2×** → 紅色邊框 + "cost outlier" label
- **超 budget cap** → collab header 邊紅 + Total 變紅閃

### Pre-flight estimate(送出前先估)
Leader 送 prompt 後、fan-out 前,跑 `services.side_query.py` LLM judge:
- 估「需 ~5 workers,各 ~10 turn,total ~$1.20」
- 顯 tooltip 給 user
- 超 budget 50%+ → 紅字 + 雙重 confirm

### Backend RPC
新加 `coordinator.cost_breakdown`:
```json
{
  "leader_self_cost_usd": 0.15,
  "workers_total_cost_usd": 1.08,
  "grand_total_usd": 1.23,
  "workers": [
    {"session_id": "...", "pane_name": "@w1", "cost_usd": 0.21, "is_outlier": false},
    {"session_id": "...", "pane_name": "@w3", "cost_usd": 0.31, "is_outlier": true}
  ]
}
```

### Settings 進階選項
**Cost display mode**:`with_workers`(預設)/ `leader_only`(進階,workers 分開列)

---

## Swarm 終止條件決策

### 問題
`max_rounds + budget_guard + manual_stop` 三個基本盤涵蓋 60% 災難,剩 40% 在
「無進展浪費 / 訊息量爆 / 卡死 / 共識後沒人停」。

### 走 3 + 5 — 基本盤 + 5 個額外

#### 1. `max_messages_per_round`(防訊息雪崩)
每 round 限 N 訊息(預設 **5**)。N peers 都發完才進下 round。避免 A→B+C,
B 回 A+C+D,C 再 broadcast... 級數爆炸。

#### 2. `per_agent_timeout`(防卡死)
單 agent X 秒沒回應(LLM / tool / network 卡)→ 標 `dead` + 跳過 + 其他 peers
繼續。User 看到 dead 燈號可選 retry / kill / continue。

#### 3. Convergence 偵測(早停)
- 連續 K rounds(預設 **2**)peers 訊息語意上沒變 → 早停
- 用 SDK 既有 `services.side_query.py` 跑 LLM judge:「最近 K rounds 有進展嗎?」

#### 4. Explicit `<TERMINATE>` signal(共識後正式結束)
- 任一 agent 發 `<TERMINATE>` → 表「我覺得可以結束」
- 過半 peers(`majority_done_threshold`,預設 **N/2 + 1**)發了 → 進「收尾模式」
- 收尾模式不再交談,各 agent 跑一輪寫 final summary

#### 5. Approaching-limit graceful taper(軟落地)
- Budget 用到 **80%** → 注 system message:「budget 快用完,請收尾」
- Round 達 max-1 也同樣 inject
- 比硬 cut 好:hard cut 時 transcripts 半條 + summary 沒寫;軟落地讓 agents 整合

### UI 影響
- **頂部進度條**:`Round 3 / 8` + `$0.43 / $1.00` + `5 messages used`
- **Pane header 3 種額外狀態**:`thinking`(琥珀)/ `dead`(灰)/ `done`(藍勾)
- **大紅「立即停止」按鈕永遠在** — one-click,不要 confirm(user 抓狂時別跳問)
- **80% budget** 浮 toast「快超預算,N round 後自動收尾」

### 解不了的角落 case(承認)
| 問題 | 為何無法完美 | 我們能怎樣 |
|---|---|---|
| Off-topic drift | 需 LLM judge 不精準且燒 token | Convergence 偵測抓「沒進展」間接解 |
| 兩 agent ping-pong 對立議題不收 | 共識本來就有時收不了 | Majority done signal — 過半停就停 |
| LLM 鑽 termination signal 漏洞 | 模型不太會故意,但 prompt injection 可能亂發 `<TERMINATE>` | 需 N 個 peers 確認,單一不算 |
| User 出門忘了 swarm 還在跑 | 沒法 | budget cap $1 + wall_clock 1h 保險 |

承認 ~10% 角落 case 解不了,那是 swarm 本質難題,不是基建缺失。

---

## Tool concurrency 決策

### 問題
Coordinator fan-out 5 workers,可能同時對 same file Edit/Write/Bash。SDK
既有 `file_state_cache` 是 optimistic concurrency(mtime+hash 比對 → reject
+ 重 Read)。multi-worker 下出現新 race:N 個 workers 都拿 t0 snapshot,
寫入時只有 1 成功,其他 reject → 重 Read → 再撞 → 無限 race loser 燒 token。

### 走 D — 沿用 optimistic + 3 個 safeguard

| 方案 | 評估 |
|---|---|
| A. Per-pane file lock(pessimistic) | 鎖住卡 worker idle,token 浪費更兇 |
| B. Per-collab shared `file_state_cache` | SDK 改動大,效益不明顯 |
| C. Worker-specific subdir 強制 | 對「分工平行」超好,但「一起改同檔」做不到 |
| **D. Optimistic + 3 safeguards**(選這) | 90% 場景夠用,工程成本低 |

#### Safeguard 1:Coordinator UI 提示 leader 分工
fan-out 時顯預設提示:

> 💡 **best practice**:分工讓每 worker 負責不同 file / module。同檔並行容易撞 race。

教育,不強制。

#### Safeguard 2:同檔 race 連 3 次 → halt 該 worker
- `file_state_cache` reject 3 次同檔 → 該 worker auto halt
- Emit notification 給 leader:「@wX has 3 conflicts on `auth.py`, halted.」
- Leader 選 retry / kill / 重新分工

防 race loser 無限燒 token。

#### Safeguard 3:Destructive Bash 預設 dry-run
`rm` / `mv` / `sed -i` 等破壞性命令 worker 跑時:
- 預設先 dry-run(`echo 'would: rm file.py'`)
- 把預期 effect emit 給 leader
- Leader 同意才真執行
- 沿用既有 `permissions/` rules — 加幾條 default 規則即可
- User 可關「destructive dry-run」(Settings → Tools)

---

## 「實驗性」safe mode 決策

> Swarm 整個 mode 標「實驗性」,以下 safe mode + sidebar badge 加上後是
> **完整的「實驗性」對 user 的全部表面**。不另開「實驗性標示」section。

### 問題
Swarm 標實驗性但 user 知道也踩坑(N peers 共識要 `rm -rf workspace` 之類)。
標籤 + budget cap 是被動防衛,要主動。

### 走 — Safe mode default-on,disable destructive tools

**Safe mode 行為**:
- Swarm 啟動自動 disable:`Edit` / `Write` / `Bash` / `NotebookEdit`
- 允許:`Read` / `Grep` / `Glob` / `WebFetch` / `WebSearch` / `TodoWrite` / `AskPane`
- LLM 真實 call(要看互動 + 算 cost),只是無 side effect
- Swarm 在 safe mode 下**只能討論,不能做事**

### 為何 disable 而非寫 dry-run wrapper

| | A. 每 tool 寫 dry-run wrapper | **B. Disable destructive tools** |
|---|---|---|
| 工程量 | 大(每 tool 各做) | 小(沿用 disabled_tools 機制) |
| 完整度 | 完整 | 對「實驗 mode」夠 |

實驗 mode 本質是「看 swarm 怎麼互動」,不是「讓 swarm 改我 code」。**B 完美對應目標**。

### Settings toggle
```
☑ Swarm safe mode(預設開啟,推薦)
   實驗模式下自動 disable 寫檔 / 跑 shell 等 side-effect 工具。
   Swarm 只能讀檔 / 搜尋 / 互相討論,不會動到你的 workspace。
   想讓 swarm 真執行 → 關掉此選項(自負風險)。
```

關掉顯紅字警告 + 建議「budget cap 設低 + git clean state + 跑完不滿可 git reset」。

### 表面行為
- Swarm 啟動 sidecar 讀 `swarm_safe_mode_enabled` pref
- True → `disabled_set` 加 `{Edit, Write, Bash, NotebookEdit}`
- Pane 內 tool list 看不到那 4 個 tool(完整透明)

### Coordinator 不套用
Coordinator 不是實驗性,workers 本就該動手寫 code / 跑 test。**只 Swarm 套用**。

---

## 預設值總表(實驗模式的最終形)

| Setting | Coordinator | Swarm | 為什麼 Swarm 更嚴 |
|---|---|---|---|
| `safe_mode` | — | **ON** | 不會動到 workspace,純討論 |
| `budget_usd_cap` | 用 collab default | **$1** | 比 collab 嚴 4-5 倍 |
| `max_rounds` | — | **8** | swarm 該談完 |
| `max_messages_per_round` | — | **5** | N=3 peers + leader 已寬 |
| `per_agent_timeout` | 60s | **60s** | LLM turn 不超 30s,2× buffer |
| `wall_clock_max` | — | **1 hour** | 怕 user 出門忘了 |
| `convergence_check_every_n_rounds` | — | **2** | 每 2 round 跑 judge |
| `majority_done_threshold` | — | **N/2 + 1** | 標準多數決 |
| `worker_retention_days`(Coordinator) | **7** | — | per-collab 可改 |
| `cost_display_mode` | `with_workers` | — | 預設不誤導 |

---

## 工程量與切片

### Phase 0:SDK streaming refactor(前置,~5d)

| Item | 估時 |
|---|---|
| `run_coordinator` 改 async generator + event 型別 | 2d |
| `run_swarm` 同步改 streaming | 1d |
| SDK tests 全改 + 新加 streaming tests | 1d |
| README / changelog | 0.5d |
| Cancellation + error 處理 | 0.5d |

### Phase 1:Coordinator GUI(主菜,~12h)

| Item | 估時 |
|---|---|
| Schema(`mode` + worker columns)+ migration + RPC | 1h |
| Coordinator runner wire(走新 streaming API) | 2h |
| Coordinator UI(leader + workers split + stream routing + `worker_id` framing) | 5-6h |
| Cost 三層級顯示 + breakdown modal + pre-flight estimate | 2-3h |
| Mode picker / icon / i18n / 警告 banner | 2h |
| Tests | 3h |

### Phase 2:Swarm GUI(實驗性,~9h)

| Item | 估時 |
|---|---|
| Swarm runner wire(streaming API + message_bus 訂閱) | 3h |
| Swarm UI(message toast + per-pane counter + 終止條件 UI) | 3h |
| Safe mode toggle + sidebar 實驗 badge | 1h |
| Tests | 2h |

### 合計
**Phase 0 + 1 + 2 ≈ 5d + 12h + 9h ≈ 7-8 工作天**

### 切片次序
1. **先 ship Phase 0 完整**(SDK streaming refactor)— Phase 1/2 都靠這基礎
2. **再做 Phase 1**(Coordinator)— visibility win 最強,SDK runner 較成熟
3. **跑一陣子才 Phase 2**(Swarm)— Coordinator 上線後看真實使用率,真有 user 要再做

---

## 不會做的(out-of-scope)

- ❌ 三個 mode 各開獨立 sidebar tab(已在現有 IA 討論否決)
- ❌ Sidecar 自己 wrap streaming(B 方案 — 已決選 A 走 SDK 改)
- ❌ 每 tool 個別寫 dry-run wrapper(B safe mode disable 方案完成同樣目標,工程量 1/10)
- ❌ Per-collab shared `file_state_cache`(SDK 大改動,效益不明顯)
- ❌ Coordinator 套 safe mode(workers 本該動手,違背設計目標)

---

## 何時觸發實作

短期不做。**觸發訊號**(任一發生即啟動):
1. User 反映「Agent tool 結果都看不到中間,想看 workers 跑啥」
2. 公司 / 客戶具體 demo 需求(平行加速 N 個分析任務)
3. 研究類 user 想要 swarm sandbox 做 paper / demo

期間 advanced user 可直接用 SDK Python class 跑 Coordinator / Swarm — 不缺路。

---

## 看完繼續

- [`multi-pane-collaboration.md`](./multi-pane-collaboration.md) — 既有「並排 pane」mode 的設計筆記
- [`../features/multi-pane-collaboration.md`](../features/multi-pane-collaboration.md) — 已實作 pane mode
- [`../features/multi-agent.md`](../features/multi-agent.md) — SDK 內 Coordinator / Swarm 的 Python API
- [`README.md`](./README.md) — Roadmap 總覽

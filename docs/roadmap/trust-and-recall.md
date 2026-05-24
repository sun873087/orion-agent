# Trust & Recall — 下一輪 conversational polish

上一輪(已併入 main)做了一整套「降低非工程使用者門檻」的 LLM-enhanced UX:
title 自動摘要、banner / tool / error 解釋、follow-up 建議、訊息摘要、草稿保存、
cost ledger + breakdown、soul.md、`?` cheat sheet。

這份 doc 是**下一輪**,主軸換成兩條 narrative:

1. **Trust** — User 信任 Orion 必須看得到 Orion「知道什麼 / 送了什麼出去 / 不該看到什麼」
2. **Recall** — Soul.md 是「Orion 對你的人格認識」,但跨 session 的「對話脈絡延續性」還沒。讓 Orion 像「真的記得」而不是每次冷開始

對話「即時感」(C/D 系列)也順手收進來,但不是主軸。

> **設計原則**(承襲上輪):
> - **0 預設成本** — 任何 LLM call feature 預設 OFF / 主動觸發
> - **失敗 silent + fallback** — LLM 掛了不影響主體驗
> - **Prompt injection 防護** — 把 untrusted 內容用 `<untrusted>` tag 包,system prompt 明示忽略內部指令
> - **沿用單一 cheap model channel**(`compact_summary_provider`)— user 設一個 model 全部 enhancement 共用

---

## 已完成

| # | 功能 | 概念 |
|---|---|---|
| ✅ | **A1. 訊息「為什麼這樣回答」追溯** | 每個 turn 末 assistant message 加「🔎 為什麼?」按鈕,modal 顯本 turn 的 system_prompt(完整段落)+ tools list + model + token / cost。Sidecar `AuditStore` per-session ring buffer 100 turns,**content-addressed dedup**(prompts / tool_sets 各自 hash 表 + entries ref)— 同 session 內 system_prompt 跨 turn 幾乎不變,100 turn 從 ~1MB 壓到 ~30KB。持久化 DB JSON 跨 sidecar 重啟。已知 limitation:SDK 自動 inject 的 memory ranker / git status / per_turn_text 暫不在 audit 顯(需要 SDK 暴露 hook 才能 capture)。 |
| ✅ | **A2. 「我送了什麼給 LLM」隱私 audit** | 沿用 A1 audit modal,加新區段「📤 送 LLM 的訊息」。Sidecar 加 wire_buffer(獨立 ring buffer,maxlen 從 settings 來,default 1,範圍 0-20)snapshot 真實 `conv.state_messages`。Tool result 警示色 + 紅 badge「送了雲端」讓 user 一眼看出檔案內容真的離開機器。有 wire snapshot 顯精準版,沒有就 fallback `messagesBySession`(approximate badge)。Header 加「複製」按鈕一鍵 copy 完整 payload 給 user 離線 audit / diff。Settings 新「隱私 / 資料」section 集中控制(A1 read-only 說明 + A2 數量設定)。95% 對齊真實 wire(SDK auto-inject 的 memory / git_status 不含,modal 有 disclaimer)。 |
| ✅ | **B2. 跨對話搜尋 — 改成 LLM Tool**(原 spec sidebar UI → 改 Tool) | 設計 pivot:原本想做 sidebar semantic search,改成**對齊 Anthropic 的 `conversation_search` / `recent_chats` Tool 模式**(LLM 主動「想起」過去對話 > user 自己 sidebar 找)。後端 SQLite FTS5 virtual table 對 `messages.raw_text` 全文索引,trigger 自動 sync,BM25 ranker 毫秒級 query。新 cowork-specific tools:`ConversationSearch(query, limit?, scope?, session_id?)` 跟 `RecentChats(since?, until?, limit?, scope?)`,description 強調「實質性 keyword」對齊 Anthropic 引導語。`scope` 可選 `all`(預設)/ `project`(同當前 session 旗下 project)/ `collaboration`(同當前 multi-pane window 的 panes)/ `session`(僅當前 session)— LLM 無法自己取 project_id / collaboration_id,sidecar 從當前 session auto-fill(類似 schedule tool pattern)。Read-only,Settings → 工具 新「Recall」group default ON。Pure local — zero embedding model call / zero 外部 service / zero token cost。 |
| ✅ | **C1. 訊息品質 👍 / 👎(+ disliked 在 search 排除)** | 每個 assistant message action row 加 👍 / 👎 兩個按鈕(toggle 行為,同按鈕 = unset)。新表 `cowork_message_feedback`(message_id PK FK→messages.id ON DELETE CASCADE)+ 2 個 RPC。**👎 過的訊息在 SQL 層 hard-排除**(不靠 prompt 控制 — ConversationSearch SQL `LEFT JOIN cowork_message_feedback WHERE feedback IS NULL OR feedback != 'negative'`)。Tool description 內 NOTE 是給 LLM 的 hint(讓它知道「為什麼某些東西搜不到」避免無謂重試),**不影響穩定性**(SQL JOIN 100% 排除,LLM 根本看不到 disliked message 進結果)。順手把 sidecar `load_raw_messages` 改成回 message_id,UI hydrate 用真實 SDK id 取代隨機 hist id,讓 feedback 對應穩定。Optimistic UI + RPC fail revert。Tests 涵蓋 CRUD / invalid value / search 排除 / FK CASCADE。 |

---

## A. Trust — 透明度三件套(剩 A3)

### A3. 敏感資訊偵測 + 攔截

**痛點**:User 不小心 paste API key、密碼、access token 到對話框 → 整段 prompt
送雲端 → 即使 provider 不外洩,log / cache 仍是風險。

**做法**:Renderer pre-send 偵測 user message + tool input 內常見 secret pattern
(`AKIA[0-9A-Z]{16}` / `sk-[A-Za-z0-9]{20,}` / `gho_…` / `ghp_…` / `Bearer …`等),
跳警告 modal「偵測到可能的 API key — 確定要送嗎?要不要先 redact?」

**設計考量**:
- 純 regex,不打 LLM(0 成本)
- 可選「redact 後送」自動把 secret 換成 `[REDACTED-AWS-KEY]` placeholder
- Tool input 內也掃(LLM 自動 paste 路徑或環境變數時也防漏)
- Settings 加 toggle(預設 ON,「我知道我在做什麼」可關)
- 不存任何 secret(警告 modal 顯時也不寫 DB)

---

## B. Recall — 跨 session 脈絡延續

### B1. 「上次我們聊到哪」recap chip

**痛點**:每次開新 session 都從零開始。User 昨天聊到一半的東西,今天要 scroll
回去重看才繼續。Soul.md 是長期「人格認識」,recall 是短期「上次對話狀態」。

**做法**:Sidebar 上方或對話開頭顯一張小卡:
```
✨ 上次我們聊到...
  - 在 debug OAuth 重定向迴圈
  - 待辦:檢查 nginx X-Forwarded-Proto header
  [點繼續這個對話] [關閉]
```
LLM 看上次對話末段生 ~50 字 recap,寫進 session metadata。下次切回顯一次,
user click 跳轉 / dismiss。

**設計考量**:
- 走摘要 model,turn 結束時 fire-and-forget 生 recap(像 follow-up 同 channel)
- 只在 session **inactive > 2 小時**才顯(避免短時間切走又切回看到自己對話的 recap)
- Recap 內容存 `cowork_session_ext.recap_text` + `recap_generated_at`
- Cost 進 ledger 新 origin `recap`

### B3. 對話 → 自動 export markdown

**痛點**:有時對話跑出來的成果(計畫 / 教學 / 設計討論)值得存當文件,但 user
要手動 copy 出去整理。

**做法**:對話一段告一段落(每 5-10 turn 後)Orion 主動提示「這段內容看起來
像 X,要不要存成 markdown 進你的 workspace?」User 點 yes → Orion 摘要 + 寫檔
進 `<workspace>/notes/<auto-title>.md`。

**設計考量**:
- 預設 OFF — 主動提示偏擾,可能有 user 不喜歡
- Trigger 嚴格:turn 數 >= 5 + LLM 判斷「對話有獨立完整段落」才提示
- 寫的檔附 metadata header(session_id / created_at / 來源對話),方便回溯

---

## C. 對話品質回饋(剩 C2)

### C2. 對話 → todo 自動產生

**痛點**:User 跟 Orion 討論 N 個要做的事,自己要手動寫進 todo / TodoWrite。

**做法**:LLM 看完一段對話發現有 actionable items,主動「我看到這幾個 todo —
要不要幫你寫進 TodoWrite?」一鍵確認 / 編輯。

**設計考量**:
- 預設 OFF — 提示頻率高會煩
- 跟 follow-up 同 channel,但時機更晚(整個對話段落結束)
- 跟既有 TodoWrite tool 整合,不另開系統

---

## D. 即時感

### D1. Tool 執行一行狀態列

**痛點**:LLM 跑 tool 時 user 不確定在做什麼,只能展開 tool group 看 progress。

**做法**:Sidebar 底部或對話區頂部一條 thin status bar(只在 busy 時顯),
顯「正在讀 foo.py / 跑 3 秒了 / 5 個 tool 還在跑」。

**設計考量**:
- 純 UI,不打 LLM(0 成本)
- 沿用既有 toolCalls state,subscribe + render

### D2. Tool call inline citation

**痛點**:Assistant message 提到「我看過 foo.py」但 user 不知道實際是哪個 tool
call。

**做法**:LLM 回答內若提到檔名 / 路徑,自動 link 到對應 tool result row。
Hover 顯 tooltip 預覽,click 跳該 tool row。

**設計考量**:
- 需要 LLM-side 約定(在 message 內用某 marker 標 tool ref)或 renderer-side
  fuzzy match(從 message 抓 file path 對 tool calls)
- 後者較務實(不依賴 LLM 配合)

---

## 推薦優先順序

1. ~~**A1**~~ ✅ / ~~**A2**~~ ✅ / ~~**B2**~~ ✅ / ~~**C1**~~ ✅ — 已完成。C1 跟 B2 配合:disliked 訊息在 SQL 層 hard-排除,LLM 跨對話搜不到 user 標 👎 的回答
2. **A3**(敏感資訊偵測)— 純 regex 防護,投入最小,效果立即
3. **B1**(recap chip)— 跨 session 體驗大躍進,沿用既有 cheap LLM channel
4. **B3**(對話自動 export markdown)— Phase 2,沿用同 cheap LLM channel
5. **C2 / D1**(todo 自動產生 / tool 狀態列)— 純 polish,有空再做

---

## 不會做的(暫定)

- **AI 主動建議下個 action**(看到 user 沒打字 5 分鐘就提示)— 太擾人,不符
  「user 主導」原則
- **完整 voice agent**(OpenAI Realtime 那種 voice-to-voice)— 另一個 league
- **訊息 inline ghost text 補完**(Copilot style)— 中文 IME 雷區,工程量遠超預期

---

## 看完繼續

- [`README.md`](./README.md) — 整體 roadmap
- [`../architecture/design-decisions.md`](../architecture/design-decisions.md) — 已凍的設計決策

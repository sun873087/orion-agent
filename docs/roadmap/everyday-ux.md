# Everyday UX — 下一輪日常使用優化

上一輪 trust-and-recall(A1 audit / A2 wire / B2 search / C1 thumbs)併入 main
後,試圖再往「LLM 主動行為」推(C2 對話 → todo / recap chip / 自動 export 提示)
**user 都退回了**。教訓:

- ❌ LLM 主動提示類 → user 嫌煩
- ❌ 另開 panel 複製既有功能 → over-engineered
- ❌ 替既有 tool 重造輪子(C2 想另存 todo 但 TodoWrite 已經能做)

這份 doc 是**重新從 user 真實痛點出發**的下一輪,主軸偏「日常 navigation /
cost 控制 / 小事一鍵搞定」,**不碰 LLM 主動建議路線**。

> **設計原則**(承襲上輪 + 新教訓):
> - **0 預設成本** — 任何 LLM call feature 預設 OFF / 主動觸發
> - **失敗 silent + fallback** — LLM 掛了不影響主體驗
> - **不另開 panel 複製既有功能** — 既有 TodoWrite / Sidebar 能做的就不另起爐灶
> - **不做 LLM 主動提示** — user 主導,LLM 只在 user 明確 ask 時動作
> - **不依賴 LLM 行為合作** — 設計要假設 LLM 會偷懶,UI 永遠有 user override

---

## 主軸候選(4 個方向,各自獨立)

### 🚀 方向 A:Cmd+K 全局 command palette

**痛點**:目前操作要 hop 多個 panel — 切 session 開 sidebar、切 model 進
Settings、切 workspace 進 project settings、跑 slash command 要記名字。

**做法**:任何地方 `Cmd+K` 浮出 command palette,fuzzy match 集中 N 種動作:
- 搜 session(已有 sidebar search,提到全局)
- 搜 message 內文 across sessions(走既有 ConversationSearch / sidebar search)
- 切 model
- 切 workspace
- 開 Settings 特定 section
- 跑 slash command

**為什麼有用**:現代 chat app 標配(Claude.ai / Cursor / Linear 都有)。keyboard-
first user 一鍵到位。
**投入**:~4-5 小時(全局 hotkey + modal + fuzzy match + 各 source provider 整合)
**0 LLM cost**(純 UI)

---

### 💰 方向 B:Cost 防爆 — 送出前估算

**痛點**:目前 cost 是**事後看** — send → 收費 → 才在 sidebar 看到。User 之前
直接罵「使用者很在意成本」。

**做法**:user 按 send → renderer 先用 tiktoken 粗估 prompt token + history → 算
USD → 超 threshold 跳 modal「這次估 $X,確認嗎?」確認才實際 RPC。

**設計考量**:
- Threshold 預設 $0.10 / single send,Settings 可調(0 = 永不問)
- 同時偵測「剩餘 budget < 估算」也跳 modal(預防超 budget cap)
- Modal 顯 token breakdown(prompt / context / history)讓 user 知道哪部分肥
- 純 client-side,不打 sidecar(estimate 在 web worker 跑避免卡 UI)

**為什麼有用**:把成本焦慮從「事後懊悔」推到「事前可選擇」。
**投入**:~3 小時(tiktoken bundle + estimator + modal + Settings)
**0 LLM cost**(純 client estimate)

---

### 📌 方向 C:Message bookmark / Pin

**痛點**:long session 內某段重要結論(設計決策 / 步驟總結 / 程式碼片段),user
之後想找要 scroll 或 search。

**做法**:任 message 右上 📌 bookmark 圖示 → 點 toggle pin → Sidebar 加「⭐
Pinned」section 列**跨 session** bookmarked messages(顯訊息片段 + session 標題)。
Click → 跳到該 session 該 message。

**設計考量**:
- 跟 👍/👎 feedback 完全分開(品質 vs 重要性)
- 新表 `cowork_message_bookmarks`(message_id PK FK → messages.id ON DELETE CASCADE)
- Pin 不影響 LLM 行為(純 user UI),不像 feedback 會排除 search
- Sidebar pinned section 可 collapse,預設 collapsed

**為什麼有用**:長對話的 anchor — user 找重要內容不必走 search → 看 snippet → 點開。
**投入**:~3-4 小時(新表 + 2 RPC + sidebar section + MessageBubble 按鈕 + i18n)
**0 LLM cost**

---

### 🔁 方向 D:換 model 重試 / 並排比對

**痛點**:目前 regenerate 用同 model 重跑。實際痛點是「**這 model 沒用,換 claude
試試**」— 但要去 Settings 改 model + regenerate,而且新答案蓋掉舊答案沒法比對。

**做法**:上條 user message 旁加「🔄 換 model 重試」按鈕 → dropdown 列當前
可用 models → 選 → 該 model 跑同 prompt → **結果並排顯示**(原本回答右邊插一條
新 model 的回答,標 model 名 + token cost)。

**設計考量**:
- 兩個回答都 keep,user 可勾哪個是「正確答案」(寫進 cost ledger 標 origin?)
- 並排 UI 在窄 viewport 退成 tab 切換
- 「換 model」用的是當下 turn 的 wire payload,不是重 prepare context — 對齊
- 多 model 跑 = 多 cost,Settings 加「換 model 是否預先警告」toggle

**為什麼有用**:Anthropic / OpenAI / etc 強項不同,user 想 A/B 而不必另開新 session 重打字。
**投入**:~5-6 小時(UI 並排 + branch render + cost ledger 新 origin + Settings)
**有 LLM cost**(每次按真的多跑一次)

---

## 小 polish 池(每個 < 1 小時)

| # | 功能 | 痛點 |
|---|---|---|
| **P1** | Sidebar 底部「最近 7 天 cost」chip | 整週花多少看不到,要點 session 一個個算 |
| **P2** | Session 加 tag / label(work / research / etc),sidebar 可 filter | 100 條 session 找不到分類 |
| **P3** | Conversation 「📄 一鍵 export markdown」按鈕(對話頂部) | 對話成果想 backup / share 要手動 copy |
| **P4** | 輸入框「📋 paste 智慧偵測」— 偵測 paste 是 code → 自動加 ```language fence | 貼 code 還要手動圍 backtick |
| **P5** | Tool result 卡片「複製這條結果」一鍵 copy | 想抓某個 tool output 要全選 |
| **P6** | Settings 「重設所有快取 / cache」按鈕 | 行為怪要重啟,沒地方 clear cache |
| **P7** | LLM busy 時 Header 呼吸燈 / 動 spinner | busy 狀態現在太微弱看不出 |

---

## 推薦優先順序

1. **A(Cmd+K)** — everyday navigation 最大躍進,純 UI 0 cost,長期 ROI 最高
2. **B(Cost 防爆)** — 直接打 user 「在意成本」的痛點,純 client-side
3. **P1 / P3 / P5** — polish 池高 ROI 三個(成本 chip / export / 複製 tool result)
4. **C(bookmark)** — long session 用戶需要,但 short session 用戶感覺不到
5. **D(換 model 重試)** — 工程量最大,但**有人會 daily 用**;留 phase 2

---

## 不會做的(明確 out-of-scope)

承襲 C2 退回的教訓:

- **LLM 主動建議下個 action / 對話自動 export 提示 / recap chip** — 上輪 trust-
  and-recall 試過,user 退回,確認「user 主導」原則重於 LLM 主動
- **另開 panel 重複既有功能** — TodoWrite 既有 panel 就夠,不再造「使用者 todo
  panel」這種重複系統
- **完整 voice agent / 訊息 inline ghost text 補完** — 工程量遠超預期 / 中文 IME 雷區
- **AI 主動建議專案組織 / session merge / auto-tag** — 都是 LLM 主動類,先擱

---

## 看完繼續

- [`README.md`](./README.md) — 整體 roadmap
- [`../architecture/design-decisions.md`](../architecture/design-decisions.md) — 已凍的設計決策
- [`multi-pane-collaboration.md`](./multi-pane-collaboration.md) — multi-pane / dispatch

# Conversational UX polish — 給非工程使用者也用得順

Cowork 的對話體驗仍偏「工程使用者懂的工具」(banner 顯 `Glob *`、
session title 寫整段原 prompt、tool error 是 stack trace)。這份 doc 收
**讓非工程使用者也舒服**的優化想法,分**已完成**跟**接下來方向**。

> 設計原則:**0 預設成本 / 看不懂才付費**。便宜 LLM 小模型(沿用 Settings
> 的「摘要 model」)是主要工具,user opt-in 才花錢。

---

## 已完成 — 本 session(2026-05)

| # | 功能 | 概念 |
|---|---|---|
| ✅ | **Session title 改 LLM 自然摘要** | 第一個 turn 寫規則 quick title,turn 結束背景跑 LLM 改成 ~15 字自然摘要。仿 claude.ai 兩段式。CAS 更新避免覆掉 user 手動 rename。 |
| ✅ | **Banner 翻譯規則化 + LLM 解釋按鈕** | 「允許 Orion 執行:Glob *」→「允許 Orion 列出此資料夾的所有檔案」(13 個常見 tool 規則翻譯)。Bash 等規則 cover 不到的場景:加「✨ 看不懂?讓 AI 解釋」按鈕,點才 LLM call,prompt injection 防護用 `<untrusted>` tag。 |
| ✅ | **Follow-up 建議句 chip(Tab 採用)** | 每 turn 完背景跑 LLM 猜 3 條使用者可能想接著問的話,輸入框上方顯 chip。Tab / 點採用第一個。Settings + 輸入框 toolbar pill 雙開關控制(預設 OFF,有 token 成本)。chip 寬度上限 + truncate + tooltip 避免長句撐爆 row。 |

> 共用技術 channel:`compact_summary_provider`(user Settings 的「摘要
> model」)+ `reasoning_effort=minimal` + `max_tokens=1024` + 不帶
> temperature(gpt-5 系列拒收)。三個 feature 都走同一個 cheap LLM 通道,
> user 設一個 model 三個都受益。

---

## 接下來方向

按「投入 / 痛點」排序,推薦的優先在前。

### A. Tool error 也加「不懂?讓 AI 解釋」(推薦先做)

**痛點**:Tool 跑失敗時,error 通常是 stack trace / shell exit code /
JSON parse error,非工程使用者看不懂,只知道「壞了」。

**做法**:沿用 `tool.explain` RPC 同模式,在 ToolCallGroup 的 error state
旁加按鈕「✨ 看不懂?讓 AI 解釋」。LLM 收 tool name + input + error 訊息,
吐一句人話「為什麼失敗 + 該怎麼處理」。

**預期實作**:~70% 已有(RPC 通道、UI pattern、prompt injection 防護)。
擴 RPC `tool.explain` 接 `error?: string` 參數即可。

### B. vague prompt 補問

**痛點**:User 打「寫個函式」/「幫我看一下」這種太抽象的 prompt,LLM 只能
猜或反問,user 體感「為什麼還要再問一次」。

**做法**:送出前先用小 LLM 判斷「具體性夠不夠」,不夠就 banner 提示「Orion
還不太清楚:這個函式是哪個語言?哪個函式?有什麼需求?」附三個追問 chip,
user 點 chip 補資訊再送。

**設計考量**:
- 跟 follow-up 同 channel,但時機是 **pre-send 不是 post-turn**
- 預設 OFF(額外 LLM call)
- 對於明顯具體的 prompt(>30 字、含程式碼、含 path)自動 skip 不打
- 跟 slash command / `@` mention 互斥(那些是明確指令)

### C. 訊息超長一鍵摘要

**痛點**:Assistant 回 800+ 字的長 reply,user 只想知道結論。

**做法**:訊息頂端 chip「✨ 摘要這則」,點下去 LLM 給 3 行 bullet。摘要結果
cache 在訊息 metadata,不重複 call。

**設計考量**:
- User 主動觸發,零預設成本
- 用 cheap model(同 Settings 摘要 model)
- 摘要結果可摺疊隱藏 / 重新生

### D. 輸入框草稿自動保存

**痛點**:user 打到一半切去看別的 session,回來輸入框內容丟了。

**做法**:Per-session 輸入框 text 寫進 zustand store(persisted localStorage),
切回 session textarea 自動 hydrate。送出 / 顯式清空才 drop。

**設計考量**:
- 不寫 SQLite,localStorage 即可(不必跨機器同步;切了 machine 草稿丟了不痛)
- Attachments / textAttachments 是否 persist?暫不(blob 太大 / 複雜)
- 跟 follow-up chip 互動:有草稿時 chip 不顯(沿用現邏輯 `text.length === 0`)

### E. assistant 訊息「再答一次」(regenerate variant)

**痛點**:對 AI 某條回覆不滿意,要 fork 才能換答案(fork 會建新 session,
重)。

**做法**:assistant message 旁邊一鍵「換個說法」 → truncate 該訊息之後,
從上一條 user prompt 重新生(不改 user prompt)。跟現有 fork 不同 — 不
分支,直接覆蓋。

**設計考量**:
- 跟現有「重新生成」按鈕區別清楚(目前是 `regenerate`,但好像沒在所有
  訊息上 surface — 要先 audit)
- variant 模式可選「more concise / more detail / 換個 model」

### F. `?` 快速鍵 cheat sheet

**痛點**:Enter / Shift+Enter / Tab / Cmd+K 等鍵綁定 user 不知道。

**做法**:按 `?` 鍵跳 modal,列出所有快捷鍵分組顯示。`?` 在輸入框輸入時
不要觸發(只在無 focus / 在 sidebar focus 時)。

**預期實作**:純 React 元件,~100 行內。沒 LLM call,純 polish。

### G. 全域 Command Bar(Cmd+K)

**痛點**:切 session 要點 sidebar、跳 settings 要點齒輪、跑 slash 要打
`/`。多個入口。

**做法**:`Cmd+K` 開全域搜尋框,fuzzy match:
- Session(title / 內容)
- Settings 頁(各 section)
- Skill 名稱
- Slash command

Enter 跳 / 執行。

**靈感**:Linear / VS Code 的 command palette。

**設計考量**:
- Skill / slash 已有 popover,Cmd+K 是「跨類型」的合一入口
- 不取代既有 sidebar 搜尋(Cmd+F 搜對話內容),Cmd+K 是「跳到 X」、
  Cmd+F 是「在這找 X」

### H. 成本 breakdown

**痛點**:User 開了 follow-up / tool explain / title gen 之後,看不到
「這些功能各佔多少 cost」。只看 total 不夠透明。

**做法**:右側 panel 累積 cost 改成可展開,拆細:
```
本 session 累計  $0.0234
├ 主對話       $0.0210
├ 摘要         $0.0008(auto-compact × 1)
├ Follow-up    $0.0012(× 6 turns)
├ Title 生成   $0.0002(× 1)
└ Tool explain $0.0002(× 1)
```

**設計考量**:
- 需要 sidecar `_track_usage` 標 origin label(`chat` / `summary` /
  `follow_ups` / `title` / `explain`)
- 預設摺疊,user 點才展開(避免吵)
- 跟 Budget cap 整合 — exceeded 時提示「主對話超 cap,但 follow-up 只佔 5%
  可繼續開」

### I. 自動 user profile 學習

**痛點**:多次對話後,LLM 還是不知 user 偏好的技術棧 / 語氣 / 回覆長度,
每次都要重提醒。

**做法**:Sidecar 觀察對話模式(常用語言 / framework / 偏好的 reply 長度
/ tone),寫進 reference memory(`~/.orion/users/<u>/memory/profile.md`)。
LLM 對話自動帶 inject。

**設計考量**:
- **侵犯感大**,必須:
  1. 預設 OFF
  2. UI 顯示「Orion 觀察到你...」可審閱 / 拒絕 / 編輯
  3. 觀察前要 N turns(避免單次對話偏誤)
- 寫進 memory 後走既有 ranker,LLM 看上下文時自動 retrieve
- 跟 manual memory edit 不衝突(user 改了 profile.md sidecar 不蓋掉)

---

## 共用設計原則(留給 future maintainer)

1. **0 預設成本** — 任何 LLM call 的 feature,預設 OFF 或 user 觸發。Settings
   有 toggle,toolbar 有快捷 pill(若高頻使用)
2. **失敗 silent + fallback** — LLM 掛了 / 沒設摘要 model / API 額度爆 →
   不影響原體驗,只是少了 enhancement。Stderr log 留診斷
3. **Prompt injection 防護** — 任何把 tool input / 對話內容塞給 LLM 的場景,
   用 `<untrusted>...</untrusted>` tag 包住 + system prompt 明確指示忽略內部
   指令
4. **沿用「摘要 model」channel** — user 設一個 cheap model,所有「enhancement
   LLM」共用,不要每個 feature 都讓 user 重設 provider/model
5. **gpt-5 reasoning model 規格** — `reasoning_effort=minimal` +
   `max_tokens=1024` + 不帶 `temperature`(三條缺一不可,踩過坑)

---

## 不會做的(暫定)

- **Inline ghost text(Copilot-style 補完)**:中文 IME composition state
  在跨平台行為不一致,debounce + composition gate 工程量遠超預期。如果做也
  該是英文 input 為主的場景再來考慮
- **AI 自動發訊息(主動推送)**:打破「user 主導」原則,容易煩
- **Voice-based UX(完整)**:OpenAI Realtime 出來後可以試,但目前 STT/TTS
  已夠 — 完整 voice agent 是另一個 league

---

## 看完繼續

- [`README.md`](./README.md) — 整體 roadmap
- [`../features/cowork.md`](../features/cowork.md) — Cowork app 既有功能
- [`../architecture/design-decisions.md`](../architecture/design-decisions.md) — 已凍的設計決策

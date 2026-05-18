# Cowork 功能 wishlist

Cowork 接下來想做 / 必須做 / 競品有的功能 brainstorm。每條都還不是 phase
plan — 確認要做的條目再轉成 `plans/<NN>-<name>.md` 走正式流程。

依「不做沒辦法發布 / 用 10 分鐘會抱怨缺 / 用 1 小時會發現缺 / 補強」四層分類。

最後一節列「我建議的優先順序」假設目標是 **v1 release 給外部 user**。

---

## 🚨 必須(不做沒辦法發布)

| Feature | 為什麼 |
|---|---|
| **PyInstaller 打包 + electron-builder cross-platform**(.app / .exe / .AppImage)| 目前只能 `pnpm dev`,沒法給 non-dev user 用 |
| **macOS notarization / Windows code signing** | 沒簽 Gatekeeper / SmartScreen 直接擋 |
| **Auto-update**(`electron-updater`)| 一旦發布,bug fix / feature update 沒辦法推 |
| **API key validation**(Settings 加「測試連線」按鈕)| 目前 key 設錯只在第一次 send 才知道,初次 onboarding 摸不著 |

---

## 🔥 強烈想要(user 用 10 分鐘會抱怨缺)

| Feature | 痛點 |
|---|---|
| **Edit / Bash preview + dry-run**(寫檔前顯 diff,LLM 跑 destructive Bash 前顯 command + dry-run)| 現在 LLM 直接動手,不可逆操作 user 沒攔截窗口 |
| **整輪 undo**(rollback last turn 含 file edits)| AI 做錯事目前只能手動 git revert / fs 修。需要 file_state_cache 記 before/after |
| **Diff viewer inline**(Edit 工具結果顯實際 unified diff,不是「Edit succeeded」)| 看不到 AI 改了什麼 |
| **Cost cap / token budget per session**(超過 $X 自停)| Loop / Agent / autonomous workflow 沒 budget 守容易燒錢 |
| **Per-session cost dashboard**(累積 token + $)| `/context` 只顯當前 window 用量,沒累積花費 |
| **檔案直接拖入對話**(drop file → 自動 inject content + path 進 system context)| 目前要 `/add-files` 或叫 LLM Read,user 手感差 |
| **`@` mention**(`@file:src/foo.ts` / `@skill:debug` / `@symbol:Conversation.send`)| 比叫 LLM 用 Grep 找快 10 倍,Cursor 等都有 |
| **空 chat quick prompts**(empty state 顯「試試這個」範例)| 首次使用者面對空白頁不知道怎麼開頭 |
| **歷史對話 fork**(從某 turn 開分支試另一條路)| 想嘗試不同 approach 又不想失去原 thread |
| **First-run wizard**(provider key → model → workspace → 完成)| 目前 Settings 找半天 |

---

## 💡 強競爭力(用 1 小時會發現缺)

| Feature | 為什麼想要 |
|---|---|
| ~~**Local model support**(Ollama / LM Studio)~~ ✅ **Phase 31-L 完成 — Ollama native** | 隱私 / 離線 / 大量 cheap inference。LM Studio 待補(走 OpenAI-compat 路線,類似 work) |
| **Side-by-side 模型對比**(同 prompt 跑兩 model 並列)| 評估、debug、ensemble decision |
| **`@codebase` 語意搜尋**(vector embed,LLM auto-pull 相關 context)| 大 monorepo 不靠 Grep 找,效率倍增 |
| **MCP server marketplace / 1-click install**(從 registry 抓 server config)| 目前要手編 `~/.orion/mcp.json`,新用戶完全不知道 |
| **Conversation 分支樹視覺化**(配合 fork 看分支 / 比較)| 跟 fork 配合 |
| **Snippets / saved prompts**(常用 prompt 一鍵塞)| 重複工作必備 |
| **TTS 對話聽 / 唸出 LLM 回應**(STT 已有,反向)| 開車 / 走路 / 多工聽 |
| ~~**Multi-window**(同時 2 個 conversation 並列)~~ ✅ **Phase 31-M 完成,改為背景多 session**(切走的 session 仍在跑,sidebar 顯轉圈圈,最多 N=5 並發可設) | 現在切 session 看不到另一個 |
| **Reasoning thinking expandable**(`<thinking>` 區塊收摺 / 展開)| Sonnet 4.7 等 reasoning model 有用 |
| **Tool call 失敗 retry 按鈕** | 不必再叫 LLM 重 propose |

---

## 🛠 robustness / quality of life

| Feature | 為什麼 |
|---|---|
| **Backup / restore**(整個 cowork.db + ~/.orion/ export 成 zip / restore 回來)| 換機器 / 災難復原 |
| **多 device 同步**(opt-in iCloud / Dropbox / WebDAV)| 桌機 + 筆電切換 |
| **Offline detection UI**(API 連不上明確顯示)| 目前 silent fail |
| **Rate limit ETA / queue UI** | 撞限制 user 不知道在等什麼 |
| **Keyboard shortcut overlay**(`Cmd+/` 顯所有快捷)| 探索 / 教學 |
| **Plan mode OS notification**(AWAITING 時不在 app 內也通知)| Plan submit 後 user 切去別處,回來才看到 — OS 推一下 |
| **FTS5 全文搜尋**(目前 in-memory,大 history 慢)| 規模一大會卡 |
| **HTTP archive(HAR)export of Browser session**(debug 用)| Browser tool 跑壞 user 沒辦法 inspect |

---

## 🤔 還可以想的(沒 strong 推薦,但有想到列著)

- **AI 對話標籤 / category**(work / personal / experimental,sidebar filter)
- **匯出 plan_file 為獨立 .md 給 git commit**
- **Skill marketplace**(從 GitHub repo 一鍵 import 別人寫的 SKILL.md)
- **Conversation review checklist**(LLM 完成任務後自跑 self-check)
- **`/replay` — 把成功 workflow 自動提煉成 skill**(有 `skillify` 了,更自動化版本)
- **iPad / iOS companion app**(走 chat-api 當 consumer,不是 Electron)

---

## 🎯 我建議的優先順序

假設目標是 **v1 release 給外部 user**:

1. **API key validation 按鈕**(0.5 day)— onboarding 立刻順
2. **檔案拖入 inject**(1 day)— UX 立刻變現代
3. **Edit diff viewer inline**(1 day)— 信任度大幅 ↑
4. **First-run wizard**(1 day)— 新用戶 retention 關鍵
5. **Cost cap + per-session dashboard**(1.5 day)— Loop / Agent 才敢放手用
6. **PyInstaller + electron-builder**(2-3 day)— 真正能發布
7. **macOS notarize / Windows sign**(1 day setup + ongoing)
8. **Auto-update**(1 day)
9. **`@` mention**(2 day)— 中度工作量但回報巨大
10. **整輪 undo**(2-3 day)— 需要 file_state_cache snapshot

合計 ~14 工程天 + sign / cert 取得時間(可能要等 Apple Developer ID
audit),約 3-4 週可以發 v1。

---

## 已做過(對照)

不在此清單中、但已存在的 Cowork feature 完整列表見 [`../features/cowork.md`](../features/cowork.md) 「主要功能」段。
Phase 31 累積實作的:對話管理 / 排程 / Loop / Project / 技能系統 / 內建工具控制 / 路徑統一 / 桌面 OS 整合 / Slash commands / Plan Mode / Agent tool(default disabled)/ ...

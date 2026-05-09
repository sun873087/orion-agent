# Optional Features 附錄

不是 Phase 0-15 所有 phase 都必做。本附錄列**選擇性 / 進階特性**,你可挑要的補。

## 速覽表

| 特性 | 對應 TS | 行數 | 何時需要 | 建議優先 |
|---|---|---|---|---|
| [IDE 整合](#1-ide-整合) | `utils/ide.ts` | 1494 | 做 VS Code / JetBrains plugin | 中 |
| [Tips / Help 系統](#2-tips--help-系統) | `services/tips/` | 760 | 新 user onboarding | 中 |
| [MagicDocs(自動文件)](#3-magicdocs-自動文件) | `services/MagicDocs/` | 381 | 想做 code → docs 工具 | 低 |
| [PromptSuggestion + Speculation](#4-promptsuggestion--speculation) | `services/PromptSuggestion/` | 1514 | 提升輸入體驗 | 中 |
| [Notifier(桌面 / 推送通知)](#5-notifier) | `services/notifier.ts` | 156 | 長任務需要通知 | 中 |
| [Away Summary(離開摘要)](#6-away-summary) | `services/awaySummary.ts` | 74 | 長執行 agent 場景 | 低 |
| [DXT plugin format](#7-dxt-plugin-format) | `utils/dxt/` | — | 接 Anthropic plugin 生態 | 低 |
| [Computer Use(電腦操作)](#8-computer-use-電腦操作) | `utils/computerUse/` | — | 桌面 agent(scope 外) | 跳 |
| [Voice 輸入](#9-voice-輸入) | `services/voice*` | — | 語音介面 | 跳 |
| [Teleport(SSH 遠端 session)](#10-teleport-ssh-遠端-session) | `utils/teleport/` | — | 已被 Phase 7 sandbox 取代 | 跳 |
| [Bridge / Remote(CCR 整合)](#11-bridge--remote-ccr-整合) | `bridge/` `remote/` | 32+5 檔 | 你自己就是 server | 跳 |
| [Auto-update / 版本檢查](#12-auto-update) | (散落) | — | npm 套件用,SaaS 不需 | 跳 |

---

## 詳細說明

### 1. IDE 整合

**對應**:`src/utils/ide.ts`(1494 行,大!)+ `src/utils/idePathConversion.ts`

**做什麼**:讓 VS Code / JetBrains plugin 透過 protocol 連到 agent。Plugin 可:
- 把當前 cursor / selection / open files 傳給 agent
- agent 直接 inline 改 IDE 中的檔案
- diagnostic / hover 結果顯示在 IDE

**實作建議**:
- 用 LSP-like protocol(JSON-RPC over stdio)
- Plugin 端實作為 VS Code extension
- Agent 端在 FastAPI 加 `/ide/connect` endpoint

**何時做**:你發現 user 強烈要求「在 IDE 裡用 agent 而非 web chat」。

**簡化路徑**:Phase 6 已有 WebSocket /chat/stream,IDE plugin 直接用同 endpoint 即可,功能差別在 plugin 端(extract IDE state 自己處理)。**不需要 1494 行 port**。

---

### 2. Tips / Help 系統

**對應**:`src/services/tips/tipRegistry.ts`(686 行)、`tipScheduler.ts`(58)、`tipHistory.ts`(17)

**做什麼**:在合適時機(對話空閒、新功能上線、user 重複某動作)推 tip 訊息:
> 💡 Tip: You can use `/clear` to reset the conversation.

**實作建議**:
- `tips/registry.py`:tip 列表 + matcher conditions
- `tips/scheduler.py`:何時觸發(conversation idle、user behavior pattern)
- `tips/history.py`:per-user tip seen 紀錄(避免重複)

**何時做**:product-led growth 階段,提升 retention。

**Python skeleton 摘要**:

```python
@dataclass
class Tip:
    id: str
    text: str
    triggers: list[str]  # "first_session" / "after_5_messages" / ...
    once_per_user: bool = True


TIPS = [
    Tip(id="slash_clear", text="💡 Use /clear to reset", triggers=["after_5_messages"]),
    # ...
]


async def get_next_tip(user_id, conv_state) -> Tip | None:
    seen = await load_seen_tips(user_id)
    for tip in TIPS:
        if tip.id in seen and tip.once_per_user:
            continue
        if any(matches_trigger(t, conv_state) for t in tip.triggers):
            await mark_seen(user_id, tip.id)
            return tip
    return None
```

---

### 3. MagicDocs(自動文件)

**對應**:`src/services/MagicDocs/magicDocs.ts`(254 行)、`prompts.ts`(127)

**做什麼**:讓 agent 把整個 codebase 轉為文件。給定 repo,輸出:
- README
- API reference
- Architecture overview

**實作建議**:
- 用 sub-agent(Phase 1)spawn 一個 docs writer
- 多階段:explore → outline → draft → polish
- 整合到 `/docs` slash 命令

**何時做**:如果你的產品定位是「給 user 用 agent 自動文件化 codebase」。否則低優先(這是個獨立功能)。

---

### 4. PromptSuggestion + Speculation

**對應**:`src/services/PromptSuggestion/promptSuggestion.ts`(523)+ `speculation.ts`(991!)

**做什麼**:兩件事:

**(a)Prompt suggestion**:user 打字時,顯示「You might want to ask: ...」自動補。

**(b)Speculative execution**(big!)
- agent 預測 user 下一步可能的 prompt
- 提前 spawn 一個 fork 跑那個預測
- user 真的問了 → 直接給 cached 結果(快)
- user 沒問 → 丟掉 fork

**速度提升大,但 token 成本上升**(~30%)。

**實作建議**:
- `suggestions/predictor.py`:用 Haiku 預測 user 下一步
- `speculation/runner.py`:fork agent 預先跑
- `speculation/cache.py`:cache 預測結果
- 整合 Phase 11 input pipeline

**何時做**:user 抱怨「agent 回應慢」。或 SaaS 想差異化(其他 chat 沒這個)。

**注意**:speculation 對沒命中的浪費 token。要評估 P(命中)× 加速 vs 浪費 token 成本。

---

### 5. Notifier

**對應**:`src/services/notifier.ts`(156 行)

**做什麼**:長任務(背景 task / 多 turn agent)完成後通知 user:
- 桌面通知(macOS / Linux / Windows)
- 推送通知(web push notification)
- email

**實作建議**:
- `notifier/desktop.py`:用 [`plyer`](https://plyer.readthedocs.io/) 跨平台桌面 notif
- `notifier/web_push.py`:用 [`pywebpush`](https://github.com/web-push-libs/pywebpush) Web Push protocol
- Phase 6 WebSocket 加 `notification` event 推前端

**何時做**:有長任務 user case(`Bash run_in_background` / cron / coordinator)。

---

### 6. Away Summary

**對應**:`src/services/awaySummary.ts`(74 行)

**做什麼**:user 離開瀏覽器一段時間,agent 跑完任務後,user 回來時看到:

> Welcome back! While you were away, the agent:
> - Reviewed 3 PRs
> - Fixed 2 lint warnings
> - Deployed to staging

**實作建議**:
- 跟 AgentSummary(Phase 15)機制一樣,但 trigger 不同
- WebSocket reconnect 時觸發
- 用 sideQuery 摘要離開期間的工作

**何時做**:有 background agent 跑 use case。否則低優先。

---

### 7. DXT plugin format

(已在 Phase 14 簡單寫過,本附錄補完整)

**完整 DXT 規範**:
```
my-plugin.dxt(zip 檔)
├── plugin.json     # manifest
├── icon.png         # 顯示用
├── README.md
├── skills/
│   ├── *.md
├── hooks/
│   ├── *.sh / *.py
├── mcp/
│   ├── server.py
└── signatures/      # 未來:簽名
    └── plugin.sig
```

**實作建議**:
- `plugins/dxt_install.py`:解 zip + 驗 manifest + 接 Phase 8 plugin loader
- 簽名驗證(future,目前可 skip)

**何時做**:接 Anthropic 官方 plugin 生態(若有公開 marketplace)。

---

### 8. Computer Use(電腦操作)

**對應**:`src/utils/computerUse/`(目錄)

**做什麼**:Anthropic 的 Computer Use feature — 讓模型:
- 截圖(看螢幕)
- 滑鼠 / 鍵盤操作
- 跨應用控制

**為何跳**:你的 chat UI 是 web 服務,**模型不能控制 user 的電腦**(也不該)。Computer Use 適合桌面 app(`claude-desktop`),不是 SaaS 場景。

如果你要做桌面客戶端(Electron),才需要這層。

---

### 9. Voice 輸入

**對應**:`src/services/voice.ts` / `voiceStreamSTT.ts` / `voiceKeyterms.ts`

**為何跳**:語音輸入是前端能力(Web Speech API / MediaRecorder),不是 agent 能力。前端轉文字後送 chat 即可。

如果你要服務端 STT(Speech-to-Text),用獨立服務(Whisper API / 自架),**不該耦合在 agent 框架內**。

---

### 10. Teleport(SSH 遠端 session)

**對應**:`src/utils/teleport/`(目錄)

**做什麼**:CLI 模式下,user 打 `claude --teleport <host>` 把 agent 移到遠端 SSH 連線執行。

**為何跳**:你的 sandbox(Phase 7 / 7b)已經是「遠端執行環境」。teleport 對 SaaS 沒額外價值。

---

### 11. Bridge / Remote(CCR 整合)

**對應**:`src/bridge/`(32 檔)+ `src/remote/`(5 檔)

**做什麼**:Claude Code CLI 連到 Anthropic 雲端的 CCR(Claude Code Runner)— 讓 web 端 chat 控制 user 本機 CLI。

**為何跳**:你**自己就是 SaaS server**,不需要橋接 Anthropic CCR。Phase 6 的 WebSocket 已是同類功能(web 端控制 server 端 agent)。

---

### 12. Auto-update / 版本檢查

**對應**:Claude Code CLI 啟動時 check npm。

**為何跳**:SaaS 環境 server 自己控制 deploy 流程,client(web 前端)用 service worker 或 build hash 檢查。**沒有 npm 套件版本概念**。

---

## 統整建議

對於**chat UI on K8s** 場景的優先序:

```
做(Phase 0-15 已涵蓋或附錄補):
   ✅ Phase 0-15 全部
   ➕ Tips / Help 系統(若做 product-led growth)
   ➕ Notifier(若有長任務)
   ➕ PromptSuggestion(若想差異化體驗)

選擇性:
   △ IDE 整合(若有 enterprise dev 客戶)
   △ MagicDocs(若做 docs-as-a-service)
   △ Away Summary(若有 background agent)
   △ DXT plugin format(若進 Anthropic 生態)

不做:
   ❌ Computer Use(SaaS 不適用)
   ❌ Voice(前端負責)
   ❌ Teleport(已被 sandbox 取代)
   ❌ Bridge / Remote(你就是 server)
   ❌ Auto-update(沒 client 套件)
```

完成 Phase 0-15 + 選擇性附錄 = **真正的 production-grade Claude Code 對等實作**。

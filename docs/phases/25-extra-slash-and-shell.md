# Phase 11c — 6 CLI Slash 內建 + !shell + @file + WS attachments 整合

**狀態**:📋 Plan(Phase 11 web-chat 精簡版完工後,看 user 真實需求再做)
**前置**:Phase 11 完成(slash registry + 2 內建 + upload + image + token_estimation)
**估時**:1 週

## 動機

Phase 11 範圍 A 砍到 spec 推薦的 web-chat 精簡版:只保 `/help` `/model`,
不做 `!shell` / `@file` ref。**沒做**:
- 6 個 CLI 用得到的 slash 內建(/clear /compact /init /memory /cost /history)
- `!shell` 模式(orion run 模式可選開,SaaS 預設關)
- `@file` ref 自動讀檔(對 CLI 友善)
- WebSocket UserMessageEvent.attachments 整合(目前 /uploads 走 separate REST)
- plugin manifest 註冊 slash 命令(對應 Phase 8)

CLI mode 用戶會想要這些。本 phase 補完。

## 範圍

### 做

| 項目 | 說明 |
|---|---|
| `/clear` | 清 Conversation.state_messages + reset replacement_state |
| `/compact` | 手動觸發 Phase 3 compact(force=True) |
| `/init` | 注入「分析 codebase 寫 CLAUDE.md」prompt(走 new_user_message 路徑) |
| `/memory` | 列 / 載入 user_memory_paths 內 MEMORY.md(整合 Phase 3) |
| `/cost` | call get_session_summary(Phase 9 cost_tracker)印當前 session |
| `/history` | 列 user 所有 session(整合 Phase 6 SessionManager.list_for_user) |
| `!cmd` 模式 | `ORION_ALLOW_SHELL_INPUT=1` 升旗才啟,走 Phase 7 sandbox / Phase 1 BashTool;結果包成 user message |
| `@file` ref | 偵測 `@<path>`,自動 read_file(走 Phase 7 sandbox 若啟)→ ContentBlock 注入 |
| Plugin slash 註冊 | Phase 8 plugin manifest 加 `commands` 欄位 → load_all_plugins 時 register_command |
| WS UserMessageEvent.attachments | event_schema 加 `attachments` 欄位(images + upload_ids),chat.py runner 用 process_user_input 處理 |
| Image 壓縮 | 超 5 MB 用 PIL thumbnail(opt-in dep) |

### 不做(留更後)

- speculative execution(PromptSuggestion)→ OPTIONAL § 4
- 跨 session `/clear all` / `/clear history` → Phase 12+
- /memory edit 直接改檔 → 用 ConfigTool / 前端側欄
- /init 真實 codebase 解析(現在仍是手寫 system prompt)→ skill-based,Phase 12+

## 檔案結構

```
src/orion_agent/
├── commands/builtin/
│   ├── clear.py              [新]
│   ├── compact.py            [新]
│   ├── init.py               [新]
│   ├── memory.py             [新]
│   ├── cost.py               [新]
│   └── history.py            [新]
├── input/
│   ├── shell.py              [新] is_shell_command + exec_shell(走 sandbox / BashTool)
│   └── text.py               [新] expand_file_refs / extract_attachments
├── plugins/loader.py         [改] load_all_plugins 加 register slash from plugin manifest
└── api/event_schema.py       [改] UserMessageEvent.attachments 欄位
api/routes/chat.py            [改] runner 用 process_user_input

tests/unit/commands/
├── test_clear.py / test_compact.py / test_init.py / test_memory.py / test_cost.py / test_history.py
tests/unit/input/
├── test_shell.py
└── test_text.py              file ref 展開
```

## 實作順序(7 步)

| Step | 工作 |
|---|---|
| 1 | 6 個 builtin slash + 各 unit test |
| 2 | input/shell.py — is_shell_command(`!cmd` 不含 `!!`)+ exec_shell(走 Phase 7 sandbox 若啟,否則 BashTool) |
| 3 | `ORION_ALLOW_SHELL_INPUT` 升旗 — 預設關;只 CLI 模式預設開 |
| 4 | input/text.py — expand_file_refs 偵測 `@<path>` |
| 5 | api/event_schema.py 加 attachments;chat.py runner 接 process_user_input |
| 6 | plugins/loader.py 把 plugin manifest 的 commands 欄位 register 進 registry |
| 7 | docs/phase-11c-completion.md + 整合 demo |

## Verification

```bash
# CLI mode slash 命令(orion run 預設關 — 只在 interactive shell 模式有意義,
# 如 Phase 12+ 加的 orion repl)
ORION_ALLOW_SHELL_INPUT=1 uv run orion repl
> /help            # 列 8 個內建
> /clear           # 清訊息
> /memory          # 看 MEMORY.md
> /cost            # 顯示當前 session 累計
> !ls              # shell 命令(包成 user message)
> /init            # 注入 codebase 分析 prompt

# WebSocket attachments 整合
curl -s -X POST http://localhost:8000/uploads -F file=@code.py ...
# 拿到 upload_id
ws.send({"type": "user_message", "content": "review this", "attachments": [
  {"type": "upload", "upload_id": "abc123"},
  {"type": "image", "data_url": "data:image/png;base64,..."},
]})
```

## 風險

| 風險 | 緩解 |
|---|---|
| `!cmd` 在 SaaS 預設開 → user 跑 `rm -rf /` | 預設關 + 升旗 + sandbox(Phase 7 docker backend) |
| `@file` ref path traversal | 走 sandbox 內 read,sandbox 自帶隔離 |
| WS attachments schema 變更打破舊 client | event_schema bump version,server-side accept 兩個 schema 一段時間 |
| Plugin command 衝突內建命令 | register_command 已 reject duplicate;plugin 命名強制 prefix(`<plugin>:cmd_name`)|
| `/init` 寫 CLAUDE.md 蓋掉 user 既有檔 | 改 mode:`/init` 只列建議差異,user 自己決定 apply |

## 完成 Phase 11c 後

orion-agent CLI 體驗 = TS Claude Code 對等。後續 Phase 12+ 做 input UX
(autocomplete / tooltips)+ multi-tenant 等 product feature。

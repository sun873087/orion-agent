# Manual testing

`make test` 涵蓋自動 test;有些功能要手動 click / 看 — 此文列那些 path。

## Chat API + Web

```bash
# Terminal 1
make dev-api

# Terminal 2
make dev-web
```

開 http://127.0.0.1:5173。

### Checklist

- [ ] 註冊新 user(`Sign up` → fill form → 收 verify 信跳過,自動 login)
- [ ] 開新 session,Provider 下拉看到 Anthropic / OpenAI / Ollama
- [ ] 送 "hi" 看 streaming text 一個字一個字出
- [ ] 工具呼叫:打 "讀 /etc/hosts" → Read tool card 出來 → 結果顯
- [ ] Session list 刪 / 改名
- [ ] Logout / 重新 login → session list 還在

## Cowork

```bash
make dev-cowork
```

### Checklist

- [ ] App 啟動 → 看 model 下拉 + Workspace badge + Session ID
- [ ] 送 prompt → text streaming + tool card 即時顯
- [ ] Slash command:`/help` / `/compact` / `/plan`
- [ ] Plan mode:輸入框旁 "放手讓我做" → "計畫" → 送任務 → 看 LLM 只 Read/Grep → 跳 modal 顯計畫 → Approve → 看 LLM 接著 Edit/Write
- [ ] Voice input:右下角麥克風 → 講話 → STT 結果填進輸入框
- [ ] TTS playback:Settings 開 autoplay → LLM 回完話自動念
- [ ] Schedule:`/loop "每天 9am 寫日報"` → 設成功
- [ ] Memory:Settings → Memory → 加一條 → 下次對話看是否 inject
- [ ] Skill:Settings → Skills → toggle 一個 → 下次對話看 LLM 行為變
- [ ] MCP:Settings → MCP → add server(e.g. github)→ 重啟 sidecar → 對話用 `mcp__github__*` tool
- [ ] Fork:某條 user msg 右上 fork 按鈕 → 開分支 → 兩條對話獨立
- [ ] Project:Sidebar 新增 Project → 多 session 共用 workspace
- [ ] Budget:某 session 設 $0.01 cap → 對話到 $0.01 → 擋 + banner 提示
- [ ] Cost icon:Header 看 累積 $ → 點開 RightSidebar 看細節
- [ ] Backup:Settings → Backup → Export.zip → 換新 user 開 → Restore → 資料回來
- [ ] Auto-update:啟動 5s 後 main process log 應看到 `[updater] checking-for-update`

## Model Proxy

```bash
make proxy-bootstrap
# 填 .env 的 ANTHROPIC/OPENAI key
make dev-model-proxy
open http://127.0.0.1:9090/admin/ui/
```

### Checklist

- [ ] Login 用 ADMIN_KEY
- [ ] New user → 建立成功
- [ ] Gen key → 明文 token 顯一次,複製
- [ ] Set budget $0.05
- [ ] 把 token 貼進 client(e.g. Cowork)→ 對話 → proxy log 看 usage_log row 寫入
- [ ] User detail page 顯 sparkline + 累計 cost
- [ ] Set budget cap → user 用超 → 下次 send 撞 402
- [ ] Rotate key → 舊 token 撞 403,新 token 通
- [ ] Audit log 看到所有 admin action
- [ ] Webhook 設一個 budget.exceeded → 觸發 cap → POST 到 URL
- [ ] Backup → /admin/maintenance/backup → 取得 zip → Restore → 復原

## CLI

```bash
uv run --package orion-cli orion run "demo"
```

### Checklist

- [ ] `orion --help`
- [ ] `orion run "讀 /etc/hosts"` — tool 即時顯進度
- [ ] `orion run --resume <session>` — 接續舊 session
- [ ] `--provider openai --model gpt-5-mini`
- [ ] `--sandbox docker` — Bash 跑在 container

## 撞錯怎麼辦

照 [troubleshooting.md](./troubleshooting.md) 走;沒對應條目 → check sidecar / proxy
log;最後手段:`rm -rf .venv && uv sync && make test`。

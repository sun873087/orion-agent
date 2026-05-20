# Troubleshooting

常見錯誤跟解法。

## `ModuleNotFoundError: No module named 'orion_*'`

**根因**(macOS):`~/Desktop` / `~/Documents` 被 iCloud Drive 同步,uv 寫 `dist-info/`
時 iCloud 自動 rename 新檔加 " 2" 後綴,Python import 失敗。

**確認**:

```bash
ls .venv/lib/python3.12/site-packages/orion_*-0.1.0.dist-info/ | grep " [2-9]"
```

**解法**:把 repo 移出 iCloud sync 範圍(或 macOS 系統設定 → Apple ID → iCloud → 桌面與
文件 → 關閉)。然後:

```bash
rm -rf .venv
uv sync
```

## `make dev-model-proxy` 撞 port 9090 in use

Phase 33 加了 auto-kill:`make dev-model-proxy` 會 `lsof :9090 | xargs kill -9` 再啟動。
若還撞,手動清:

```bash
lsof -ti :9090 | xargs kill -9
make dev-model-proxy
```

## `no such column: users.rate_limit_rpm`(或其他)

舊 proxy DB schema 跟 code 對不上。Phase 33 加了 `init_db` auto-migration(create_all
+ inspector 比 column 補缺),**重啟 proxy** 自動 ALTER TABLE:

```bash
make dev-model-proxy
# log 應該顯:auto-migrated: added users.rate_limit_rpm
```

## Cowork 撞 403 但 token 看起來對

Token 必須在 proxy DB 內(`api_keys.token_hash` row)。Phase 32 後不能自己編 token。

**修法**:

```bash
# 1. Admin UI 為 Cowork 生 token
open http://127.0.0.1:9090/admin/ui/
# Login → New user → Generate API key → 複製明文

# 2. 貼進 apps/orion-cowork/.env 的 ORION_MODEL_PROXY_KEY
```

詳:[`../features/model-proxy.md`](../features/model-proxy.md)。

## Cowork ChatBox 撞錯 / 卡住,看不到原因

Sidecar 已會 emit 結構化 error frame,renderer 顯紅 ErrorBanner(可展開 / 複製 / 關閉)。
若卡住沒任何錯,看 sidecar log(`~/.orion/log/cowork-sidecar.log` 或 Electron DevTools
Console 看 main process log)。

## Anthropic / OpenAI 撞 401

- **Direct 模式**:檢查 `apps/<app>/.env` 的 `ANTHROPIC_API_KEY` / `OPENAI_API_KEY`
- **Proxy 模式**:檢查 `ORION_MODEL_PROXY_KEY` 是 admin 生的 `sk-orion-...` token

401 ≠ 403(後者是 token 曾有但 revoked)— Phase 33 對齊業界。

## Vite build 後 Electron 白屏

`vite.config.ts` 內 `base: './'`(production 用)— 若漏了,production build 用 absolute
`/assets/...` 路徑而 Electron `file://` 讀不到。**重 build**:

```bash
cd apps/orion-cowork
rm -rf dist
pnpm build
```

## Test 在 CI 過但本機掛 / 反過來

通常 env 差異。比較:

```bash
env | grep -E "ORION|ANTHROPIC|OPENAI" | sort
```

確認本機 / CI 兩邊一致。常見問題:`ORION_MODEL_PROXY_URL` 在本機 .env 設了但 CI 沒。

## pnpm install 撞 EACCES / 卡死

```bash
rm -rf node_modules apps/*/node_modules packages/*/node_modules
pnpm store prune
pnpm install
```

## Sidecar process 卡住、Electron 不關

```bash
ps aux | grep orion-cowork-sidecar
kill <pid>
```

或重開 Electron 強迫 main process 收 sidecar(`app.on('before-quit', ...)`)。

## SQLite WAL 殘留(crash 後)

```bash
# Cowork
ls ~/.orion/sessions/cowork.db*
# 看到 .db-shm / -wal 殘留 → safe to rm(下次啟動 WAL 自動 init)
rm ~/.orion/sessions/cowork.db-shm ~/.orion/sessions/cowork.db-wal
```

Proxy 同樣 `packages/orion-model-proxy/data/proxy.db-*`。

## 看完繼續

- [setup.md](./setup.md) — 從 0 跑起
- [run-tests.md](./run-tests.md) — 測試
- [build.md](./build.md) — 打包 dist

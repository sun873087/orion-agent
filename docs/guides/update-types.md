# Update type contracts

跨 Python / TS 邊界改 schema 時的同步流程。

## 哪些 boundary 要 sync?

### 1. chat-api ↔ web frontend

```
apps/orion-chat/api/routes/*.py         ← Python (Pydantic)
        ↕  REST + WS JSON
apps/orion-chat/web/src/api/*.ts        ← TS types
```

改 chat-api 的 routes / WS event schema 後,web frontend 的 TS types 要更新。

**目前作法**:手動同步。看 Pydantic model → 寫對應 `type Foo = {...}` 在 web/src/api/。

**未來**:用 `pydantic2ts` / `datamodel-code-generator` 自動產出。

### 2. Cowork sidecar ↔ renderer

```
apps/orion-cowork/sidecar/src/orion_cowork_sidecar/handlers.py    ← Python RPC method
        ↕  JSON-RPC over stdio
apps/orion-cowork/renderer/src/api/agent.ts                       ← TS wrappers
apps/orion-cowork/renderer/src/store/*.ts                         ← TS data types
```

加新 RPC method 時:

1. 在 sidecar `handlers.py` 加 `async def method_name(self, params): yield ...`
2. 在 `methods()` dict 註冊 RPC name(e.g. `"backup.export": ...`)
3. 在 renderer `api/agent.ts` 加對應 `async function backupExport(...)` wrapper
4. 在 store types 加新 type(若有 data shape)
5. UI components 用新 wrapper

## Preload API extension

加 Electron `window.{...}Api`:

```
apps/orion-cowork/electron/preload.ts                     ← API impl + ipcRenderer.on
apps/orion-cowork/electron/main.ts                        ← ipcMain.handle + 對應 listener
apps/orion-cowork/renderer/src/preload.d.ts               ← TS interface 給 window.{xxx}Api
```

新加例:Phase 33 的 `window.updaterApi`(electron-updater):

1. `electron/updater.ts` 寫 init + 對外 quitAndInstall
2. `main.ts` 註冊 `ipcMain.handle('updater:quitAndInstall', ...)` + `initAutoUpdater(...)` 啟動
3. `preload.ts` `contextBridge.exposeInMainWorld('updaterApi', {...})`
4. `preload.d.ts` 加 `interface OrionUpdaterApi { ... }` + extend `Window`

順序錯了會撞 TS error。

## Catalog 更新(`models.json`)

加新 model:

1. `packages/orion-model/src/orion_model/models.json` 加 entry(id / label / max_tokens / pricing / supports_reasoning)
2. 跑 `pytest packages/orion-model` 確認 catalog 不破
3. 若新 model 需特殊 wire(e.g. OpenAI o-series 帶 reasoning_effort),`openai_provider.py` 內加邏輯

Catalog 用 `@functools.cache` — restart proxy / app 才看到新 model。

## 同步 i18n keys

加 new UI string:

1. 4 locale 都加 key(`zh-TW.ts` / `zh-CN.ts` / `en.ts` / `ja.ts`)
2. TS strict mode 抓漏 — 若 zh-CN 漏一 key,typecheck 過(因為 union type)— 自己注意
3. 用法:`t('settings.backup.exportTitle')`

## Schema migration(proxy)

加 `users.rate_limit_rpm` 之類新 column:

1. `packages/orion-model-proxy/src/orion_model_proxy/models.py` 加 column
2. `init_db._add_missing_columns` 自動 ALTER TABLE(下次啟動)
3. Production 用 alembic 寫 migration 是更穩(目前未做)

## 看完繼續

- [setup.md](./setup.md) — 跑 dev mode
- [run-tests.md](./run-tests.md) — 測 schema 沒破

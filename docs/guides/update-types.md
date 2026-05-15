# Update type contract(chat-api ↔ web / cowork-renderer)

chat-api 改了 routes / WS event schema 後,web frontend 的 TS types 要重新生成,不然編譯期就會撞 mismatch。

## 一鍵生成

```bash
make gen-types
```

內部三步驟:

| Step | 來源 | 產出 |
|---|---|---|
| `gen:openapi` | `chat-api/app.openapi()` | `apps/orion-chat/shared/openapi.json` |
| `gen:ws-schema` | pydantic `ClientEvent` / `ServerEvent` | `shared/ws-{client,server}-events.schema.json` |
| `gen:ts-types` | openapi-typescript + json2ts | `apps/orion-chat/web/src/types/api.gen.ts` + `ws-*-events.gen.ts` |

## 何時要跑

| 改了 | 影響 |
|---|---|
| `chat-api/routes/*.py` 加 / 改端點 | `openapi.json` + `api.gen.ts` |
| `chat-api/event_schema.py` 加 / 改 WS event | `ws-*.schema.json` + `ws-*-events.gen.ts` |
| pydantic model 的 `Field(...)` 描述 / 預設值 | 兩者都會變 |
| 純內部 helper(不出現在 schema) | 不用跑 |

不確定就跑一次 `make gen-types` + `git diff` 看有沒有 .gen.ts 變動。

## 使用生成的 types

```typescript
// apps/orion-chat/web/src/api/foo.ts
import type { paths } from '@/types/api.gen'

type LoginResponse = paths['/auth/login']['post']['responses']['200']['content']['application/json']
```

WS:

```typescript
import type { OrionChatServer→ClientEvents } from '@/types/ws-server-events.gen'

ws.onmessage = (raw) => {
  const ev: OrionChatServer→ClientEvents = JSON.parse(raw.data)
  switch (ev.type) {
    case 'assistant_text_delta': ...
  }
}
```

**不要手寫 chat-api 對應的 types** — 一旦 schema 改了會跟生成的衝突。

## CI drift check

(未設定;設定後)CI 跑:

```bash
make gen-types
git diff --exit-code apps/orion-chat/shared apps/orion-chat/web/src/types
```

若有改 schema 但忘記重 generate → CI 紅。

## 生成失敗常見原因

| 症狀 | 原因 | 解 |
|---|---|---|
| `openapi-typescript: command not found` | 沒裝 npm dev deps | `npm install` |
| `json2ts: Missing $ref pointer` | pydantic discriminated union 在同一檔內共用 $defs | `dump_ws_schema.py` 拆兩檔(已做) |
| `cannot find module '@/types/api.gen'` | vite alias 沒設 / 沒 generate | `make gen-types`,確認檔案存在 |

## Cowork renderer

目前 Cowork 用 stdio JSON-RPC,**不**透過 chat-api,所以**不**用這套 pipeline。Cowork 的 wire format 直接寫在 `apps/orion-cowork/renderer/src/api/agent.ts`(手動定義 union type)。

未來若 Cowork 也要型別契約自動化,設計類似(從 sidecar handlers 自動 dump schema)。

## 相關

- [chat-api.md](../features/chat-api.md) — schema 來源
- [web-frontend.md](../features/web-frontend.md) — 怎麼用

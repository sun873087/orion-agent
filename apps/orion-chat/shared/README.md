# apps/orion-chat/shared/

Chat 產品(api + web)的共享契約。**內容由 script 自動生成,不要手改**。

## 檔案

| 檔案 | 來源 | 用途 |
|---|---|---|
| `openapi.json` | `scripts/dump_openapi.py`(從 FastAPI app `.openapi()`) | REST 端點 schema |
| `ws-events.schema.json` | `scripts/dump_ws_schema.py`(從 `event_schema.py` pydantic models) | WebSocket client↔server event 訊息 schema |

## 生成

```bash
npm run gen:types       # 一次跑完三步驟:openapi + ws-schema + ts-types
```

或單獨:

```bash
npm run gen:openapi     # api → shared/openapi.json
npm run gen:ws-schema   # api → shared/ws-events.schema.json
npm run gen:ts-types    # shared/*.json → web/src/types/*.gen.ts
```

## CI drift check

```bash
npm run gen:types
git diff --exit-code apps/orion-chat/shared apps/orion-chat/web/src/types
```

若 api event_schema 或 routes 改了但沒重 generate,CI 紅。

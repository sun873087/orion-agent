# Phase 30-D:移 web + 共享契約

## 速覽

- **預計時程**:2-3 天
- **前置 Phase**:30-C(chat-api 已搬到 `apps/orion-chat/api/`)
- **狀態**:📝 spec only,**未實作**
- **目標**:把 `frontend/` 搬到 `apps/orion-chat/web/`,讓「Chat 產品 = api + web」綁在同一個 sub-project 下;加入從 chat-api OpenAPI / WS schema 自動生成 TS types 的機制

## 1. 為何要做這個

`frontend/` 唯一的客戶是 `orion-chat/api`,兩者共享:

- HTTP REST 端點(`/api/chat/sessions`、`/api/auth/login` 等)
- WebSocket protocol(`/chat/stream/<sid>`,各種 client/server event 訊息格式)
- JWT auth 流程
- 訊息 / event schema(`event_schema.py` 那組 pydantic models)

把它們綁在 `apps/orion-chat/` 下,**契約對齊**:

- 改 api event_schema → web 跟著重 generate TS types,編譯期就抓到 mismatch
- 一起發版(Docker 出一個 `orion-chat` image,內含 api + web static build)
- `apps/orion-chat/shared/` 放雙邊共享的 OpenAPI / WS schema,單一 source of truth

## 2. 任務拆解

- [ ] `git mv frontend apps/orion-chat/web`
- [ ] 確認 `apps/orion-chat/web/package.json` 路徑沒有指 `../api`(若有,改絕對名稱)
- [ ] 在 repo root 加 `package.json` 設定 npm workspaces
- [ ] root `npm install` 通
- [ ] `cd apps/orion-chat/web && npm run dev` 跑得起來
- [ ] 驗證 web 連 `apps/orion-chat/api` 對話正常(現有功能不應 regress)
- [ ] 新增 `apps/orion-chat/shared/` 目錄
- [ ] 寫 OpenAPI 生成 script(`scripts/gen-openapi.py`):從 chat-api 跑 `app.openapi()` dump 到 `shared/openapi.json`
- [ ] 寫 TS types 生成 script:`npx openapi-typescript shared/openapi.json -o web/src/types/api.ts`
- [ ] 寫 WS event schema 生成(下面 §4 詳述,因為不是 REST,openapi-typescript 抓不到)
- [ ] web 改用生成的 types(漸進),刪掉手寫的 type 定義
- [ ] CI 加一步驗證生成的 types 沒漂移(`generate && git diff --exit-code`)

## 3. `apps/orion-chat/` 目錄結構

```
apps/orion-chat/
├── api/                       (Phase C 已建好)
│   ├── pyproject.toml
│   └── src/orion_chat_api/
├── web/                       ★ 從 frontend/ 搬來
│   ├── package.json
│   ├── vite.config.ts
│   ├── tsconfig.json
│   ├── tailwind.config.js
│   ├── postcss.config.js
│   ├── eslint.config.js
│   ├── index.html
│   ├── public/
│   └── src/
│       ├── types/
│       │   ├── api.ts          ← 自動生成,不要手改
│       │   └── ws-events.ts    ← 自動生成
│       └── ...(原有 React code)
├── shared/                    ★ 新
│   ├── openapi.json            ← 生成
│   ├── ws-events.schema.json   ← 生成
│   └── README.md               ← 說明這裡都是生成檔
└── README.md                  ★ 新:解釋 chat 產品 = api + web 一起發版
```

## 4. WS event schema 怎麼生成

`apps/orion-chat/api/src/orion_chat_api/event_schema.py` 目前用 pydantic 定義 WS 來回的 event types(client → server 跟 server → client)。流程:

```python
# apps/orion-chat/scripts/dump_ws_schema.py
import json
from pathlib import Path
from orion_chat_api.event_schema import (
    ClientEvent,  # discriminated union
    ServerEvent,
)

schema = {
    "client_to_server": ClientEvent.model_json_schema(),
    "server_to_client": ServerEvent.model_json_schema(),
}
Path("apps/orion-chat/shared/ws-events.schema.json").write_text(
    json.dumps(schema, indent=2, ensure_ascii=False)
)
```

然後用 `json-schema-to-typescript`(npm package)把 JSON schema 轉 TS types:

```bash
npx json-schema-to-typescript apps/orion-chat/shared/ws-events.schema.json \
  --output apps/orion-chat/web/src/types/ws-events.ts
```

## 5. root npm workspaces 設定

### 5.1 新檔:`/package.json`(repo root)

```json
{
  "name": "orion-agent-workspace",
  "private": true,
  "workspaces": [
    "apps/orion-chat/web",
    "apps/orion-cowork"
  ],
  "scripts": {
    "gen:openapi": "uv run --package orion-chat-api python apps/orion-chat/scripts/dump_openapi.py",
    "gen:ws-schema": "uv run --package orion-chat-api python apps/orion-chat/scripts/dump_ws_schema.py",
    "gen:types": "npm run gen:openapi && npm run gen:ws-schema && npm run gen:ts-types",
    "gen:ts-types": "npx openapi-typescript apps/orion-chat/shared/openapi.json -o apps/orion-chat/web/src/types/api.ts && npx json-schema-to-typescript apps/orion-chat/shared/ws-events.schema.json --output apps/orion-chat/web/src/types/ws-events.ts"
  },
  "devDependencies": {
    "openapi-typescript": "^7.0.0",
    "json-schema-to-typescript": "^15.0.0"
  }
}
```

註:`apps/orion-cowork` 在 Phase E 才會建立,先列在 workspaces 但不存在沒關係(npm 8+ 容忍 missing member,8 以前要等 Phase E)。穩妥起見,**Phase D 先只列 `apps/orion-chat/web`**,Phase E 再加 cowork。

### 5.2 修改:`apps/orion-chat/web/package.json`

- 確認 `name` 改成 `"@orion/chat-web"`(workspace 用 scoped name 比較不會撞 npm public)
- 確認沒寫死絕對路徑

## 6. 驗證 contract 的 CI 流程

```yaml
# .github/workflows/ci.yml (示意)
- name: Generate types
  run: npm run gen:types

- name: Check no drift
  run: git diff --exit-code apps/orion-chat/web/src/types/ apps/orion-chat/shared/
  # 若 api event_schema 改了沒 regenerate,CI 紅
```

## 7. 風險與緩解

| 風險 | 嚴重度 | 緩解 |
|---|---|---|
| 既有 `frontend/src/types/` 手寫 types 跟生成 types 衝突 | 中 | Phase D 漸進:生成檔放 `types/api.ts`、`types/ws-events.ts`,手寫的逐步替換不一次全砍 |
| Vite proxy 設定還指向舊路徑 | 低 | `vite.config.ts` proxy 是相對 `http://localhost:8000`,不受目錄搬遷影響 |
| `index.html` 內 base path 變了 | 低 | Vite dev server 不會 |
| `.dockerignore` / `.gitignore` 漏掉 `apps/orion-chat/web/node_modules` | 低 | Phase D 結束時順手 audit |
| OpenAPI dump 漏端點(FastAPI 自動 schema 不含 WS) | 中 | 用 §4 額外生成 WS schema |
| pydantic discriminated union 在 `model_json_schema()` 輸出格式 npm tool 不認 | 中 | 寫個小 wrapper 把 pydantic schema 轉成 standard JSON Schema(`$ref` 攤平) |

## 8. 驗收

- [ ] `frontend/` 目錄消失
- [ ] `apps/orion-chat/web/` 存在,內容跟舊 frontend 一致
- [ ] root `npm install` 通,`apps/orion-chat/web/node_modules/` 走 root 的 hoist
- [ ] `npm run dev -w @orion/chat-web` 跑得起來,連 chat-api 對話正常
- [ ] `npm run gen:types` 跑得起來,生成的檔有內容
- [ ] CI 跑 generate + diff 是綠的

## 9. 完成後的狀態

```
orion-agent/
├── pyproject.toml
├── package.json                ★ 新:npm workspaces root
├── uv.lock
├── package-lock.json           ★ 新
├── node_modules/               ★ 新:hoisted
├── packages/
│   ├── orion-model/
│   └── orion-sdk/
├── apps/
│   ├── orion-cli/
│   └── orion-chat/
│       ├── api/
│       ├── web/                ★ 從 frontend/ 搬來
│       ├── shared/             ★ 新
│       │   ├── openapi.json
│       │   ├── ws-events.schema.json
│       │   └── README.md
│       ├── scripts/
│       │   ├── dump_openapi.py
│       │   └── dump_ws_schema.py
│       └── README.md
├── deploy/                     (Phase F 才更新)
└── docs/
```

## 10. 下一步

Phase D 完成後可進 Phase F(收尾)。Phase E 可以跟 D 平行做。

# Design decisions

重要的設計取捨,**和它們的理由**。要動以下任一條前,先讀本文。

---

## 1. 不用 agent framework

**選擇**:`orion-sdk` 直接用 `anthropic` + `openai` 兩個薄 HTTP wrapper SDK。**不**用 Claude Agent SDK / OpenAI Agents SDK / LangChain / LiteLLM / 其他第三方 framework。

**理由**:

- Agent loop 邏輯本身不複雜,核心 `core/query_loop.py` 不到 300 行。Framework 帶來的是抽象成本(每個 framework 自己的 message / event / tool 抽象)而非實質減少程式。
- Tool 並行、permission、streaming、tool result 持久化、memory、compact、recovery 這些**真正的複雜度**,framework 通常處理得很表面;改起來要對抗 framework,不如自己寫。
- 多 provider 支援:用 framework 等於同時跟 framework 跟 provider 兩邊吵架。自己寫 `NormalizedEvent` 抽象一次到位,且能控制每個 wire-format 細節。

**代價**:每個 LLM provider 行為差異(reasoning blocks、prompt caching、tool use parallelism)要自己處理 — 已封裝在 `packages/orion-model/translation/{anthropic,openai}.py`。

---

## 2. `orion-model` 跟 `orion-sdk` 分兩個 package

**選擇**:LLM 抽象(`orion-model`)獨立成 package,**不**塞進 `orion-sdk`。

**理由**:

- `orion-model` 邊界清楚 — 只認 LLM,不認 agent loop / tools / memory。**沒有反向依賴**(grep 過,`packages/orion-model/src/` 內所有 import 都只指自己)。
- 可單獨用 — 想做 prompt 測試、benchmark、純 chatbot,引一個 600 LOC 級的 package 就夠,不用拖 sqlalchemy / docker / mcp 進來。
- 強制紀律 — `orion-sdk` 內任何模組想 call LLM 都得透過 `orion-model.provider`,不能繞道 `import anthropic`,違規由 import-linter 擋下。

---

## 3. Cowork 不走 chat-api,直接用 SDK

**選擇**:`apps/orion-cowork/sidecar` 是獨立 Python 進程,直接 `import orion_sdk` 跑 agent loop,**不**透過 `orion-chat-api`。Electron main 用 stdio JSON-RPC 跟 sidecar 通訊。

**理由**:

- Cowork 是**本機單機 app** — 單一使用者、單一機器、本機檔案完整存取。
- chat-api 為「跨網路 / 多使用者」設計,有 JWT auth、CORS、多 session 管理、HTTP overhead、token rate limit、CSRF 防護。Cowork 一個都不需要。
- 讓 Cowork 走 chat-api = 自己打開 HTTP server、發 token 給自己、再連回來 — 沒有意義。
- 對稱性:CLI / chat-api / cowork-sidecar 三個是**平行的 SDK consumer**,各自用 SDK,各自選自己的傳輸協定(stdin、HTTP/WS、stdio JSON-RPC)。

**代價**:Cowork 跟 chat/web 沒有共用協定,renderer 完全獨立寫(這是刻意,見下一條)。

---

## 4. Cowork renderer 完全獨立重寫,不複用 chat/web 元件

**選擇**:`apps/orion-cowork/renderer/` 用 React 但不 import 任何 `apps/orion-chat/web/` 元件。

**理由**:

- chat/web 是「服務型 chat UI」(session 列表、登入、訊息泡泡),Cowork 是「桌機 app UI」(可能多視窗、托盤、檔案 drag、本機通知整合)— 設計 paradigm 不同。
- 一旦共用,兩邊行為被綁,Cowork 想做桌機 native 體驗時被 chat/web 拖。
- 共用元件等於再加一個 npm workspace member (`@orion/chat-ui-shared` 之類),養兩份 dep。

**代價**:小團隊有 chat/web 跟 cowork 兩份 React UI 要維護。可接受 — UI 是「本來就會變」的層,共用元件的價值低於想像。

---

## 5. 不做完整 TS port of agent runtime

**選擇**:SDK 只有 Python 版,**不**做 TypeScript port。Cowork 用 Python sidecar(而非純 TS agent)。

**理由**:

- 完整 TS port = 重寫 30+ 工具、core 狀態機、sandbox、memory、compact、storage、migrations。**雙倍維護成本**,每加 feature 寫兩次,Python / TS 行為差一點就是 bug。
- 對照 Anthropic 自己:Claude.ai(web)跟 Claude Code(desktop)沒共用 agent runtime — 它們是獨立 codebase,Claude Code 從第一天就是 TS,沒有 port 問題。
- TS 「client SDK」(只 call chat-api 的 typed wrapper)有價值,但那叫 OpenAPI client,不叫 agent SDK。

**代價**:Cowork 必須打包 Python runtime(production 用 PyInstaller),binary 較肥。Phase E PoC 階段用 `uv run` 開發,production 打包另開 phase。

---

## 6. Monorepo + workspaces,不拆獨立 repo

**選擇**:uv workspace + npm workspaces,全部在一個 git repo。

**理由**:

- 本機 editable install — 改 SDK 馬上所有 app 吃到,不用 publish 周轉
- 單一 lock file(`uv.lock` / `package-lock.json`)— 不會跨 repo 漂移
- CI 簡單 — 一個 `uv sync` + 一個 `npm install` 把整個 workspace 裝好
- 想要分離 — 直接把資料夾切出去就好(用 `git subtree split`)

**代價**:repo size 變大、CI matrix 要會跑「只在某 package 變動時跑該 package 的 tests」(尚未實作,目前 CI 跑全套)。

---

## 7. Tool / OTel 命名空間故意保留 `orion_agent.*` 前綴

**選擇**:OpenTelemetry span 名稱 `orion_agent.turn` / `orion_agent.tool` / `orion_agent.tokens.*` 在 Phase 30 import path 改名後**故意不動**。

**理由**:這些是觀測平台的 namespace,既有 dashboard / alert 都掛在這些名字上。改它們等於要同步改觀測 stack,本來只是 import refactor 變成 cross-team 工程。

**代價**:Python import path 是 `orion_sdk.*`、OTel namespace 是 `orion_agent.*`,新人看到會疑惑。**用 grep / 本文解釋**:Python 程式碼 = `orion_sdk`,觀測 = `orion_agent`。

---

## 8. Migrations 屬於 `orion-sdk`,不屬於 `orion-chat-api`

**選擇**:alembic migrations 放 `packages/orion-sdk/migrations/`,由 SDK 提供 `upgrade()` API。chat-api 啟動時呼叫。

**理由**:

- DB schema 屬於 SDK(`storage/db/models.py` 定義),migrations 跟著它走。
- 多個 SDK consumer(chat-api、Cowork 本機 SQLite、未來其他 app)可能用同一份 schema — schema migration 不該歸特定 app。
- Cowork sidecar 想存對話歷史時,直接呼叫 SDK 的 upgrade 函式,跟 chat-api 用同一份 schema。

**代價**:`packages/orion-sdk` 多了 `alembic.ini` + `migrations/`,看起來不像「純 library」。可接受。

---

## 9. Tests 分散到對應 package,共用 fixtures 透過 `pytest_plugins`

**選擇**:每個 package 自己的 `tests/` 目錄(orion-model 46、orion-sdk 704、orion-cli 55、orion-chat-api 102、orion-cowork-sidecar 7),共用 fixtures 抽到 `orion_sdk._testing` 模組,各 conftest 用 `pytest_plugins = ["orion_sdk._testing"]` 拉進來。

**理由**:

- 測試歸屬清楚 — 改 chat-api routes 不該跑 SDK 全套 700 tests
- 各 package 可獨立發 PyPI — orion-model 真要分離,它有自己的 tests
- 共用 fixtures 不靠 sys.path hack,用 pytest 原生 plugin 機制
- 對照業界(sqlalchemy.testing、numpy.testing)— 把 testing helpers 放 production wheel 內,private 雙底線開頭,是業界慣例

**代價**:`orion_sdk._testing` 進 production wheel(用 `pytest` 作 fixture,但 lazy import,production runtime 不會被觸發)。可接受。

---

## 10. WS protocol + REST 兩者並存

**選擇**:`orion-chat-api` 同時提供 REST endpoints(auth / sessions / settings / memories CRUD)跟 WebSocket(`/chat/stream/<sid>`),不只有 WS。

**理由**:

- 對話本身需要 streaming 跟雙向(WS 合適)
- 但 session 管理、設定、auth 是 request/response(REST 合適,可被任何 HTTP client 用)
- 第三方整合(自動化、行動 app)用 REST 比 WS 容易
- Frontend 一律用 REST 拿初始狀態 + WS 開長連線推 events

**代價**:兩套協定要同步維護。已用自動生成型別 mitigated(`shared/openapi.json` + `shared/ws-*.schema.json`)。

---

## 看完繼續

- [packages.md](./packages.md) — 各 package 具體做什麼
- [runtime-layout.md](./runtime-layout.md) — config / data 在哪
- [`../features/`](../features/) — 各 feature 的設計細節

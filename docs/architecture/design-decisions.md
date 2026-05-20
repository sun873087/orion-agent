# Design decisions

重要的設計取捨,**和它們的理由**。要動以下任一條前,先讀本文。

## 1. 不用 LangChain / LlamaIndex / 任何 agent framework

直接用 `anthropic` + `openai` 的薄 SDK + 自寫 agent loop。

**理由**:第三方 framework 通常為 generic chatbot 設計,把 tool-call schema、prompt
template、token 計算包成黑盒。orion 對「stream 怎麼分 chunk / cache 怎麼下、tool
parallel 怎麼跑、permission policy 怎麼介入」都要可控,任何一層黑盒都得跳;與其
跟 framework 鬥,不如薄 SDK 自寫。

## 2. 3 個 app 不共用 sessions DB

- Cowork:`~/.orion/sessions/cowork.db`(SQLite,SDK 共用表 + `cowork_*` 擴充表)
- CLI:`~/.orion/sessions/<uuid>/transcript.jsonl`(per-session JSONL dir)
- chat-api:同 CLI 預設 / production 走 Postgres

**理由**:Cowork 對 query latency 敏感(本機 UI 30+ session 切換要 instant),要 random
access + 索引 — SQLite 合適。CLI 是 one-shot 跟 manual review 為主,append-only JSONL
最簡單。chat-api 跑 SaaS 規模需 PostgreSQL。三家對 DB 要求完全不同,強行統一 = 都
不滿意。

**共用的**:skills / memory / mcp.json / blobs / users — 一個 host 裝 skill 另一 host
看得到,跨 host 一致性 > 各自隔離。

## 3. Cowork 不走 chat-api,走 stdio JSON-RPC 連 sidecar

Cowork 是 Electron + Python sidecar。Electron main process spawn Python sidecar,雙方
用 stdin/stdout 跑 JSON-RPC。

**理由**:本機單機不需要 HTTP + JWT + CORS。stdio 比 socket 安全(沒 port 暴露),
JSON-RPC 比 REST 適合 streaming(scheduler.fired 之類 notification 隨時推),延遲低。
要把 Cowork 改 SaaS-mode 直接走 chat-api,sidecar 直接刪。

## 4. Tool 註冊由 host 控,SDK 只定義 spec

SDK `tools/builtin_set.py` 的 `build_default_tool_set(...)` 接收一堆 callback —
`ScheduleCreate` / `LoopCreate` / `ask_user_question` 等執行邏輯由 host 注入。

**理由**:同一個 tool name(例如 `ScheduleCreate`)在 CLI 是 cron tab 寫入,在 Cowork 是
寫進 SQLite 的 `cowork_schedules` 表,在 chat-api 是發 webhook。tool 的「**意義**」由 SDK 定,
「**怎麼做**」由 host 注入。

## 5. Proxy 是 transparent reverse,不解碼 wire format

`/openai/{path:path}` + `/anthropic/{path:path}` catch-all,byte-for-byte 透傳。**不**做 Orion-native
`/v1/messages` 中間層。

**理由**:中間層 = 雙倍 wire(Orion-native ↔ provider native),維護成本高且容易跟 provider
新 endpoint 脫鉤。透傳的代價是「proxy 不知道 wire 內容」— 但這個成本用 tee 解(forward
不改 + 邊解析邊送 client)就解掉了。額外好處:**外部 SDK**(LangChain / aider / Cursor)
可以直接設 `base_url` 用我們的 proxy,不必改 wire。

## 6. Per-app `.env`,不共用 root `.env`

CLI / chat-api / cowork / proxy 各自有 `.env`(分別在 `apps/orion-cli/.env`、
`apps/orion-chat/.env`、`apps/orion-cowork/.env`、`packages/orion-model-proxy/.env`),
四份各自獨立。

**理由**:每個 app role 完全不同 — chat-api 需要 JWT/DB/OAuth,CLI 不用;proxy 需要
admin token + upstream key,client 都不用。共用 root 看 130 行 env 撈 5 行相關,新人會哭。
每個 app 的 `.env.example` 只列該 role 該管的 var,role boundary 清楚。

## 7. Memory ranker 預設 heuristic(bag-of-words),不用 LLM

`memory/ranker.py` 預設 keyword overlap,可選 `ORION_MEMORY_RANKER=llm` 切 Haiku 評分。

**理由**:LLM ranker 每輪多打一次模型,$ / 延遲都不可忽視。Bag-of-words 對 100 條
memory 內準確度夠用,延遲 <1ms。LLM ranker 留給「memory 數量爆炸 / 主題重疊嚴重」
的進階場景。

## 8. Anthropic prompt cache 預設 1h TTL(static + session),5m(messages)

`cache_config.py` 定的。

**理由**:Anthropic 計費 5m write 1.25× / 1h write 2× / read 永遠 0.1×。Static system
prompt 跟 session-stable block 跨多輪 idle gap 重複用,1h TTL 攤平寫成本;message
history 每輪都重寫最新斷點,5m 足夠。

## 9. Cowork session 內含「per-conversation budget cap」+ proxy 內含「per-user budget cap」

兩層獨立。

**理由**:
- **Per-session**(Cowork)= user 想知道「這條對話花多少」+ 自我約束
- **Per-user**(proxy)= admin 給整月預算 + 強制 enforcement

互相不取代:user 可以開 10 條 session 各 $5,proxy 端 admin 總體 $30 上限;兩端各自
擋,可疊加。

## 10. Skill / Memory / MCP 跨 host 共用 `~/.orion/`,不分 Cowork / CLI / chat-api

`~/.orion/skills/` / `~/.orion/users/<u>/memory/` / `~/.orion/mcp.json` 三家共用。

**理由**:user 心智模型是「我有一份 memory + 一批 skill,不管在 CLI / Cowork / web
都該看到同樣的」。session 各自隔離(對話歷史不互通),但 knowledge 是 user 屬性,
不是 host 屬性。

## 11. Storage 三層 budget(per-message / per-session / per-user)

SDK `storage/budget.py`。Per-message 限單條 token,per-session 限對話總 token,
per-user 限全 user 月度成本。

**理由**:單一 cap 不夠 — 一條超長訊息可能燒掉整個月預算。三層才能精準擋。

## 12. Proxy schema 自動 migration(create_all + 補 column),不用 alembic

`db.init_db()` 跑 `create_all` 後再用 inspector 補缺欄。

**理由**:alembic 是「production multi-instance 多人同時改 schema」的場景;orion proxy
通常單實例自架,alembic overkill。輕量 inspector + `ALTER TABLE ADD COLUMN` 應付加
column 場景。真要 drop / rename column 再上 alembic。

## 13. Streaming 一律 SSE 透傳,不 buffer

Proxy 對 OpenAI Chat / Anthropic Messages 都走 `aiter_bytes()` 邊收邊 forward,不等
完整 response。

**理由**:LLM 體驗最重要的事就是「user 馬上看到字出來」。Buffer = UX 死。代價是
parser 要邊收邊累加 token usage(用 SSE 末 chunk / `message_delta` 解)— 多一點
複雜度,值得。

## 14. Cowork sidecar 沒 chat-api 那一層 → 沒 multi-user / 沒 JWT

`cowork-local` 永遠是 user_id,單機單帳號。

**理由**:Cowork 是「個人桌機 app」定位 — 多 user 場景是 chat-api 的事。要 Cowork
multi-user 直接接 chat-api 反而簡單,不必扛兩套 auth。

## 15. WebFetch 有 per-session in-memory cache,WebSearch 沒

`tools/web/fetch.py` 內 5 分鐘 TTL cache。`web/search.py` 沒。

**理由**:同 session 內反覆 fetch 同 URL 很常見(model 翻多次同份 docs);同 query 連 search
不常見(model 通常 query 不同 keyword)。Cache 加錯地方=記憶體浪費。

## 16. SDK 給的 tool description 是英文,不是本地化

LLM 看的 description 不轉 i18n,只有 user-facing UI(Cowork)做 i18n。

**理由**:LLM 在英文 prompt 表現最好(model 訓練語料偏英)。Localized tool description
浪費 token + 偶爾誤導 model。User UI 是另一回事,該本地化。

## 看完繼續

- [README.md](./README.md) — 拓樸總覽
- [packages.md](./packages.md) — 每 package 細節
- [`../roadmap/README.md`](../roadmap/README.md) — 未來方向(會有新 decision)

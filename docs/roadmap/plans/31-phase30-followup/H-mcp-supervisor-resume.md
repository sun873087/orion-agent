# Phase 31-H:MCP supervisor + cross-machine resume

## 速覽

- **預計時程**:1 週
- **前置 Phase**:無(Track 3 獨立)
- **狀態**:📝 spec only,**未實作**
- **目標**:兩個 SDK polish 一起做(各約半週):
  1. MCP server crash 自動重啟
  2. Postgres-backed cross-machine session resume

## 1. MCP server supervisor

### 1.1 現況

`McpManager` 啟動時連 server,server 死掉只 log,不重啟。User 看到「工具消失」要 manual restart。

### 1.2 設計

加 supervisor task:每 N 秒檢查 server 連線狀態,死掉就重 spawn(指數 backoff,3 次失敗 give up)。

```python
# orion-sdk/mcp/supervisor.py
class McpSupervisor:
    def __init__(self, manager: McpManager, check_interval: float = 5.0):
        self.manager = manager
        self.backoff: dict[str, float] = {}  # server name → next retry time

    async def run(self):
        while True:
            for name in list(self.manager.failed_servers):
                if time.time() < self.backoff.get(name, 0):
                    continue
                attempts = self.attempts.get(name, 0)
                if attempts >= 3:
                    continue  # give up
                ok = await self.manager.reconnect(name)
                if ok:
                    self.attempts[name] = 0
                    log.info(f"mcp.{name} recovered after {attempts} attempts")
                else:
                    self.attempts[name] = attempts + 1
                    self.backoff[name] = time.time() + 2 ** attempts  # 1s, 2s, 4s
            await asyncio.sleep(self.check_interval)
```

### 1.3 整合

`Conversation.__post_init__` 啟 McpSupervisor task,跟 conversation 生命週期綁:

```python
if self.mcp_manager:
    self.mcp_supervisor = McpSupervisor(self.mcp_manager)
    asyncio.create_task(self.mcp_supervisor.run())
```

### 1.4 通知

Server recovery / give-up → emit 事件 to caller:

- recovery → `NotificationEvent(level=info, message="mcp.<name> reconnected")`
- give-up → `NotificationEvent(level=error, message="mcp.<name> gave up after 3 retries")`

caller(UI / CLI)顯示給 user。

### 1.5 任務

- [ ] `mcp/supervisor.py` 寫 supervisor + tests
- [ ] `McpManager` 暴露 `reconnect(name)` 跟 `failed_servers` property
- [ ] `Conversation` 啟動 supervisor task
- [ ] Hook 系統發 `NotificationEvent`(若 hook 系統還沒這個 event,加)
- [ ] CLI / chat-api / Cowork 接 notification 顯示給 user

## 2. Cross-machine resume

### 2.1 現況

`Conversation.resume(session_id)` 從 `~/.orion/sessions/<id>/transcript.jsonl` 重建。但 transcript 在本機 → user 換機器就拿不到。

### 2.2 設計

Postgres mode 已有 `Message` DB table 寫整段 transcript,**但 resume 路徑仍走檔案**(transcript.jsonl)。改:設 `ORION_DB_URL=postgresql://...` 時,resume 改從 DB 載入。

### 2.3 流程

```python
# storage/resume.py
async def resume_from_db(session_id: UUID, engine) -> Conversation:
    async with db_session(engine) as s:
        session_row = await s.get(Session, session_id)
        if not session_row:
            raise ValueError("session not found")
        msgs_rows = await s.execute(
            select(Message).where(Message.session_id == session_id).order_by(Message.turn_index)
        )
        state_messages = [reconstruct_normalized_message(m) for m in msgs_rows.scalars()]
    return Conversation(provider=..., state_messages=state_messages, session_id=session_id, ...)
```

### 2.4 大 tool result 處理

DB 存的訊息包含 placeholder(tombstone)。完整大結果在 `~/.orion/sessions/<id>/tool-results/` — 換機器拿不到。三個選項:

- **Option A**:大結果也存 DB(`large_results` table,blob column)— 簡單但 DB size 爆炸
- **Option B**:大結果存 S3 / object storage,DB 存 reference URL — 工程量大
- **Option C**:接受 cross-machine resume 看不到大結果(只看到 placeholder),user 知道有東西但不能展開

**建議:Option C**。簡單,90% 場景已夠。Option A/B 留給 Phase 32+。

### 2.5 任務

- [ ] `storage/resume.py:resume_from_db()` 實作
- [ ] `Conversation.resume()` 判斷 `ORION_DB_URL` env → 走 DB 路徑;否則檔案路徑
- [ ] chat-api `POST /sessions/<id>/resume` endpoint(若還沒有)
- [ ] 文件加 "Cross-machine resume 看不到大結果" caveat

## 3. 風險

| 風險 | 緩解 |
|---|---|
| Supervisor 跟 manager 競爭(同時 reconnect) | reconnect 用 lock per server name |
| 3-retry give up 太早 / 太晚 | 環境變數可調 `ORION_MCP_MAX_RETRIES` |
| DB resume 載入大 transcript(>10MB)慢 | 加 pagination / lazy load(只載最近 N turn,舊 turn 按需 fetch)|
| DB schema migration 衝突 | 用 alembic version 控制,upgrade 失敗顯示明確 error |

## 4. 驗收

- [ ] 殺 MCP server 進程 → 5 秒內 supervisor 偵測 → 嘗試 reconnect → 成功則 user 看到通知;失敗 3 次後 give up
- [ ] Postgres 模式:在機器 A 跑對話 → 機器 B 登入同 user → 可看到對話列表 → resume → 訊息歷史可見(大結果 placeholder)
- [ ] DB resume 性能:200 turn 對話 < 2 秒 load 完

## 5. 完成後

Phase 31-H 完成 = SDK polish 結束。Track 3 結束。Phase 31 整個結束。

整 Phase 31 完工 → `git rm` 整個 `plans/31-phase30-followup/` 目錄 + 在 `../../done.md` 加一行:
```
- Phase 31 — Phase 30 follow-up (Cowork ship-readiness + e2e infra + SDK polish):<commit hash>
```

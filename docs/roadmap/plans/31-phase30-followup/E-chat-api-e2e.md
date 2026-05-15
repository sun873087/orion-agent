# Phase 31-E:Chat-api e2e infra

## 速覽

- **預計時程**:1 週
- **前置 Phase**:無(Track 2 獨立,可跟 Track 1 平行)
- **狀態**:📝 spec only,**未實作**(目前只有 `apps/orion-chat/tests/e2e/README.md` placeholder)
- **目標**:完整 stack e2e — Postgres + chat-api + WS client + REST,驗證 happy-path + 主要 sad-path。

## 1. 為何要

現有 102 個 chat-api unit tests 都跑 in-memory:

- `InMemorySessionManager`(實際 production 用 Postgres `DbSessionManager`)
- mock LLM provider(實際 production 打真 anthropic / openai)
- TestClient(實際 production 走 ASGI server + WebSocket upgrade)

production blind spots:
- Postgres migration / schema 變動的 FK / cascade 行為
- WS protocol 在真 server 下的 framing / ping/pong / disconnect
- Long-running session 跨 turn 的 DB state 一致性

e2e 解這些。

## 2. 範圍

### 2.1 In scope

- Docker Postgres container(per test session)
- 完整 uvicorn 跑 chat-api
- httpx + websockets 當 client
- happy-path:register → login → create session → WS send prompt → 收 streaming → DB 驗證
- sad-path:auth fail、session not found、abort、reconnect

### 2.2 Out of scope

- 真 LLM call(用 `MockProvider` 注入,避免 e2e 成本爆 + flaky)
- web frontend(那是 unit / Playwright 任務,另開)
- Multi-user 高並發壓力測試(plan 10c 範圍)

## 3. 任務拆解

### 3.1 Test container fixture

```python
# apps/orion-chat/api/tests/e2e/conftest.py
import pytest
from testcontainers.postgres import PostgresContainer

@pytest.fixture(scope="session")
def postgres_url():
    with PostgresContainer("postgres:16-alpine") as pg:
        url = pg.get_connection_url().replace("psycopg2", "asyncpg")
        yield url
```

`testcontainers` pypi package — 啟動 Docker container,測完自動 cleanup。

### 3.2 chat-api fixture

```python
@pytest.fixture
async def chat_api_server(postgres_url, unused_tcp_port):
    os.environ["ORION_DB_URL"] = postgres_url
    os.environ["ORION_DB_AUTO_CREATE"] = "1"
    config = uvicorn.Config("orion_chat_api.app:app", port=unused_tcp_port, log_level="warning")
    server = uvicorn.Server(config)
    task = asyncio.create_task(server.serve())
    await wait_for_port(unused_tcp_port)
    yield f"http://127.0.0.1:{unused_tcp_port}"
    server.should_exit = True
    await task
```

### 3.3 MockProvider 注入

Production code 走 `get_provider()` 拿真 SDK。E2e 要替換成 mock。

方案:加 env var `ORION_PROVIDER_OVERRIDE=mock` → `get_provider()` 走 mock factory(回 `MockProvider` from `orion_sdk._testing`)。

```python
# packages/orion-model/src/orion_model/provider.py
def get_provider(name, model):
    if os.getenv("ORION_PROVIDER_OVERRIDE") == "mock":
        from orion_sdk._testing import MockProvider
        return MockProvider()  # 但要設定 scripted turns,要 fixture inject
    ...
```

更好:fixture 內 monkey-patch `orion_chat_api.session_manager.get_provider` 為 lambda 回 fixture-defined MockProvider。

### 3.4 WS client wrapper

```python
async def open_ws(url, session_id, token):
    return await websockets.connect(f"{url.replace('http', 'ws')}/chat/stream/{session_id}?token={token}")

async def collect_events(ws, until="loop_terminated"):
    events = []
    async for raw in ws:
        ev = json.loads(raw)
        events.append(ev)
        if ev.get("type") == until:
            return events
```

### 3.5 happy-path test

```python
async def test_full_chat_flow(chat_api_server, mock_provider_setup):
    base = chat_api_server
    # Register + login
    r = await httpx.AsyncClient().post(f"{base}/auth/register", json={"username": "alice", "password": "p"})
    token = r.json()["access_token"]
    # Create session
    r = await client.post(f"{base}/sessions", headers={"Authorization": f"Bearer {token}"})
    sid = r.json()["id"]
    # WS
    ws = await open_ws(base, sid, token)
    await ws.send(json.dumps({"type": "user_message", "text": "hi"}))
    events = await collect_events(ws)
    assert any(e["type"] == "assistant_text_delta" for e in events)
    assert events[-1]["type"] == "loop_terminated"
    # DB check
    async with db_session(...) as s:
        msgs = await get_messages(s, sid)
        assert len(msgs) >= 2  # user + assistant
```

### 3.6 sad-path tests

- Auth fail(WS without token / bad token)
- Session not found(WS to non-existent sid)
- Abort mid-turn(WS send abort,assert turn terminates with reason="aborted")
- Reconnect mid-conversation(close WS,re-open,assert state preserved)

### 3.7 Makefile target

```makefile
test-e2e-chat:
	cd apps/orion-chat/api && uv run pytest tests/e2e -v -m e2e
```

Pytest marker `@pytest.mark.e2e` 預設 skip(`-m "not e2e"` 預設),要明確 `-m e2e` 才跑。

## 4. CI

GitHub Actions matrix:

- runner:`ubuntu-latest`
- services:`docker`(testcontainers 用)
- step:`make install` → `make test-e2e-chat`
- 失敗時上傳 chat-api log artifact

## 5. 風險

| 風險 | 緩解 |
|---|---|
| testcontainers 啟動慢(~10s) | scope="session" fixture,測試 suite 共用一個 container |
| Postgres pool / asyncpg event loop conflict | fixture 內仔細管 engine lifecycle |
| Port 衝突 | 用 `unused_tcp_port` fixture |
| Flaky:WS 訊息順序非 deterministic | 用 `until=` 條件 wait,不 assert 絕對順序 |

## 6. 驗收

- [ ] `make test-e2e-chat` local 跑得起來,5 個以上 happy + sad path test 全綠
- [ ] CI workflow 加 e2e job,綠的(若有 CI)
- [ ] 跑時間 < 60 秒(testcontainer 啟動 10s + tests 30s)

## 7. 完成後

Phase 31-E 完成 = chat-api 有產線 confidence。

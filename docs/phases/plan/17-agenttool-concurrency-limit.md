# Phase 17:AgentTool 全域並發上限

## 速覽

- **預計時程**:半天
- **前置 Phase**:Phase 6(FastAPI multi-session)— 單一 conversation 不會碰到問題,multi-conversation 才需要
- **觸發來源**:Phase 1 完工後觀察:`AgentTool` 是 non-concurrency-safe 但 multi-session 部署下會有跨 session concurrent sub-agent
- **主要交付物**:
  - 全域 `anyio.Semaphore` 限制同時跑的 sub-agent 數量
  - 觸碰上限時 wait queue(不是 fail)
  - 環境變數 `ORION_MAX_SUB_AGENTS`(預設 5)

## 1. 為何要做

目前狀態:
- 單 agent loop 內 `AgentTool.is_concurrency_safe = False` → 同 batch 不並發
- 但跨 conversation 沒任何限制 → multi-user 時可能同時跑 10+ sub-agent
- 每個 sub-agent 開新 LLM 連線 + 自己的 query_loop,**很容易撞 provider rate limit**

## 2. 任務拆解

- [ ] `tools/agent/agent_tool.py:AgentTool.__init__` 接受可選 `semaphore: anyio.Semaphore`
- [ ] `services/feature_flags.py` 或新 `services/limits.py` 提供全域 default semaphore(讀 `ORION_MAX_SUB_AGENTS`)
- [ ] `AgentTool.call` 內 `async with self._semaphore:` 包整個 sub query_loop
- [ ] Phase 6 FastAPI startup 時建立 process-wide semaphore 並注入

## 3. 設計決策

### Semaphore vs Queue

`anyio.Semaphore` 簡單:N 個位、滿了就 wait。Queue 多了排隊邏輯,沒必要。

### 全域 vs per-conversation

per-conversation 沒意義(單 loop 已 sequential);全域才解決 multi-user 撞 rate limit。

## 4. 驗收標準

```python
# tests/unit/tools/test_agent_tool_limit.py
async def test_max_concurrent_sub_agents():
    sem = anyio.Semaphore(2)
    tools = [AgentTool(provider=p, child_tools=[], semaphore=sem) for _ in range(5)]
    # 同時 fire 5 個 → 同時間最多 2 個在跑
    ...
```

## 5. 相關 code

- `orion_agent/tools/agent/agent_tool.py`
- 可能新建 `orion_agent/services/limits.py`

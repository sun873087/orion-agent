# Phase 15 — Multi-Agent Patterns 完工記錄

**完成日期**:2026-05-08
**Plan doc**:`docs/phases/15-multi-agent.md`(範圍:3 大塊 — Coordinator(leader-worker)
+ Swarm(peer-to-peer)+ AgentSummary。**spec § 5.6 AgentTool 整合(`subagent_type=
coordinator/swarm`)拆出為新 phase plan `docs/phases/plan/24-multiagent-tools.md`,本
phase 不做** — 動 AgentTool input schema 會破壞既有 model contract,獨立評估。
Redis cross-process MessageBus、worker token budget 共用、voting/consensus 等
spec § 6 故意不做的項目,維持不做。)
**狀態**:✅ `make check` 全綠 — **742 unit tests passed, 2 skipped**(25.15s),
ruff clean,mypy --strict 202 files clean。

Phase 14 → Phase 15 新增 **34 unit tests**(types 6 / message_bus 9 / agent_summary 5 /
coordinator 7 / swarm 7)。2 個 skip 是 Phase 7 docker_backend(既有,需 docker daemon)。

---

## 交付清單

### 新增模組

```
src/orion_agent/multi_agent/        [全新,6 檔]
├── __init__.py                     export Coordinator / SwarmRunner /
│                                    MessageBus / generate_agent_summary 等
├── types.py                        TaskAssignment / WorkerReport / PeerMessage
├── agent_summary.py                generate_agent_summary(用 side_query + Haiku)
├── coordinator.py                  Coordinator + CoordinatorResult,並行 dispatch +
│                                    失敗隔離 + 用 run_forked_agent 共享父 cache
├── message_bus.py                  in-process pub/sub(MemoryObjectStream)+
│                                    subscribe(name) 回 ReceiveStream(支援 idle timeout)
└── swarm.py                        SwarmRunner + SwarmAgent / Config / Result +
                                     @mention parser + idle_timeout + STOP_SWARM
```

### Tests(新增 5 檔,共 34 案例)

```
tests/unit/multi_agent/             [全新]
├── __init__.py
├── test_types.py                   6 tests(TaskAssignment id 唯一 / extra_forbid /
│                                            WorkerReport completed/failed /
│                                            PeerMessage default broadcast / unicast)
├── test_message_bus.py             9 tests(unicast / unknown / no to_agent /
│                                            broadcast 排除 sender / dup subscribe /
│                                            close after subscribe / close terminates /
│                                            full queue drops / agents property)
├── test_agent_summary.py           5 tests(text msgs / empty / tool_use blocks /
│                                            provider failure fallback / truncate)
├── test_coordinator.py             7 tests(3 workers parallel + 順序對齊 / empty /
│                                            too many → ValueError / failure 隔離 /
│                                            usage 加總 / summary_provider=None /
│                                            summary_provider 啟用)
└── test_swarm.py                   7 tests(2-agent mention 互通 / max_rounds caps /
                                             leader STOP_SWARM / dup names raise /
                                             unknown leader raise / empty initial 等
                                             mention / self-mention 忽略)
```

---

## 設計決策

### 1. 三種 pattern 平行存在,不互相取代
- **Sub-agent**(Phase 1 / 9 已有):父 → 1 子,線性
- **Coordinator**(Phase 15):1 父 → N 並行 worker,聚合
- **Swarm**(Phase 15):N 對等 peer 互傳訊息

呼叫端依任務性質選用。Coordinator 適合多面向 review;Swarm 適合辯論 / 模擬。

### 2. Coordinator 用 run_forked_agent 跑 worker(共享父 cache)
spec § 6 第一個設計決策。N 個 worker 各自全新 Conversation 會 N 倍 token 成本;
fork 共享父 prompt prefix → cache hit。
worker 跑 query_loop(可用工具),非單純 single LLM call。

### 3. Swarm 不用 forked_agent — 每 agent 獨立 system_prompt
Swarm peer 各自有 role(`security-reviewer` / `perf-analyzer` / etc.),system_prompt
不同 → cache 無法共享。直接用 `provider.stream` + 累積 NormalizedMessage history,
每 agent 一個 mini conversation。spec § 9 踩雷 #5 對應(swarm 的 cache miss 是
acceptable cost)。

### 4. @mention 解析用 regex,不寫工具
spec § 6 設計決策。模型熟 Twitter / Slack 風格;`@<name>: <msg>` 寫在自然語言內,
模型寫完一段話自然 mention 即可。比每次發訊息都 tool_use 直觀。

regex `r"@(\w[\w\-]*)\s*:\s*(.+?)(?=(?:\s*@\w[\w\-]*\s*:)|\Z)"` — 支援 hyphen,
內容延伸到下個 @mention 或結尾。

### 5. AgentSummary 用 Haiku
spec § 6 設計決策。摘要任務固定 pattern(2-4 句、focus DONE),Haiku 處理足夠。
省成本 5x。本 phase 範圍只提供 `generate_agent_summary(messages, *, provider)`
接口 — 由 caller 傳 Haiku provider;coordinator 接受 `summary_provider` 參數注入。

### 6. AgentSummary 失敗 fallback,不 raise
摘要是 best-effort 附加值。`side_query` 失敗 / 空文字輸出 → 回
`[<agent_name> completed work without summary]`。**主流程 dispatch / swarm.run
不能因摘要失敗而炸**。

### 7. MessageBus subscribe 回 MemoryObjectReceiveStream(不是 AsyncIterator)
原本 spec § 5.4 範例是包成 async generator。實作中為了支援 `idle_timeout`(spec § 9
踩雷 #3),改回 raw `MemoryObjectReceiveStream`,caller 可以 `await stream.receive()`
配 `anyio.move_on_after` 做 timeout。`async for` 也仍可用。

### 8. SwarmRunner 預先 subscribe 全部 agent
race condition:`task_group.start_soon` 不保證 task 立即執行;leader 可能跑完
`STOP_SWARM` 並 close bus,worker 才 start_soon → subscribe raise `MessageBus is
closed`。

修法:`run()` 主流程先 `bus.subscribe(name)` 全部,再 spawn tasks。tasks 從
`self._subscriptions[name]` 取 stream。spec 沒提這個踩雷,實作測試發現。

### 9. SwarmRunner idle_timeout 防死鎖
2 個 agent 互傳訊息 → 各自 round 1 後再回 round 2,無人主動結束 → 都卡 `async for`。
`idle_timeout_s=1.0`(預設):agent 連續 1 秒沒收新訊息 → 收工。
spec § 9 踩雷 #3 對應(per-agent timeout)。

### 10. SwarmRunner active counter:歸 0 → close bus
最後一個 agent 退出 _run_one 時 close bus,讓其他 agent 的 receive() 退出
EndOfStream。實際上有 idle_timeout 已避免大部分死鎖,active counter 是雙保險。

### 11. Coordinator dispatch 結果順序與 assignments 對齊
holders 預先佔位,index 對齊;併發完成時 `holders[i] = report`。caller 拿到的
`reports[i].task_id == assignments[i].task_id`(同序),避免要靠 task_id dict 對應。

### 12. 個別 worker 失敗回 status="failed",其他不受影響
spec § 6 的失敗策略。`_run_worker` 包 try/except,raise 變
`WorkerReport(status="failed", error=...)`。Coordinator.dispatch 仍正常返回所有
reports;caller 自己看 `result.failed` / `result.succeeded`。

### 13. CapacityLimiter 限併發
`anyio.CapacityLimiter(max_workers)` 強制最多 N 個 worker 同時跑。N+1 個 assignment 一
進來 → ValueError(對應 spec § 9 踩雷 #1 不讓成本爆)。

### 14. self-mention 不投遞
agent 寫 `@<自己>: ...` → bus.send 不跑(避免 agent 自言自語成迴圈)。spec 沒提
這個但 test cover。

### 15. SwarmAgent 是 frozen dataclass
不可變(name / role / system_prompt / initial_prompt)。SwarmConfig 是 mutable
dataclass(可以調 max_rounds 等)。spec 範例混用,本實作明確分。

### 16. AgentTool input schema 不動(對應 spec § 5.6 拆出去)
本 phase 純 Python API,呼叫端是另一段 Python 程式碼,**不暴露給模型**。
對應 spec § 5.6 的 AgentTool 整合 → `docs/phases/plan/24-multiagent-tools.md`。
這樣既有 `test_agent_tool.py` 全綠不動,model contract 不變。

---

## REST API 變更

無。Phase 15 全是 Python 內部 API。

---

## 環境變數

無新環境變數。

---

## Verification

```bash
cd orion-agent/api/

make check
# → ruff All checks passed!
# → mypy --strict: 202 files, 0 issues
# → pytest: 742 passed, 2 skipped(25.15s)

# Coordinator demo(3 workers 並行 + 順序對齊)
.venv/bin/python -c "
import asyncio, sys
sys.path.insert(0, 'tests')
from conftest import MockProvider, MockTurn
from orion_agent.core.state import AgentContext
from orion_agent.multi_agent import Coordinator, TaskAssignment
from orion_agent.services.forked_agent import CacheSafeParams

provider = MockProvider(turns=[
    MockTurn(text='security findings'),
    MockTurn(text='perf findings'),
    MockTurn(text='ux findings'),
])
cs = CacheSafeParams.from_parts(system_prompt='you review code', tools=[], messages=[])

async def main():
    c = Coordinator(ctx=AgentContext(), provider=provider, cache_safe_params=cs)
    result = await c.dispatch([
        TaskAssignment(description='Security review'),
        TaskAssignment(description='Perf review'),
        TaskAssignment(description='UX review'),
    ])
    for r in result.reports:
        print(f'{r.worker_id} [{r.status}]: {r.final_text}')

asyncio.run(main())
"
# 預期:三 worker 各自 final_text 含對應 review 內容

# Swarm demo(2-agent mention 互通)
.venv/bin/python -c "
import asyncio, sys
sys.path.insert(0, 'tests')
from conftest import MockProvider, MockTurn
from orion_agent.multi_agent.swarm import SwarmAgent, SwarmConfig, SwarmRunner

provider = MockProvider(turns=[
    MockTurn(text='@b: please review the schema'),
    MockTurn(text='@a: looks good but consider indexing'),
    MockTurn(text='thanks b!'),
])
config = SwarmConfig(
    agents=[
        SwarmAgent(name='a', role='asker', system_prompt='You are A.', initial_prompt='start'),
        SwarmAgent(name='b', role='reviewer', system_prompt='You are B.', initial_prompt=''),
    ],
    max_rounds=3,
    idle_timeout_s=0.5,
)
async def main():
    r = SwarmRunner(config=config, provider=provider)
    result = await r.run()
    print('rounds:', result.rounds_run)
    for name, log in result.logs.items():
        print(f'--- {name} sent ---')
        for m in log.sent_messages:
            print(f'  to {m.to_agent}: {m.content[:60]}')
asyncio.run(main())
"
# 預期:a 跑 1+ 輪、b 跑 1+ 輪;a 有送訊息給 b,b 有送回 a
```

---

## Tests 摘要

| Suite | 數量 | 說明 |
|---|---|---|
| Phase 0–14 既有 | 708 | 全綠不動 |
| **Phase 15 types** | 6 | TaskAssignment / WorkerReport / PeerMessage |
| **Phase 15 message_bus** | 9 | unicast / broadcast / close / full queue / dup |
| **Phase 15 agent_summary** | 5 | text / empty / tool_use blocks / failure / truncate |
| **Phase 15 coordinator** | 7 | parallel + 對齊 / empty / 超量 / 失敗隔離 / usage / summary |
| **Phase 15 swarm** | 7 | mention / max_rounds / STOP_SWARM / dup / leader / empty initial / self |
| **總計** | **742 passed / 2 skipped** | mypy --strict 202 files / ruff 全綠 |

---

## 風險與已緩解

| 風險 | 緩解 |
|---|---|
| Coordinator 太多 workers cost 爆 | `max_workers=5`(預設),N+1 個 assignment 一進來 raise ValueError |
| Worker fork 失敗單點故障擴散 | 個別 worker 包 try/except → status="failed",其他繼續 |
| Swarm 訊息洪流 | queue 滿 → 丟新訊息(spec § 9 踩雷 #2);max_rounds 強制結束 |
| Swarm 死鎖(互等對方先講) | `idle_timeout_s=1.0` 預設 → 沒新訊息 1 秒就收工 |
| Swarm task 啟動 race(leader 先 close bus) | run() 主流程預先 subscribe 全部,再 spawn tasks |
| Worker 無限 fork(層級遞迴) | `AgentContext.sub_agent_depth` 在 fork 時 +1(Phase 9 既有);Coordinator 用的 forked_agent 已繼承 |
| 跨 process swarm(K8s 多 pod)| 本 phase 不做(in-process bus 適合單 worker);留 phase 25 視需求 |
| AgentTool 整合改 input schema 破壞 model contract | 不動 AgentTool;新工具 / mode 拆 phase 24 獨立評估 |
| @mention 對自己 → 自言自語迴圈 | self-mention 不投遞 bus(test cover) |
| AgentSummary 失敗連鎖 | 摘要失敗 fallback `[name completed work without summary]`,coordinator dispatch 不 raise |

---

## 內部對應 spec 的差異

| Spec § | 差異 | 為何 |
|---|---|---|
| 5.1 SyncCursor / SettingDiff(從 Phase 14 章節誤帶過) | 不適用本 phase | spec 章節編號錯誤,本 phase 是 multi-agent 不是 sync |
| 5.2 `Coordinator(ctx, cache_safe_params, max_workers)` | 改 keyword-only + 加 `provider` / `worker_can_use_tool` / `summary_provider` 參數 | mypy --strict 偏好顯式 keyword;provider 必傳(forked_agent 需要);policy / summary 注入式 |
| 5.2 `_extract_summary` / `_extract_result` | 不實作,改在 Coordinator 用 `summary_provider` 注入 | 從 worker 訊息「猜」結果太脆弱;callee 用 SyntheticOutputTool 結構化輸出比較對 |
| 5.3 Swarm `subscribe()` 回 AsyncIterator | 改回 `MemoryObjectReceiveStream`(原始 stream) | 支援 idle_timeout(spec § 9 踩雷 #3 要求);async for 也仍可用 |
| 5.3 Swarm `_agent_turn` 用 side_query | 改用 `provider.stream` + 累積 history | side_query 是 single-call、不維護歷史;swarm 多輪需要 agent 看過之前對話 |
| 5.4 RedisMessageBus | **完全不做**,介面 in-process | spec § 6 設計決策已標明 in-process 預設;Redis 留新 phase 視需求 |
| 5.6 AgentTool 改 input schema 整合 | **拆出 → `docs/phases/plan/24-multiagent-tools.md`** | 動 input 破壞既有 model contract / test;獨立 phase 評估 |
| 6 worker token budget 共用 | **不做**,留新 phase | 設計爭議大(共用 vs 獨立 fairness);留 phase 24 連同 AgentTool 整合一起想 |
| 6 SubagentStart hook 整合 | **不做**(本 phase Python API 不過 tool 介面)| Phase 8 hook 是 tool 級別,Phase 15 是 lib 級別,等 phase 24 工具化再加 |

---

## 實作中發現的坑

### 1. Swarm task 啟動 race
`task_group.start_soon` 不會立即執行 task。可能發生:
- task 1 (leader) 已跑完 round 1 + STOP_SWARM + close bus
- task 2 (worker) 才被 schedule → `bus.subscribe()` raise `MessageBus is closed`

修:run() 主流程先 sync 跑 `for agent: bus.subscribe(name)`,然後才 spawn tasks。
`_run_one` 從 `self._subscriptions[name]` 拿 stream(已 closed bus 也拿到 stream
本身,只是 receive 會 EndOfStream,符合預期)。

### 2. Swarm idle_timeout 防死鎖
2-agent ping-pong:
- a initial → "@b: hi"  → bus 投遞 b
- b 收到 → "@a: hello" → bus 投遞 a
- a 收到 → "thanks"(no @mention)→ a 卡 async for
- b 卡 async for(沒新訊息)
- 兩邊都不送訊息 → max_rounds 還沒達到 → 永遠死鎖

修:每次 receive 用 `anyio.move_on_after(idle_timeout_s)` 包,超時 = 收工。
spec § 9 踩雷 #3 對應。

### 3. `MemoryObjectReceiveStream` 而非 AsyncIterator
原本想包成 async generator(spec 範例)。實作 idle_timeout 時發現 async generator
的 `__anext__` 不太好配 `move_on_after`(要手動處理 cancellation);**直接 return
`MemoryObjectReceiveStream`** 讓 caller `await stream.receive()` 配 `move_on_after`
最乾淨。

### 4. Coordinator holders 預先佔位保 order
`tg.start_soon(_store, i, a)` 結果順序非定;**預先 `holders = [None] * N`**,各 task
寫對應 index → 最後 filter None。維持 caller 視角的 reports 順序與 assignments 對齊。

### 5. mock provider 跨 worker 共用 turns 順序
`MockProvider.turns` 是 list,3 worker 並發消費 → 哪個 worker 拿哪 turn 不定。
測試只 assert「全部都含 result 字」(寬鬆),不 assert 具體 worker 拿哪 turn。

### 6. SwarmAgent frozen dataclass + ConfigDict(extra="forbid")
SwarmAgent 是 frozen(immutable);PeerMessage / TaskAssignment / WorkerReport 用
Pydantic + `ConfigDict(extra="forbid")` — 多帶欄位 raise,接住 caller typo。
test_task_assignment_extra_forbid cover。

### 7. self_mention 過濾條件用 set lookup
`agent_names = {a.name for a in self.config.agents}`(set,O(1))。每次
parse 都用,放 _dispatch_mentions 開頭 build。實際 swarm agent 數量小(< 10),
但寫成 set 是好習慣。

### 8. AgentSummary 用 side_query 而非 forked_agent
Summary 是 single LLM call(`system + user + max_tokens`),沒跑工具,沒多輪。
forked_agent 過度殺雞;side_query 正合。caller 傳 Haiku provider 就便宜快。

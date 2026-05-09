# Phase 10c — Stress Test + Capacity Planning + Sentinel SubprocessPool

**狀態**:📋 Plan(等實際 production data / cluster 出現)
**前置**:Phase 10 完成(26 工具 + perf 框架 + OTel + cost tracker)
**估時**:1-2 週(含 production rollout 期間調校)

## 動機

Phase 10 範圍 C 已交付完整工具集 + perf 模組(profiler / subprocess_pool 框架)。
**沒做**:
- 真的跑大量並行對話看哪裡是瓶頸
- 從 OTel 數據(Phase 9)推 capacity(每核心多少 RPS / 每 GB 多少 session)
- SubprocessPool sentinel-based 真重用 worker(Phase 10 只 framework)

production 上線後一陣子才會有真 metric,本 phase 是**事後微調**用,不是 day 1。

## 範圍

### 做

| 項目 | 說明 |
|---|---|
| **Sentinel SubprocessPool** | 改寫 `perf/subprocess_pool.py` worker:long-lived /bin/sh,每命令前後寫 sentinel(隨機 8 byte hex),parse stdout 抓 rc / output 區段,真重用 worker |
| **Stress harness** | `tests/stress/` — 用 `httpx.AsyncClient` 模擬 N 個 user 並行 chat;測 turn latency p50 / p95 / p99、error rate、memory 增長 |
| **Capacity guide** | `docs/capacity-planning.md` — 從 OTel 數據推:單 instance 多少 concurrent session、多少 turn/sec、PG / Redis 容量規劃 |
| **Profiler 報告** | 跑一輪 stress → pyinstrument dump → 找 top 5 hot path,寫 `docs/perf-findings.md` |
| **Cache hit ratio 調校** | Phase 4 boundary marker 位置、Phase 9 cache_hit_ratio metric 看比率 → 調 system prompt section 順序 |
| **gRPC keep-alive / connection pool** | OTel exporter / Anthropic SDK / Postgres asyncpg 都調 keep-alive |
| **Memory leak hunting** | 跑 1000+ turn 看 RSS;用 `tracemalloc` / `objgraph` 找泄漏點 |
| **K8s HPA 設定推薦** | CPU / memory / custom metric(turn rate)trigger threshold |

### 不做

- Auto-scaling 邏輯本身(由 K8s HPA 處理)
- Region-aware load balancing(看實際多 region 才需要)
- Database sharding(per-tenant 留 Phase 11+)

## 檔案結構

```
src/orion_agent/perf/
└── subprocess_pool.py                  [改] sentinel-based 真重用 worker

tests/stress/                           [全新]
├── conftest.py                         async client + 模擬 user 工廠
├── test_concurrent_turns.py            N user × M turn,測 latency 分佈
├── test_long_session.py                單 session 跑 100+ turn,測 cache hit / memory
└── README.md                           跑法 + 解讀指南

docs/
├── capacity-planning.md                從 OTel 數據推容量
├── perf-findings.md                    pyinstrument top 5 hot path + 改善方向
└── phase-10-completion.md              [改] 加 stress section
```

## 實作順序(8 步)

| Step | 工作 |
|---|---|
| 1 | sentinel-based subprocess pool:protocol 設計(隨機 8B hex sentinel + rc 取法) |
| 2 | 重寫 `exec_simple`,實 hits 走 worker(不再 fallback fork) |
| 3 | 加 unit test 驗 worker 真重用(同一 PID 跑兩條命令) |
| 4 | `tests/stress/conftest.py`:asyncio.gather(simulate_user(i) for i in range(N)) |
| 5 | `test_concurrent_turns.py`:N=20、M=10 turn → assert p95 < threshold |
| 6 | 跑 stress + dump pyinstrument 報告 → 整理 top 5 hot path |
| 7 | `docs/capacity-planning.md`:單 instance baseline + 推 K8s HPA 設定 |
| 8 | docs/phase-10c-completion.md + 把 perf-findings 連進 Phase 10 完工 doc |

## Sentinel SubprocessPool 設計

```python
SENTINEL = "<<<ORION_END_8a3f>>>"

async def exec_in_worker(worker, command, timeout):
    sentinel = secrets.token_hex(4)
    # 寫:command;然後寫 echo SENTINEL$? 標記結束 + rc
    payload = f"{command}\necho '<<<ORION_END_{sentinel}_'$?'>>>' \n"
    worker.stdin.write(payload.encode())
    await worker.stdin.drain()
    # 讀 stdout 直到看到 sentinel,parse rc
    ...
```

注意:
- worker 用 `bash` 不是 `sh`(`set -o pipefail` etc.)
- 每命令獨立 sentinel,避免 race
- timeout → SIGKILL worker + 從 pool 移除 + spawn 新的(不重用 broken worker)
- stderr 合進 stdout(`exec 2>&1` 在 worker init)

## Stress Harness 設計

```python
# tests/stress/test_concurrent_turns.py
@pytest.mark.stress
async def test_20_users_10_turns_each():
    async with httpx.AsyncClient(...) as client:
        # 20 個 token
        tokens = [await login(client, f"user{i}") for i in range(20)]
        # gather:每 user 跑 10 turn
        latencies = await asyncio.gather(*[
            run_user_session(client, tokens[i], n_turns=10)
            for i in range(20)
        ])
        flat = sorted([l for user in latencies for l in user])
        assert quantile(flat, 0.95) < 5.0  # p95 < 5s
```

跑法:`pytest tests/stress -m stress --runstress`(預設 skip,只在指定時跑)。

## Capacity 算法(草稿)

從 Phase 9 metric:
- `orion_agent_turn_duration` p95 = X ms
- `orion_agent_api_latency` p95 = Y ms(LLM API,佔 turn 大部份)
- `orion_agent_tool_duration_count` rate = Z calls/sec

推:
- 單 turn CPU 佔用 ≈ X - Y ms(我方計算量)
- 單 instance N 核 → max RPS ≈ N * 1000 / (X - Y)
- 加 30% buffer → recommend HPA target = max RPS * 0.7
- Memory:per session ~10MB(state_messages + replacement_state)→ M GB → 1000 * M concurrent sessions

## Verification

```bash
# 1. sentinel pool unit test
uv run pytest tests/unit/perf/test_subprocess_pool.py -v
# 預期:看到 "test_worker_reused_across_calls" PASSED 且同 PID

# 2. stress
uv run pytest tests/stress -m stress --runstress
# → 印 latency 分佈 + 是否符合 SLA

# 3. profiler dump
OTEL_EXPORTER_OTLP_ENDPOINT="..." \
  uv run python tests/stress/dump_profile.py 2>&1 | tee /tmp/profile.txt
head -100 /tmp/profile.txt   # top 10 hot function

# 4. capacity 試算
uv run python tests/stress/capacity.py --otel-endpoint http://localhost:4317
# 印推薦 HPA 設定
```

## 風險

| 風險 | 緩解 |
|---|---|
| Sentinel 被 user command 偽造(模型呼叫帶 sentinel 字串) | sentinel 帶 8B random hex,user 偽造機率 ≈ 2^-32;若擊中 → worker 重啟即可 |
| Worker 卡死(user command infinite loop) | 每命令有 timeout;timeout → SIGKILL worker + 重 spawn |
| Stress test 真打到 LLM API | 用 MockProvider(unit test infra 已有);只測 framework throughput,不測 LLM latency |
| Capacity 算法太樂觀(沒考慮 GC / cache miss) | 建議 30% buffer + 真 production data 反饋微調 |
| K8s HPA 太敏感 → 抖 | cool-down period + min replicas 2(避免縮到 0) |

## 完成 Phase 10c 後

orion-agent v1.0 — production-ready milestone。後續 phase(11+)做 input pipeline /
multi-tenant / 進階 OAuth 等 product-level feature。

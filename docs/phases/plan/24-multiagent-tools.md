# Phase 24:Multi-Agent Tools(將 Coordinator / Swarm 暴露給模型)

## 速覽

- **預計時程**:3-5 天
- **前置 Phase**:Phase 15(Coordinator / Swarm Python API 已就位)
- **本文件目的**:從 `docs/phases/15-multi-agent.md` § 5.6 拆出來。Phase 15 的
  multi-agent pattern 是 Python API,還沒暴露給 LLM 透過工具呼叫;本 phase 補。
- **主要交付物**:
  - `tools/agent/coordinator_tool.py` — 模型呼叫的 Coordinator 工具(吃 sub_tasks list)
  - `tools/agent/swarm_tool.py` — 模型呼叫的 Swarm 工具(吃 swarm_agents list)
  - 或:擴 `AgentTool.input` 加 `subagent_type=coordinator/swarm` + `sub_tasks` /
    `swarm_agents` 欄位(spec § 5.6 路徑)
  - Worker token budget 共用機制(spec § 9 踩雷 #6)

## 為何另開 phase?

Phase 15 spec § 5.6 提的 AgentTool 整合,實作要動 `AgentTool.input` 的 schema —
會破壞既有 model contract / 既有測試。Phase 15 完工已決定:

1. 先完成 multi-agent pattern 的 **Python API**(Coordinator / SwarmRunner / AgentSummary / MessageBus)
2. **暴露給模型的工具介面**單獨設計,獨立 phase plan(本檔)

本 phase 範圍純粹是「介面包裝」:Coordinator / SwarmRunner 已測試完成,只需想清楚:
- 兩個獨立工具(CoordinatorTool / SwarmTool)還是一個 AgentTool 多 mode?
- input schema 怎麼餵 list[TaskAssignment]?(JSON 字串 vs 結構化 array)
- worker permission policy 怎麼從父 ctx 繼承?

## 任務拆解

- [ ] 1. 設計決策:單一 AgentTool 多 mode vs 兩個獨立工具
- [ ] 2. 實作 input schema(`sub_tasks: list[dict]` 或 JSON string)
- [ ] 3. 整合 Phase 9 sub-agent isolation(每 worker 獨立 sandbox)
- [ ] 4. Worker token budget 共用機制(spec § 9 踩雷 #6)
- [ ] 5. 整合 hooks(SubagentStart for each worker)
- [ ] 6. 整合 telemetry(per-worker OTel span)
- [ ] 7. 測試 + Phase 24 心得

## 同時提的進階項目(可選)

| 項目 | 來源 | 狀態 |
|---|---|---|
| Redis cross-process MessageBus | Phase 15 § 6 設計決策 | 真要跨 K8s pod 才做,獨立 phase 25 視需要開 |
| Voting / consensus 機制 | Phase 15 § 6 故意不做 | 應用層,不在框架內 |
| 動態 agent spawn(swarm 中途加 agent) | Phase 15 § 6 | 預先 declare 即可,複雜度高,不開 |

## 驗收標準

```bash
pytest tests/unit/tools/agent/test_coordinator_tool.py \
       tests/unit/tools/agent/test_swarm_tool.py -v

# 手動:模型 call CoordinatorTool 觸發 3 workers 並行 review
> "Use coordinator to review this PR from 3 angles: security, perf, UX"
```

## 完成後寫

`orion-agent/docs/phase-24-completion.md`(zh-tw、含驗證指令、無 TODO)。

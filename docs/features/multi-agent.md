# Multi-agent

兩種多 agent 模式:Coordinator(leader-worker)+ Swarm(peer-to-peer)。

**實作位置**:`packages/orion-sdk/src/orion_sdk/multi_agent/`

## Coordinator(leader-worker)

主 agent 透過 `AgentTool` / `SubAgentCreate` spawn 子 agent 跑 sub-task,子 agent 完成回 result。

```
Main agent
    ├─ Spawn(specialist: "code-review", prompt: "...")    → child A
    ├─ Spawn(specialist: "test-writer", prompt: "...")     → child B
    └─ Spawn(...)                                          → child C
       (asyncio.gather — 平行)
    ▼
all return → main 看 result 決定下一步
```

特性:
- **單向資料流** — main 不能直接 send 子 agent 新訊息(子是 one-shot)
- **平行** — N 個子 agent asyncio.gather
- **Sub-agent 自帶 system prompt 跟 tools**(可被 main 限制)

## Swarm(peer-to-peer)

多個 agent 平等存在,可互相 send message,collaborative 完成 task。

```
Agent A ─── send "research X" ───▶ Agent B
   ▲                                  │
   │                                  │
   │             share notes          ▼
   └────── Agent C ◀────────── Agent B
```

特性:
- **互相 send**:`AgentSend(target_agent_id, message)`
- **共用 workspace + memory**(per-swarm)
- **Termination by consensus / timeout**

## 何時用哪個

| 場景 | 用 |
|---|---|
| 「研究 X、寫 test、跑 lint」三件平行做 | Coordinator(spawn 3 子) |
| 「multi-step planning + research + execute」三角色 collaborate | Swarm |
| 簡單 fan-out(都跑同樣 task,只是 input 不同) | Coordinator |
| 真實 long-running collaboration | Swarm |

## 設計取捨

- **Sub-agent 預設沒 memory**:避免 main 的 personal memory 漏給 sub。要 share 走 explicit input
- **Permission 繼承**:sub-agent 預設繼承 main 的 permission policy
- **Sub 失敗不擋 main**:gather 用 `return_exceptions=True`,main 看到 result list 內含 error

## 限制 / 已知問題

- **Swarm 還在早期**:peer message routing 沒持久化,crash 後 message in-flight 丟失
- **No cost attribution**:sub 跑的 token 算誰的?目前都算 main session
- **Sub recursion depth**:子可以再 spawn 孫,沒明確 cap

## 未來方向

- **Cost rollup**:sub 的 cost attach 到 main(usage_log 加 parent_session_id 欄)
- **Swarm 持久化**:message queue 進 DB,crash recovery
- **Agent identity / role 概念**:每個 agent 有 persistent identity,可跨 session 復用

## 看完繼續

- [tools.md](./tools.md) — `AgentTool` / `SubAgentCreate` / `AgentSend`
- [agent-loop.md](./agent-loop.md) — sub 是另一個 Conversation instance

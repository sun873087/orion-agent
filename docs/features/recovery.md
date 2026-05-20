# Recovery / Resume

中斷的對話可以從先前 session 繼續(reload 訊息歷史 + replacement state)。

**實作位置**:
- `packages/orion-sdk/src/orion_sdk/recovery/`
- `packages/orion-sdk/src/orion_sdk/storage/resume.py`

## 場景

- Crash 後重啟:DB 內 session 還在,把 last user msg 之後 incomplete 的 assistant 接著跑
- 手動 resume:`orion run --resume <session_id>`(CLI)/ Cowork 切回舊 session
- Plan mode AWAITING_APPROVAL:重啟後仍在等待狀態,UI 自動 re-emit notification

## 流程

```
session_id 拿到
    ▼
storage.load_session(engine, sid)
    ├─ Messages 從 DB(messages 表)依 message_index 排序拉出
    ├─ Plan state 從 cowork_session_ext 載入(若有)
    ├─ Budget state 從 cowork_session_ext 載入
    │
    ▼
build Conversation(messages=loaded, ...)
    ├─ 不重 inject system(用 saved 版本)— 避免 cache miss
    │
    ▼
若 last message 是 user 且 incomplete:
    auto-continue(call .send("")— 沒新 prompt 只接續舊的)
```

## Persist 時機

- **每 tool_result append 後** — fire-and-forget DB write,失敗 swallow(不擋 LLM)
- **Turn 結束** — final messages 寫進
- **Plan mode 狀態變化** — 寫 cowork_session_ext
- **Budget 累積** — 同上

## Cowork session_ext 擴充欄

`cowork_session_ext` 表(SDK 共用 `sessions` + Cowork 額外):

```
session_id (FK)
workspace_dir
project_id
plan_mode_status / plan_id / plan_file_path / plan_content
budget_usd_cap / budget_exceeded
auto_compact_enabled / auto_compact_threshold
...
```

## 限制 / 已知問題

- **Persist race**:若 host 在 LLM message append 跟 tool_result append 之間 crash,DB 內 partial 狀態 — re-load 可能撞 LLM 重複 tool_use。`resume.py` 內有 dedup 邏輯但不 100%。
- **Plan mode 跨重啟 OK,但 Approve 後 prod_task 中斷**:user 按 Approve 後 sidecar 把 follow-up 注入 + 跑 next turn,中間 crash → next turn 沒跑,但 plan state 已 idle。
- **CLI JSONL 沒 dedup**:CLI append-only JSONL,重新 send 同 prompt 會新增條目。

## 未來方向

- **Distributed lock for resume**:同 session_id 兩 instance 同時 resume → race。要 advisory lock。
- **Resume 對 multi-agent**:Coordinator 子 agent 中斷 — 是 main 一起 resume 還是子 agent 獨立?設計沒定。

## 看完繼續

- [storage.md](./storage.md) — session DB schema
- [agent-loop.md](./agent-loop.md) — Conversation 怎麼從 saved messages 建
- [cowork.md](./cowork.md) — Cowork resume UX

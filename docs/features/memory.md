# Memory

對話結束後 LLM 認為值得記的事實,以 markdown 檔形式存。每輪對話開始時 relevance
ranker 選 top-N 注入 system prompt — 等同 agent 的長期記憶。

**實作位置**:`packages/orion-sdk/src/orion_sdk/memory/`

## 存放位置

```
~/.orion/users/<user_id>/memory/
├── MEMORY.md                          ← index file(每行一條 memory pointer)
├── user-role.md                       ← memory record(frontmatter + body)
├── feedback-test-mocking.md
├── project-deadline-mar5.md
└── reference-deployment-runbook.md
```

每個 record 是一個 `.md` 檔,frontmatter 帶 metadata:

```markdown
---
name: user-role
description: User 是 senior Python dev,Phase 30+ 帶過全部 codebase
metadata:
  type: user
---

Senior Python developer working on the orion-agent monorepo. Familiar
with FastAPI, SQLAlchemy async, electron. Prefers terse explanations.
```

## 4 種 type

| Type | 用途 |
|---|---|
| **user** | User 的角色、背景、知識、偏好 |
| **feedback** | User 過去的 correction / 喜歡的做法 |
| **project** | 當前在做的 project、目標、決策、constraint |
| **reference** | 外部系統 / docs / URL 指引 |

## 寫入

LLM 透過 `MemoryWrite` tool 寫:

```
LLM:呼 MemoryWrite(name="user-role", type="user", body="...")
SDK:scan extracts → save to .md → update MEMORY.md
```

Tool 描述會引導 LLM 何時 / 寫什麼。`MEMORY.md` index 在 system prompt 內 inline(永遠看得到所有 memory 名稱);body 走 ranker。

## 讀取(ranker)

每輪對話開始:

```python
from orion_sdk.memory.ranker import select_relevant

memories = await scan_memory_dir(memory_paths)
top_n = await select_relevant(
    memories,
    recent_messages,
    mode="heuristic",      # bag-of-words(預設,0 LLM)
    # or "llm",            # 送 Haiku 評分
    top_n=5,
)
# inject 進 system prompt
```

`ORION_MEMORY_RANKER=llm` env 切 LLM ranker(每輪多打一次模型,較準但較貴)。

## Per-project memory

Project chat 走 `<workspace>/.orion/memory/`(workspace-local),自動 fall back 到 user-level。
Cowork 在 Project 內開的對話會看到兩份 memory 合併。

## 四層防膨脹

1. **Ranker 選 top-N**:預設 5 條,LLM 看不到全部
2. **`MEMORY.md` index 永遠在 system prompt**:LLM 知道有哪些 memory,需要時主動 read
3. **手動 cleanup**:Cowork Settings → Memory 可刪 / 改
4. **Compact 期間不動 memory**:對話壓縮跟 memory 是兩件事,memory 累積跟對話無關

## 設計取捨

- **Markdown file 不 DB**:user 可以直接 `vim ~/.orion/users/<id>/memory/foo.md` 改,git 也好 track。DB 反而難讀。
- **Heuristic ranker 預設**:bag-of-words 雖 dumb 但 zero-cost。100 條 memory 內準確度夠用。
- **`[[name]]` link**:memory body 可以 `[[other-memory-name]]` 引用其他 memory,scan 時 follow link 補進 context

## 限制 / 已知問題

- **Heuristic ranker 中文支援差**:bag-of-words tokenize 不切中文 — 中文 memory 可能漏選。Workaround:設 `ORION_MEMORY_RANKER=llm`。
- **No de-duplication**:LLM 寫多次同概念 memory 不會自動合併
- **MEMORY.md inject 上限**:目前沒 cap,1000 條 memory 會把 system prompt 撐爆

## 未來方向

- **Vector embedding ranker**:semantic similarity > bag-of-words,跨語言友善
- **Auto de-duplication**:寫入時相似度 check,合併而非新增
- **Memory edit history**:每次 edit 保留 diff,看演化
- **Cross-user memory**:team 共用 reference memory(目前只 per-user)

## 看完繼續

- [skills.md](./skills.md) — Skill 跟 memory 都 inject 進 system,差別?
- [`../architecture/runtime-layout.md`](../architecture/runtime-layout.md) — `~/.orion/users/` 目錄

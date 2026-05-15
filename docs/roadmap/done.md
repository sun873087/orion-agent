# Done

已完成的 phase 一句話總結。詳細內容看 git log。

## Phase 30 — Monorepo 重構(2026-05-15 ~ 2026-05-16)

把單一 `api/` package 拆成 uv workspace + npm workspaces 雙 monorepo:

- **30-A** `c052c20` — workspace root 起手
- **30-B** `137d846` — 拆 `orion-model`(純 LLM 抽象)
- **30-C** `5ccafc1` — 拆 `orion-sdk` + `orion-cli` + `orion-chat-api`(最大一刀)
- **30-D** `9752a9a` — `frontend/` → `apps/orion-chat/web/` + 型別契約 pipeline
- **30-E** `1776dc1` — 新建 Cowork(Electron + React + Python sidecar)
- **30-F** `60caf95` — Docker / Makefile / docs 收尾
- **30 follow-up** `07873e9` `c11bd18` — 刪 stale Makefile + tests 分散到對應 package

## Phase 29 — Auth user_id ↔ DB FK 對齊(2026-05-14)

`b35e25a` — JWT subject 改用 `users.id` UUID(不再用 username),所有 user-scoped FK 對齊。同步開 SQLite `PRAGMA foreign_keys=ON`。

## 主要 feature commits(Phase 0-28,粗時序)

- **Phase 0-2** — Foundation + Agent loop + Storage / Resume
- **Phase 3** — Memory + Compaction
- **Phase 4** — System prompt + Cache control
- **Phase 5** — MCP integration(4 transport)
- **Phase 6** — FastAPI + WebSocket
- **Phase 7** — Sandbox + Docker
- **Phase 8** — Hooks / Skills / Plugins
- **Phase 9** — Worktree + Telemetry
- **Phase 10** — Tools 補齊 + 性能
- **Phase 11** — Input pipeline(slash / image / token estimation)
- **Phase 12** — Internal mechanics(sideQuery / forkedAgent / Plan mode)
- **Phase 13** — Resilience(settings migrations / ConversationRecovery)
- **Phase 14** — Distribution & sync(secureStorage / settingsSync)
- **Phase 15** — Multi-agent(Coordinator + Swarm)
- **Phase 16** — Abort streaming mid-flight
- **Phase 18** — WebFetch cache
- **Phase 19** — File history GC
- **Phase 25** — Memory / MCP REST endpoints
- **Phase 27** — Memory anti-bloat Layer 1+2
- **Phase 28** — SQLite FK enforcement + cascade cleanup

詳細想看設計 → [`../features/`](../features/) 跟 [`../architecture/design-decisions.md`](../architecture/design-decisions.md)。
詳細想看 commit → `git log --oneline --grep="^feat\|^fix\|^refactor"`。

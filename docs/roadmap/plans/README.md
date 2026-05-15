# Plans

未實作的 phase plan。完工後從本目錄移除,在 [`../done.md`](../done.md) 加一行。

## 列表

| Plan | 內容 | 狀態 |
|---|---|---|
| [`31-phase30-followup/`](./31-phase30-followup/) | **Phase 30 follow-up** — Cowork ship-readiness(A-D)+ e2e infra(E, F)+ SDK polish(G, H)。3 條 track 可平行。6-8 週 | 📋 spec only |
| [`7c-helm-chart.md`](./7c-helm-chart.md) | K8s 部署 + Helm chart(取代 Phase 7 的 docker socket mount) | 📋 spec only |
| [`8c-plugin-marketplace.md`](./8c-plugin-marketplace.md) | Curated plugin registry + 簽名驗證 | 📋 spec only |
| [`9d-grafana-stack.md`](./9d-grafana-stack.md) | OTel → Grafana / Prometheus 觀測 stack | 📋 spec only |
| [`10c-stress-capacity.md`](./10c-stress-capacity.md) | 壓力測試 / capacity planning | 📋 spec only |
| [`11c-extra-slash-and-shell.md`](./11c-extra-slash-and-shell.md) | 補充 slash 命令 + shell 互動 | 📋 spec only |
| [`17-agenttool-concurrency-limit.md`](./17-agenttool-concurrency-limit.md) | sub-agent 並行上限控制 | 📋 spec only |
| [`20-transcript-compression.md`](./20-transcript-compression.md) | Transcript JSONL gzip / dedupe | 📋 spec only |
| [`21-git-github-workflow.md`](./21-git-github-workflow.md) | git / GitHub 整合工具 | 📋 spec only |
| [`22-dxt-plugin-format.md`](./22-dxt-plugin-format.md) | DXT plugin distribution format | 📋 spec only |
| [`24-multiagent-tools.md`](./24-multiagent-tools.md) | Multi-agent 進階工具 | 📋 spec only |
| [`26-projects.md`](./26-projects.md) | "Project" 概念(多 session 共用 context) | 📋 spec only |
| [`OPTIONAL.md`](./OPTIONAL.md) | 來自 Claude Code 的可選 features(IDE / MagicDocs / Notifier 等) | 📋 附錄 |

## 注意

這些 plan 大部分在 Phase 30 monorepo 重構**之前**撰寫,內含 `api/src/orion_agent/` 等舊路徑。要實作時:

1. 先讀 plan 拿設計意圖
2. 對照 `git log` 看是否有相關後續變動
3. import path / 目錄結構以**目前 `packages/orion-sdk/` 結構為準**,不要 follow plan 內舊路徑
4. 完工後 plan 從本目錄 `git rm`,在 `../done.md` 加一行

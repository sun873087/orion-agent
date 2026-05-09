# Phase 21:Git / GitHub Workflow Helpers + Slash Commands

## 速覽

- **預計時程**:1 週
- **前置 Phase**:Phase 13(基本 resilience 已就緒)
- **本文件目的**:從 `docs/phases/13-resilience.md` § 2.8 拆出來的獨立 phase。
  Phase 13 完工後沒做這部分(範圍超出「resilience」核心),升級為獨立 phase。
- **主要交付物**:
  - `utils/git/operations.py` — git status / diff / log / commit / push wrapper
  - `utils/github/auth.py` — gh CLI auth 狀態
  - `commands/builtin/commit.py` — `/commit` 命令(包 git commit + 對話內生成 commit message)
  - `commands/builtin/pr.py` — `/pr` 命令(用 gh CLI 開 PR)
  - `commands/builtin/review.py` — `/review` 命令(spawn coordinator,依賴 Phase 15 multi-agent)

## 為何另開 phase?

Phase 13 spec 把這個跟 migrations / recovery / persistence / instructions / output styles
塞同一個 phase。實際做下來:

1. git/github helpers 是「工具 + 命令」族群,跟 resilience(韌性)沒主題關聯
2. `/review` 命令依賴 Phase 15 multi-agent coordinator(Phase 13 還沒到那)
3. Phase 13 已經夠長,再多一塊會變成「30+ files 的 mega phase」

依使用者規範(completion 不寫 TODO,延後 / nice-to-have 升級為新 phase plan),把這
塊獨立成 Phase 21。

## TS 對應

- `src/utils/git/`(git 操作 helper)
- `src/utils/github/ghAuthStatus.ts`(gh CLI 連動)
- `src/commands/commit/`、`src/commands/pr/`、`src/commands/review/`

## 任務拆解

### Week 1:git / github helpers + 基礎命令

- [ ] 1.1 `utils/git/operations.py`:thin wrapper(git status / diff / log / commit /
       push / branch / current branch)。內部用 `asyncio.subprocess`(同 prompt/context.py
       的 `_run_git`),timeout 3s,失敗回 None / 空 list,不 raise
- [ ] 1.2 `utils/github/auth.py`:`gh auth status` 解析(connected / token scope / 帳號)
- [ ] 1.3 `utils/github/api.py`:必要時直接呼 GitHub REST API(用 `gh api` 而非 fetch
       to keep auth flow一致)
- [ ] 1.4 寫測試(mock subprocess / fake repo)

### Week 2:slash commands

- [ ] 2.1 `commands/builtin/commit.py`:`/commit [<extra-context>]` —
       讀 git status + git diff,丟 side_query(Phase 12)生 commit message,
       caller-confirm 後跑 `git commit`
- [ ] 2.2 `commands/builtin/pr.py`:`/pr [<title>]` — 解 git log 主題、跑 `gh pr create`
- [ ] 2.3 `commands/builtin/review.py`:**依賴 Phase 15** — spawn 多角度 review
       coordinator;Phase 15 完成前先做 stub(回 "Phase 15 required")
- [ ] 2.4 註冊到 `register_builtins()`
- [ ] 2.5 測試 + Phase 21 心得

## 設計決策(預設)

### git wrapper 用 subprocess 而非 GitPython
GitPython 額外依賴重;orion-agent 已有 prompt/context.py 走 subprocess 的範式,沿用一致。

### gh CLI 而非 PyGithub
gh 已是 user 安裝物(假設 dev 環境有);用 gh 走 user 自己的 token / config,
不需要再做 token 管理。SaaS 環境若沒 gh,/pr 命令直接回 `gh not installed` 即可。

### `/review` 暫緩
Phase 15 spec 明確要求 multi-agent coordinator,Phase 21 不重做;先放 stub。

## 依賴

- Phase 12 `services/side_query.py`(commit message 生成)
- Phase 15 multi-agent coordinator(review 用)

## 驗收標準

```bash
pytest tests/unit/utils/git/ tests/unit/utils/github/ \
       tests/unit/commands/builtin/test_commit.py \
       tests/unit/commands/builtin/test_pr.py -v

# 手動
/commit
/pr "fix: my change"
/review  # 期望 Phase 15 完成後才 functional
```

## 完成後寫

`orion-agent/docs/phase-21-completion.md`(zh-tw、含驗證指令、無 TODO)。

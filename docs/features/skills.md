# Skills

Skill = markdown bundle(`SKILL.md` + frontmatter + 附檔)。動態載入 prompt 內容調整 agent 行為,不寫 Python。

**實作位置**:`packages/orion-sdk/src/orion_sdk/skills/`

## Skill bundle 格式

```
~/.orion/skills/<name>/
├── SKILL.md         # 主檔(frontmatter + body)
├── examples/
└── ...
```

`SKILL.md` 範例:

```markdown
---
name: be-concise
description: Trim responses to one paragraph max
when_to_use: |
  Activate whenever the user explicitly asks for short replies,
  or in chat threads where a concise answer suits the context.
cowork_visible: true
---

You are responding in concise mode. Limit replies to ≤200 words.
...
```

### Frontmatter 欄位

| 欄位 | 必填 | 用途 |
|---|---|---|
| `name` | ✓ | Skill 識別名(LLM 透過 `Skill(skill_name='X')` 載入) |
| `description` | ✓ | 一句話 — LLM 看這句決定何時呼 / popover 顯示 |
| `when_to_use` |  | 觸發提示(進階版 description) |
| `parameters` |  | JSON Schema — skill 接受的 args 結構 |
| `hooks` |  | 同 settings.json hooks 格式 |
| `effort` |  | `low` / `medium` / `high`(reasoning model 用) |
| `model` |  | 強制這 skill 用某個 model |
| `cowork_visible` |  | **預設 `true`**;設 `false` 表此 skill 是 CLI / web 專用,**Cowork 桌面 UI 兩處(slash popover + Settings → 技能)隱藏,LLM 仍可透過名字載**。CLI / chat-api host 忽略此欄,一視同仁。 |

### `cowork_visible: false` 何時用

當 skill 內容跟 Cowork 桌面場景不 fit:

- **CLI 重度工作流** — 譬如 `batch`(5-30 個 worktree 平行開 PR),桌面 chat 沒這環境
- **指向 CLI / chat-api 專屬路徑** — 譬如 `update-config` 寫 `~/.orion/settings.json`,跟 Cowork GUI Settings 重疊;Cowork 自己用 `cowork_prefs` 表存偏好不走這檔

list 隱藏不影響 LLM 能力 — 對話內若有人問起,LLM 仍可 `Skill(skill_name='batch')` 載入(但這時 user 已明確要求,不會卡到他)。

## 內建 skill(`bundled`)

`packages/orion-sdk/src/orion_sdk/skills/bundled/` 預裝 10 個(Phase 31-G 為止):

| Skill | 用途 | `cowork_visible` |
|---|---|---|
| `be-concise` | 強制簡潔回應 | true |
| `debug` | 看 session log / transcript 診斷 | true |
| `loop` | 解析 `/loop <interval> <prompt>` → 算 cron + 呼 `LoopCreate`(Cowork)或 `CronCreate`(CLI) | true |
| `remember` | 整理 user memory layer(auto-memory / instructions) | true |
| `review-diff` | code review diff | true |
| `simplify` | 改動 code 簡化 + 修問題 | true |
| `skillify` | 把**當前對話**包成 SKILL.md(capture-only,4 問) | true |
| `stuck` | 診斷凍 / 卡 / 慢 agent session | true |
| `batch` | 5-30 個 worktree agent 平行 PR | **false** |
| `update-config` | 改 `~/.orion/settings.json` | **false** |

跟著 `pip install` ship。`~/.orion/skills/` 同名會覆蓋 bundled。
`cowork_visible: false` 的兩個在 Cowork popover 跟 Settings 隱藏 — 見上方說明。

## 載入 4 層

1. `bundled` — 套件附
2. `~/.orion/skills/` — admin 級
3. `<cwd>/.orion/skills/` — per-project
4. `~/.orion/users/<uid>/skills/` — per-user

後者覆蓋前者(`skills/loader.py:resolve_skills`)。

## Skill 怎麼被用

兩條路徑:

1. **被動載入**:`SessionStart` hook 掃 skills,選 `auto: true` 的塞 system prompt
2. **主動呼叫**:LLM 用 `Skill` 工具(`tools/agent/skill_tool.py`)透過 name 載入

第二條路徑讓 LLM 自己決定何時用 skill。Skill body 進入 conversation,效果近似 user 又灌一段 prompt 給 agent。

## Web chat 場景

per-user skills 存 DB(未實作)— 目前只支援 file-based。Phase 8 / 14 規劃見 [`../roadmap/`](../roadmap/)。

## 設計取捨

- **Skill = pure markdown,不寫 code** — 安全(沒有任意執行)、可由 non-dev 撰寫
- **動態載入而非預先註冊** — 數量多時不影響啟動時間
- **跟 hooks / plugins 分離** — skills 改 prompt;hooks 改 flow;plugins 加 tools

## 限制

- 沒有 skill 版本管理(覆蓋就覆蓋)
- frontmatter `when_to_use` 是 hint 給 LLM,實際選用 LLM 決定
- 大 skill body(>10KB)會吃 token

## 相關

- [hooks.md](./hooks.md) — 不同層擴充機制
- [plugins.md](./plugins.md) — 寫 code 的擴充
- [`../architecture/runtime-layout.md`](../architecture/runtime-layout.md) — skills 的 4 層位置

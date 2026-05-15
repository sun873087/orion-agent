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
---

You are responding in concise mode. Limit replies to ≤200 words.
...
```

## 內建 skill(`bundled`)

`packages/orion-sdk/src/orion_sdk/skills/bundled/` 預裝 10 個:

- `be-concise` — 強制短回應
- `simplify` — 程式簡化
- `loop` — 自循環 prompt
- `review` / `security-review`
- `init` — 新專案啟動
- `claude-api` / `claude-code-guide`
- `fewer-permission-prompts`
- ... (詳見資料夾)

跟著 `pip install` ship。`~/.orion/skills/` 同名會覆蓋 bundled。

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

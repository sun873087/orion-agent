# Skills

Skill = markdown bundle(`SKILL.md` + frontmatter + 附檔)。動態載入 prompt 內容調整
agent 行為,**不寫 Python**。

**實作位置**:`packages/orion-sdk/src/orion_sdk/skills/`

## Skill 長什麼樣

```
~/.orion/skills/git-workflow/
├── SKILL.md                  ← 主檔(LLM 看到的 prompt)
├── conventional-commits.md   ← 引用檔(SKILL.md 內 `@conventional-commits.md`)
└── templates/
    └── pr-body.md
```

`SKILL.md` frontmatter:

```markdown
---
name: git-workflow
description: 寫 git commit / open PR / push 的 workflow
metadata:
  type: workflow
  trigger_keywords: ["commit", "PR", "push", "git"]
  cowork_visible: true
---

When user wants to commit / push / open PR:

1. Show `git status` first
2. Use **HEREDOC** for commit body(Co-Author trailer:Claude...)
3. Never `--no-verify` unless explicitly asked
...

See @conventional-commits.md for commit style rules.
```

## 兩層位置

```
~/.orion/skills/                ← system skills(全 host 共用,跨 user)
~/.orion/users/<u>/skills/      ← per-user skills(個人專屬)
```

System skill 通常是 orion-agent bundle(`git-workflow` / `file-reading` / ...);per-user 是 user 自寫。

## 載入時機

- **Manual**:LLM 透過 `Skill` tool 主動 load — tool description 帶 skill 索引
- **Trigger keyword**:user message 含 `trigger_keywords` 就自動 load(opt-in per skill)
- **Cowork popover**:UI 按鈕 toggle on/off 整批 skill

載入後內容 inject 進 system prompt(session-stable cache 段)。

## 跨 host 共用

`~/.orion/skills/` 不分 host(CLI / Cowork / chat-api 都看同一份)。寫一次三家都能用。

## `cowork_visible: false`

Skill 內含 CLI-only 場景(`batch` / `update-config` 之類)在 Cowork popover + Settings UI 隱藏,但 LLM 仍可 load。

## 設計取捨

- **Markdown 不 Python**:user 寫 prompt 而非寫 code,門檻低。要 code-level extensibility 走 [plugins](./plugins.md)。
- **`@<file>` 引用**:大 skill 拆檔,SKILL.md 只放 entry,其他用 `@` 引用 — 載入時遞迴 follow。
- **Trigger keyword 是 opt-in**:預設要 LLM 主動 load,避免 keyword 太鬆把無關 skill 都拉進來。

## 限制 / 已知問題

- **Trigger keyword 沒 weighting**:命中就 load,可能誤觸發
- **跨 host 共用 = 衝突風險**:user 改 skill 影響全部 host
- **Skill content 不 sandbox**:malicious skill 可以指示 LLM 做事(LLM 信 system prompt > user msg)— skill 來源信任很重要

## 未來方向

- **Skill marketplace / registry**:從 npm / GitHub 一鍵安裝 popular skill
- **Skill version + autoupdate**:加 `version: 1.2.0` 跟 update check
- **Skill diff review**:user 安裝前看 skill 對 agent 行為的影響預覽

## 看完繼續

- [memory.md](./memory.md) — skill 跟 memory 都 inject system,差別?(skill 靜態 / memory 個人事實)
- [tools.md](./tools.md) — Skill tool

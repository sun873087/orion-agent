# Bundled Skills

這個資料夾是 **orion-agent 套件附的 skill** — 跟著 `pip install` / `uv install` 一起安裝,
所有 user / tenant 預設都看得到。

## 慣例

每個 skill 一個子資料夾,內含 `SKILL.md`(必)+ 可選附加檔案(model 用 Read 拿)。

```
bundled/
└── <skill-name>/
    ├── SKILL.md         ← frontmatter + body
    └── examples/...     ← 可選附件
```

`SKILL.md` 的 YAML frontmatter:

```yaml
---
name: skill-name           # 預設用資料夾名
description: 一句話說明
parameters:                # 可選 — JSON Schema for skill arguments
  type: object
  properties:
    foo:
      type: string
  required: [foo]
hooks: []                  # 可選 — 同 settings.json hooks 格式
effort: medium             # 可選 — low / medium / high(reasoning model 用)
model: claude-opus-4-7     # 可選 — 強制這個 skill 用某個 model
---

# Body 開始(送給模型的 prompt 主體)
```

## 目前內建的 10 個 skill

| 名稱 | 描述 |
|---|---|
| `be-concise` | 強制簡潔回應,不要前言 / 摘要 |
| `review-diff` | 程式碼 diff 審查(bugs / style / tests / security) |
| `simplify` | 看 `git diff`,launch 3 個並行 agent 審 reuse / quality / efficiency,然後動手修 |
| `stuck` | 診斷 frozen / slow agent process(`ps`, child processes, stack dump) |
| `batch` | 大改造拆 5-30 個 worktree agent 並行,各自開 PR |
| `loop` | 解析 `[interval] <prompt>` → CronCreate 排定週期執行 |
| `remember` | 走過 CLAUDE.md / CLAUDE.local.md / auto-memory,提出 promote / cleanup 提案(不直接寫) |
| `skillify` | 把當前 session 流程封裝成新 SKILL.md(走 AskUserQuestion 訪談) |
| `debug` | 讀 `~/.orion/sessions/<sid>/transcript.jsonl` 找錯誤 / warning,加 settings 路徑提示 |
| `update-config` | 改 settings 時挑對 layer + 用對 write path(Config 工具 / `/me/settings` REST) |

從上游 [Claude Code 17 個 bundled skills](https://github.com/anthropics/claude-code) 移植 8 個(原有 2 個共 10)。
**沒移植的 7 個**:`keybindings`(Claude Code TUI 鍵盤)、`claude-api` + `claude-api-content`
(247KB 多語言 SDK 文件 bundle)、`claude-in-chrome`(Chrome 擴充)、`schedule-remote-agents`
(MCP connector 依賴)、`verify` + `verify-content`(ANT-only + SKILL_FILES)、`lorem-ipsum`
(282 行 word list 資料)。

> **完整目錄結構**(不只 skills,還有 settings / mcp.json / plugins / instructions / sessions / uploads / memory):見 `orion-agent/docs/PROJECT_LAYOUT.md`。

## 五層 Skill 來源(`load_all_skills` 順序,**後者覆蓋前者**)

```
1. bundled            ← 你現在看的這個資料夾(套件內)
2. system             ← ~/.orion/skills/(env: ORION_SKILLS_DIR)
3. project            ← <cwd>/.orion/skills/(CLI 模式 only)
4. user               ← ~/.orion/users/<user_id>/skills/(env: ORION_USER_SKILLS_DIR)
5. extra_dirs         ← caller / plugin 在 runtime 傳進來的清單(下方解釋)
```

**Last-wins** = 最後 load 的覆蓋同名。所以如果你想覆寫 bundled 的 `simplify`,
在 `~/.orion/skills/simplify/SKILL.md` 寫一份新的 — 它會贏。

### 三個常見場景的選擇

| 你想要的效果 | 放哪 |
|---|---|
| 改全 server 預設(admin / 部署者)| `~/.orion/skills/<name>/SKILL.md`(系統級) |
| 跟著專案走(repo 內共用)| `<repo>/.orion/skills/<name>/SKILL.md`(commit 進 git) |
| 自己用,不影響其他人 | `~/.orion/users/<user_id>/skills/<name>/SKILL.md`(per-tenant) |
| 第三方 plugin 帶 skill 進來 | 透過 `extra_dirs`(plugin runtime 注入) |

## 什麼是 `extra_dirs`?

**runtime 傳進來的額外目錄清單**,給 caller / plugin 動態注入用。簽名:

```python
load_all_skills(
    extra_dirs: list[Path] | None = None,    # ← 你問的這個
    user_id: str | None = None,
) -> list[Skill]
```

兩個典型用途:

### 1. Plugin 帶 skill

Phase 8 plugin 機制:第三方寫 plugin,內含一個 skills 目錄。Plugin loader
load 完 plugin manifest,把 plugin 的 skill dir append 到 `extra_dirs`,
這樣 plugin 提供的 skill 自動被 SkillTool 看到。

```python
# 假想 plugin 啟動 hook
plugin_skills_dirs = [p.skills_dir for p in active_plugins if p.skills_dir]
skills = load_all_skills(extra_dirs=plugin_skills_dirs, user_id=ctx.user_id)
```

### 2. 測試 / 一次性 override

不想動 env var、不想改 `~/.orion/`,但想跑 test 或暫時注一個 skill:

```python
# 例如 unit test
tmp = tmp_path / "test_skills"
(tmp / "fake_skill").mkdir(parents=True)
(tmp / "fake_skill" / "SKILL.md").write_text("---\nname: fake\n---\nhi")
skills = load_all_skills(extra_dirs=[tmp])  # tmp 比 user dir 還優先
```

### 為什麼要 last-wins?

最後 load 贏 → **越客製、越優先**。bundled 只是 baseline;system 給 admin
override;user 給 tenant override;plugin / test 給最 dynamic 的 caller override。
這跟上游 Claude Code 的 `loadSkillsDir.ts` 同思路。

## 加新 skill 給自己用

```bash
# 自己用(per-tenant)
mkdir -p ~/.orion/users/<your_user_id>/skills/my-skill
cat > ~/.orion/users/<your_user_id>/skills/my-skill/SKILL.md <<'EOF'
---
name: my-skill
description: 短說明
---

# 主體 prompt 內容...
EOF
```

下一次 `Skill / skill_name=my-skill` 就會載入。自動掃到不需重啟,
但 web chat / WS chat 一條 conversation 已建好的 Conversation 不會即時 hot-reload
(下個 turn / 新 session 才會看到)。

## 不要在 bundled/ 改

這資料夾跟 git 走、跟 release 走,user 改了 `git pull` 會被覆蓋。
要客製請用 system / user / project layer。

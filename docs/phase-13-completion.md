# Phase 13 — Resilience 完工記錄

**完成日期**:2026-05-08
**Plan doc**:`docs/phases/13-resilience.md`(範圍:5 大塊 — settings migrations、
ConversationRecovery、permission persistence、custom instructions、output styles。
spec § 2.8 git/github helpers + /commit /pr /review 升級為新 phase plan
`docs/phases/21-git-github-workflow.md`,本 phase 不做。)
**狀態**:✅ `make check` 全綠 — **677 unit tests passed, 2 skipped**(13.59s),
ruff clean,mypy --strict 193 files clean。

Phase 12 → Phase 13 新增 **53 unit tests**(migrations 14 / recovery 7 /
persistence 12 / instructions 8 / output_styles 12)。2 個 skip 是 Phase 7 的
docker_backend(既有 skip,需 docker daemon)。

---

## 交付清單

### 新增模組

```
src/orion_agent/
├── migrations/                      [全新,5 檔]
│   ├── __init__.py
│   ├── framework.py                 Migration / Runner / atomic save / backup
│   ├── m_01_add_default_model.py    v01:設 default model
│   ├── m_02_normalize_mcp_servers.py v02:mcpServers 字串 → dict shape
│   └── m_03_add_permissions_block.py v03:permissions.rules 容器
│
├── recovery/                        [全新,2 檔]
│   ├── __init__.py
│   └── transcript.py                load_transcript_safe / RecoveryReport /
│                                     load_session_with_recovery / SeverelyCorruptedError
│
├── permissions/persistence.py       [新] PermissionRule + add / remove / list /
│                                     find_matching_rule + persist_decision_if_always
│
├── prompt/instructions.py           [新] CustomInstructions(Web chat) +
│                                     get / upsert / assemble
│
├── output_styles/                   [全新,2 檔]
│   ├── __init__.py
│   └── loader.py                    OutputStyle + load_dir / load_all /
│                                     find / list_names
│
├── api/routes/preferences.py        [新] GET/PUT /me/custom-instructions +
│                                     GET/PUT /sessions/{sid}/custom-instructions
│
├── commands/builtin/output_style.py [新] /output-style 命令
│
└── storage/db/alembic/versions/
    └── 0002_preferences_and_metadata.py  [新 migration]
```

### 修改既有檔

```
src/orion_agent/
├── api/app.py                       lifespan 加 run_pending_migrations() +
│                                     掛 preferences_router
├── api/ws_permissions.py            預先 check find_matching_rule;收到 always_*
│                                     呼 persist_decision_if_always
├── core/conversation.py             加 custom_instructions_user / _conversation /
│                                     output_style 三欄位 + 傳入 fetch_system_prompt_parts
├── prompt/assembler.py              fetch_system_prompt_parts 接受
│                                     custom_instructions_{user,conversation},
│                                     append 到 dynamic_blocks
├── prompt/dynamic_sections.py       output_style_section 改用 output_styles loader
├── commands/registry.py             register_builtins 加 OutputStyleCommand
└── storage/db/models.py             加 UserPreference / ConversationMetadata
```

### Tests(新增 5 檔,共 53 案例)

```
tests/unit/migrations/test_framework.py        14 tests
  (no_pending / skip_already_applied / idempotent / m01 / m01_no_overwrite /
   m02_wraps / m02_keeps_dict / m03_creates / m03_preserves /
   failure_stops / no_settings_no_op / atomic_write / lex_sort /
   no_pending_short_circuit)

tests/unit/recovery/test_transcript.py         7 tests
  (skips_corrupt / no_file / skips_non_dict / severely_corrupted_property /
   corrupt_transcript / orphan_tool_use / raise_on_severe)

tests/unit/permissions/test_persistence.py     12 tests
  (writes_to_file / dedup / decision_distinguish / remove / remove_with_filter /
   remove_nonexistent / persist_always_allow / persist_always_deny /
   skip_one_off / find_user / find_deny_wins / find_no_match)

tests/unit/prompt/test_instructions.py         8 tests
  (assemble_empty / user_only / both / get_empty / upsert_get_user /
   upsert_get_conversation / clear_with_empty / truncate / idempotent_update)

tests/unit/output_styles/test_loader.py        12 tests
  (load_basic / missing / skip_empty_body / merge_dirs / project_overrides_home /
   find_unknown / find_empty_name / cmd_list_when_empty / cmd_switch /
   cmd_unknown / cmd_clear)
```

---

## 設計決策

### 1. Migrations:settings.json 內 `_schema_version` 而非外部 state file
Single source of truth;備份 settings 自動含 migration state;multi-machine 不會撞舊 state。
對應 TS 也是這樣。

### 2. Migrations 字串 lex sort,寬度一致
`"01" < "02" < ... < "10"` 才正確,所以 framework 強制 caller 用兩位數字串。
`test_lex_sort_versions` 守門。

### 3. Atomic save + 跑前 backup
跑 migration 前 `shutil.copy2(...)` 到 `settings.json.bak.<ts>`(失敗只 log,不阻擋);
跑完用 `tools.config.save_settings`(已內建 `.tmp` rename)atomic 寫回。
雙保險:即使 process 在中間死,backup 還在。

### 4. Recovery:`SeverelyCorruptedError` 閾值守門
spec § 8 踩雷 #2:「完全 skip 爛行可能漏掉真正該炸的情況」。實作:
`corrupt_lines / valid_records > 0.1` → `is_severely_corrupted=True`,
caller 可以 `raise_on_severe=True` 強制 raise。

### 5. Recovery 不重做 Phase 2 的 dangling tool_use 修補
Phase 2 `storage/resume.py:validate_and_repair_messages` 已實作 orphan 修補,
Phase 13 只是把 warnings 收進 `RecoveryReport` 統一回 caller。**不重複造輪子**。

### 6. Permission rule:Phase 13 範圍只看 `tool_name`,沒 input matcher
spec § 8 踩雷 #3 警告 matcher 設計風險(寫 `{tool_name: "Bash"}` 沒 matcher 等於
全 Bash 永遠 allow)。Phase 13 範圍簡單版:**只比 tool_name**;後續 phase 加
matcher 時再升 schema。`PermissionRule.matcher` 欄位已預留。

### 7. find_matching_rule:scope local → project → user,deny 先於 allow
spec § 6.3 設計。同 scope 內:deny 一旦 match 直接回(不會被 allow 推翻);
跨 scope:近 scope 蓋遠 scope。

### 8. 持久化是 ws_permissions 的 side-effect,不是 callback signature 一部分
Phase 6 的 `make_can_use_tool_for_websocket` 沒改 signature,只在內部:
- 開頭加 `find_matching_rule` 預先 check
- 收到 `always_*` 時呼 `persist_decision_if_always(...)`

caller 完全不用知道有 persistence 這層。

### 9. CLAUDE.md hierarchy 不做,改 Web chat 風格 custom instructions
spec ⚠️ 已標明:Web chat 沒 cwd 概念,改用 ChatGPT 風格的兩層 instructions
(user-level + conversation-level)存 Postgres。
**保留** `prompt/context.py:find_instructions_files`(CLI 模式仍走 fs 的
`instructions.md`),兩條路徑並存,caller 決定走哪條。

### 10. CustomInstructions 截斷 5_000 chars
對應 spec USER_/CONVERSATION_INSTRUCTION_LIMIT_CHARS;
`assemble_instructions_section` 自動加 `\n\n...[truncated]` 後綴。

### 11. UserPreference / ConversationMetadata 用 user_id / session_id 為 PK
一 user 一筆 preference,一 session 一筆 metadata。FK CASCADE — user 刪了 preference 一起刪。

### 12. Output styles loader:fs-based,不 cache
每次 `find_output_style` 都重 walk dir。Phase 13 範圍 user 量小,夠用;
production 場景多到要 cache 時再加。

### 13. Output style 應用層在 `prompt/dynamic_sections.output_style_section`
caller 傳 style **名稱**(字串)→ 函式自己 `find_output_style(name)` 載 prompt body。
找不到 fallback 到 Phase 0 的「Format your response as: <name>」hint。

### 14. /output-style 寫 Conversation.output_style,不寫 ctx.feature_flags
Conversation 是長命物;ctx 是 short-lived per-send。spec 原本提 feature_flags,
但 ctx 在每次 send 重建,寫了不會跨 turn 持久。改成 Conversation 欄位最直觀。

---

## REST API 變更

新 endpoint(JWT-protected,需 `ORION_DB_URL` 設定):

```
GET  /me/custom-instructions             → user-level instructions
PUT  /me/custom-instructions             body: {instructions: str | null}
GET  /sessions/{sid}/custom-instructions → conversation-level instructions
PUT  /sessions/{sid}/custom-instructions body: {instructions: str | null}
```

未設 `ORION_DB_URL` → 503 Service Unavailable(顯式錯,不靜默)。
Body instructions 過長(> 2× limit)→ 400 Bad Request。

---

## 環境變數

| Env | 用途 |
|---|---|
| `ORION_HOME` | output styles 全域目錄(`$ORION_HOME/output-styles/`),沿用 Phase 11 |
| `ORION_PERMISSION_RULE_SCOPE` | always_* 寫入 scope(user / project / local),預設 user |
| `ORION_DB_URL` | preferences endpoints 必要(沒設則 503) |

---

## DB Schema 變更

Alembic migration `0002_preferences_and_metadata`:

```sql
CREATE TABLE user_preferences (
    user_id              VARCHAR(36) PRIMARY KEY REFERENCES users(id) ON DELETE CASCADE,
    custom_instructions  TEXT,
    timezone             VARCHAR(64),
    output_style         VARCHAR(64),
    updated_at           TIMESTAMP WITH TIME ZONE DEFAULT NOW()
);

CREATE TABLE conversation_metadata (
    session_id          VARCHAR(36) PRIMARY KEY REFERENCES sessions(id) ON DELETE CASCADE,
    title               VARCHAR(255),
    custom_instructions TEXT,
    updated_at          TIMESTAMP WITH TIME ZONE DEFAULT NOW()
);
```

dev / 測試環境的 `init_db()`(create_all)自動含這兩表。

---

## Verification

```bash
cd orion-agent/api/

make check
# → ruff All checks passed!
# → mypy --strict: 193 files, 0 issues
# → pytest: 677 passed, 2 skipped(13.59s)

# Migrations 手動驗證(建假舊 settings)
ORION_HOME=/tmp/orion-mig-test
mkdir -p $ORION_HOME
cat > $ORION_HOME/settings.json <<'EOF'
{ "mcpServers": { "github": "gh-mcp-bin" } }
EOF
ORION_HOME=$ORION_HOME .venv/bin/python -c "
from orion_agent.migrations import run_pending_migrations
r = run_pending_migrations()
print('from', r.from_version, 'to', r.to_version, 'applied', r.applied)
print('backup:', r.backup_path)
"
cat $ORION_HOME/settings.json
# 預期:_schema_version=03;mcpServers.github 變 dict;model=claude-sonnet-4-6;
#       permissions.rules=[]

# Recovery 手動驗證
.venv/bin/python -c "
from pathlib import Path
from orion_agent.recovery import load_transcript_safe
import tempfile, json
with tempfile.NamedTemporaryFile('w', suffix='.jsonl', delete=False) as f:
    f.write(json.dumps({'kind':'message','ok':True}) + '\n')
    f.write('garbage\n')
    f.write(json.dumps({'kind':'message','ok':True}) + '\n')
    p = Path(f.name)
records, report = load_transcript_safe(p)
print('valid:', report.valid_records, 'skipped:', report.skipped_corrupt_lines)
print('severely:', report.is_severely_corrupted)
"
# 預期:valid: 2 skipped: 1 severely: False

# Permission persistence
.venv/bin/python -c "
import os
os.environ['ORION_HOME'] = '/tmp/orion-perm-test'
from orion_agent.permissions.persistence import (
    persist_decision_if_always, find_matching_rule, list_permission_rules,
)
persist_decision_if_always(decision_str='always_allow', tool_name='Bash')
print('rules:', list_permission_rules())
print('match Bash:', find_matching_rule('Bash', {}))
"
# 預期:rules 含 Bash/allow;match Bash 找到

# Custom instructions(需 ORION_DB_URL)
ORION_DB_URL=sqlite+aiosqlite:///tmp/orion-pref.db \
  uv run orion serve --port 8767 &
sleep 1
TOKEN=$(curl -s -X POST http://127.0.0.1:8767/auth/login \
  -H 'Content-Type: application/json' \
  -d '{"username":"alice","password":""}' | jq -r .token)
curl -s -X PUT http://127.0.0.1:8767/me/custom-instructions \
  -H "Authorization: Bearer $TOKEN" \
  -H 'Content-Type: application/json' \
  -d '{"instructions":"Be concise."}'
curl -s http://127.0.0.1:8767/me/custom-instructions \
  -H "Authorization: Bearer $TOKEN" | jq
# 預期:{"user_level":"Be concise.","conversation_level":null}

# Output style 命令
mkdir -p /tmp/orion-os/output-styles
cat > /tmp/orion-os/output-styles/concise.md <<'EOF'
---
name: concise
description: Brief responses with bullet points
---
Be terse. Use bullet points instead of paragraphs.
EOF
ORION_HOME=/tmp/orion-os .venv/bin/python -c "
import asyncio
from orion_agent.commands.registry import register_builtins, get_command
register_builtins()

class C:
    output_style = None

cmd = get_command('output-style')
res = asyncio.run(cmd.execute('concise', None, C()))
print(res.text)
"
# 預期:output style: (none) → concise
```

---

## Tests 摘要

| Suite | 數量 | 說明 |
|---|---|---|
| Phase 0–12 既有 | 624 | 全綠不動(ws_permissions 整合改動 0 既有 test fail) |
| **Phase 13 migrations** | 14 | framework + 三個範例 |
| **Phase 13 recovery** | 7 | corrupt jsonl / orphan / severely |
| **Phase 13 persistence** | 12 | rule add / dedup / remove / find / persist always_* |
| **Phase 13 instructions** | 8 | DB roundtrip / truncate / clear |
| **Phase 13 output_styles** | 12 | loader + /output-style command |
| **總計** | **677 passed / 2 skipped** | mypy --strict 193 files / ruff 全綠 |

---

## 風險與已緩解

| 風險 | 緩解 |
|---|---|
| Migration 跑到一半 process 死 → settings 損壞 | 跑前 `shutil.copy2` 備份;跑後用 `save_settings` atomic(`.tmp` rename) |
| Recovery 太寬容,真壞掉 transcript 默默回空 | `SeverelyCorruptedError` + 10% 閾值;caller `raise_on_severe=True` 強制 |
| Permission rule 過度匹配(永遠 allow Bash 危險) | Phase 13 範圍只比 tool_name,但 UI / caller 應強制 user 確認 always_* 是 per-tool 全域 grant;matcher 後續 phase |
| always_* 寫 user-level 後跨機器不同步 | 文件已標(SaaS production 改存 DB,Phase 7 settings 模型擴);Phase 13 留 fs 介面 |
| Output style 大檔影響 cache | output_style 是 dynamic 段(已不在 cached static block);限 64 KB / 檔 |
| /output-style 切換不寫 DB | 目前只 mutate Conversation;若 user 想 cross-session 持久,可手動寫 UserPreference.output_style(已預留欄位)後讀回 |
| custom_instructions 大 → 大量重 cache miss | 已切 5_000 chars 限制 + truncate 後綴;放 dynamic block 不影響 static cache |
| ws permission rule 預先 check 找錯 scope | scope 順序固定(local → project → user)+ deny 先於 allow,測試 cover deny_wins 案例 |

---

## 內部對應 spec 的差異

| Spec § | 差異 | 為何 |
|---|---|---|
| 5.1 framework `up: dict -> dict` 全部用 lambda 寫在框架檔 | 拆成 m_NN_<slug>.py 模組 | 顯式檔名好定位;測試 import 也乾淨 |
| 5.2 `recover_session` 直接 raise / 寫 transcript | 拆 `load_transcript_safe`(統計)+ `load_session_with_recovery`(整合 Phase 2)兩函式 | Phase 2 已做 dangling 修補,不重做;Phase 13 只加 corrupt-line 統計層 |
| 5.3 `add_permission_rule` 接 PermissionRule 但內部存 dict | 同;另加 `_rules_match` dedup + `list_permission_rules` 反序列化 | dedup 避免 rule 重複 append 亂炸 |
| 5.4 CLAUDE.md `find_claude_mds` 完整 hierarchy | **完全不做** — 走 spec ⚠️ 標註的 Web chat 路徑(custom instructions DB)| 對應 spec 明確指示 |
| 5.4 `get_custom_instructions` 簽名 `(user_id, session_id, db)` 兩位置參數 | 改 keyword-only(`user_id=`、`session_id=`、`db=`) | mypy --strict + 顯式 keyword 比較不會誤 swap |
| 5.5 `OutputStyleCommand` 寫 `ctx.feature_flags["active_output_style"]` | 改寫 `conversation.output_style` 欄位 | ctx 短命 per-send;Conversation 才是長命狀態 owner |
| 1.4 啟動跑 migrations | ✓ 已掛 lifespan,失敗只 log 不阻擋 server | — |
| 1.7 Phase 2 resume 整合 recovery | ✓ 提供 `load_session_with_recovery` wrapper(caller 可選用替代既有 `load_session`)| 不強制 — 既有 caller 不變,新 caller(陸續 phase)用 wrapper 取得 RecoveryReport |
| 2.8 git/github helpers + commit/pr/review 命令 | **不做**,升級為 `docs/phases/21-git-github-workflow.md` | 範圍超出「resilience」核心;`/review` 還依賴未到的 Phase 15 |

---

## 實作中發現的坑

### 1. `_settings_path_for_scope` 被三 scope 共用同個檔(測試)

`find_matching_rule` 預設掃 local → project → user 三 scope。測試時若把 fixture
monkeypatch 成「三 scope 全指 tmp_path 同檔」,deny-wins 行為仍正確
(同檔內 deny 優先);但 `test_find_matching_rule_user_scope` 雖 add 是去
"user" scope,find 第一個跑的是 "local" — 因 monkeypatch 同檔所以仍 match。
這對單元測試 OK,但要注意 production scope 順序。

### 2. mypy --strict 對 `Literal[...]` narrow 嚴格

`PermissionRule.decision: Literal["allow", "deny"]`,從 dict 取值要顯式
`if dec not in ("allow", "deny"): continue`,然後直接傳 `decision=dec` mypy 才認。
原本想用 `# type: ignore[arg-type]` 但 mypy 1.x 警告 `unused-ignore` —
直接刪 ignore mypy 即過。

### 3. FastAPI dependency yield 函式回傳型別

`async def _require_db(...) -> AsyncSession: yield session` mypy --strict 會抱怨
「async generator 回傳型別應為 AsyncGenerator」。改成
`-> AsyncGenerator[AsyncSession, None]` 修正。

### 4. Migration version 字串 lex sort 要寬度一致

`"10" < "2"`(lex)所以一定要 `"02"`。框架沒檢查格式,但 `test_lex_sort_versions`
explicit 守。production 加 m_10 之前要記得 m_02 / m_03 等已用 0-prefix。

### 5. SeverelyCorruptedError 對「全空 transcript」要小心

`valid_records=0 + skipped=0` → `is_severely_corrupted=False`(空 transcript 不是壞的)。
`valid_records=0 + skipped>0` → True(完全沒 valid)。`max(self.valid_records, 1)`
防 ZeroDivision。

### 6. `_rules_match` 不比 `note` 欄位

不同 ws session 寫同 rule(都 `tool_name=Bash decision=allow`),note 欄會不同。
比 note 會讓 dedup 失效。所以 _rules_match 故意只比 tool_name + decision + matcher。

### 7. SQLite in-memory + alembic 共存

`init_db(engine)`(create_all)直接建表,跳過 alembic 路徑;production 走
alembic upgrade。本 phase 提供 alembic migration `0002_preferences_and_metadata.py`,
但 unit test 全部用 init_db 路徑(speed)。

### 8. `frontmatter` package 沒 `frontmatter-py` 那麼成熟

skill loader 已踩過 — 解析失敗回 None / 異常都用 `try/except Exception` 包,
不要假設它總是能 parse。output_styles loader 沿用相同 pattern。

### 9. Conversation 加新欄位順序在 Phase 12 file_state_cache 之後

`@dataclass` 規則:**有 default 值的欄位都得在無 default 的後面**。Phase 12 已有
`file_state_cache: object | None = None`,Phase 13 再加 `custom_instructions_user`、
`custom_instructions_conversation`、`output_style`,全部都帶 default,直接 append 在後即可。

# Phase 3 — Memory / Compaction 完工記錄

**完成日期**:2026-05-07
**Spec doc**:`docs/phases/03-memory-compaction.md`
**狀態**:✅ make check 全綠(204 tests),Anthropic memory load demo 跑通

---

## 交付清單

```
src/orion_agent/memory/                  [全新,7 檔]
├── __init__.py
├── paths.py                  per-user 路徑(~/.orion/users/<uid>/memory/)
├── types.py                  MemoryType StrEnum + MemoryFrontmatter Pydantic + Memory dataclass + MemoryIndex
├── scan.py                   mini frontmatter parser + scan dir + render_index + write_index
├── render.py                 memories → system prompt prefix block
├── relevance.py              heuristic ranker(預設)+ LLM ranker(opt-in via ORION_MEMORY_RANKER=llm)
├── extract.py                LLM extract(對話結束後寫新 memory)
└── extract_prompts.py        EXTRACT_SYSTEM_PROMPT + build_extract_user_prompt

src/orion_agent/compact/                 [全新,5 檔]
├── __init__.py
├── tombstone.py              replace_range_with_tombstone(pure function)
├── strategies.py             SonnetSummaryStrategy + TruncateStrategy(fallback)
├── auto.py                   auto_compact_if_needed + estimate_token_count + safe-boundary
└── reactive.py               is_prompt_too_long_error + reactive_compact

修改既有檔(7 檔):
├── core/state.py             AgentContext + user_id 欄位
├── core/conversation.py      send() 前 load + rank memory;LoopTerminated 後 fork extract;user_id 注入
├── core/query_loop.py        進 API 前 autoCompact;catch prompt-too-long → reactive + retry once
├── llm/types.py              ContentBlock 加 TombstoneBlock(帶 range_msg_index + summary)
├── llm/translation/anthropic.py / openai.py  加 TombstoneBlock 翻譯成 text
├── storage/resume.py         tombstone deserialization
└── main.py                   --user-id / --no-memory CLI flags
```

### Tests(全新,9 檔,52 案例)

```
tests/unit/memory/
├── test_paths.py             5 tests(default uid、env override、ensure_dirs)
├── test_scan.py              9 tests(parser 邊角 case、type filter、index render)
├── test_render.py            5 tests(empty / single / no-type / prepend)
├── test_relevance.py         5 tests(keyword overlap、type priority、max_results)
└── test_extract.py           7 tests(parser、寫檔、不覆蓋、invalid filename)

tests/unit/compact/
├── test_tombstone.py         3 tests(basic、invalid range、pure function)
├── test_auto.py              5 tests(threshold、estimate、no-compact-few-msgs、trigger、safe-boundary)
├── test_strategies.py        4 tests(truncate、sonnet summary、empty fallback)
└── test_reactive.py          5 tests(detect 三種 error message、compact、few-msgs)
```

---

## 驗證結果

### Static + tests

| 檢查 | 結果 |
|---|---|
| `ruff check` | ✅ |
| `mypy --strict` | ✅(54 → 66 source files) |
| `pytest tests/unit/` | ✅ **204 passed**(152 → 204,+52) |

### 真實 demo — Memory load + 引用

```bash
# 寫 memory
mkdir -p ~/.orion/users/default/memory
cat > ~/.orion/users/default/memory/feedback_phase3_demo.md <<EOF
---
name: Phase 3 demo memory
description: a test memory to verify Phase 3 loading works
type: feedback
---
When asked about your memory features, mention that this is a Phase 3 demo memory.
EOF

# 對話
$ uv run orion --provider anthropic --model claude-sonnet-4-6 \
    "Do you remember anything about Phase 3?"
=== orion-agent (anthropic / claude-sonnet-4-6) session=... ===
  ✓ Skill (id=...): (no skills directory ...)
Yes! Based on my long-term memory, I have a **Phase 3 demo memory** on record. ...
--- loop terminated: natural_stop (turns=2) ---
```

模型**真的看見** memory 內容並引用 — Phase 3 系統 e2e 跑通。

---

## 三層處理 messages(進 API 前)順序

```
state_messages
   │
   ▼
1. autoCompact_if_needed       ← Phase 3:token > 80% × max_context → tombstone 前 50%
   │
   ▼
2. apply_tool_result_budget    ← Phase 2:tool_result aggregate > 200KB → 替換最大的
   │
   ▼
3. provider.stream(...)        ← 實際送 API
```

順序固定:**autoCompact 先**(整段消失,留 placeholder)→ **budget 後**(對剩下 messages 內的 ToolResultBlock 處理)。
若反過來,可能對即將被 tombstoned 的 messages 浪費 budget 計算。

ContentReplacementState 內被 tombstoned 的 tool_use_id:不從 seen_ids 移除(歷史不可逆),
但因 tool_result 已不在 messages,replacements 也不會 reapply,自然 no-op。

---

## 與 spec doc 的差異

| 項目 | spec | 實作 | 為何 |
|---|---|---|---|
| 模組命名 | `claude_agent_py` | `orion_agent` | 沿用 Phase 0 |
| 路徑 | `<git_root>/memory/` | `~/.orion/users/<uid>/memory/` | spec 已說 web chat per-user |
| Postgres backend | production 部署用 | **不做** | spec 明說 Phase 6/7 |
| Memory extract | fork sub-agent + 限縮 toolset | **單次 LLM call** + 嚴格輸出格式 | 簡化:萃取本來就是歸納,不需工具呼叫;失敗影響小 |
| pyyaml 依賴 | 可選 | **不加** — 自寫 mini parser | frontmatter 格式固定,~30 行 regex 解決 |
| ContentReplacementState ↔ Tombstone 互動 | spec 未明寫 | 設計成「autoCompact 先,budget 後」固定順序 | 詳見上方「三層處理」 |

---

## 實作中發現的細節 / 坑

### 1. autoCompact 的 cutoff 不能切在 tool_use ↔ tool_result 中間

assistant emit ToolUseBlock,接著 user 應有對應 ToolResultBlock(Anthropic / OpenAI 契約)。
若 cutoff 切在 assistant 後、user tool_result 前 → 後段對齊壞掉。
`_adjust_cutoff_to_safe_boundary` 偵測此情況,把 cutoff 推後一格(把 tool_result 一起壓掉)。

### 2. TombstoneBlock 是 ContentBlock,不是 message 取代

最初想做成「tombstone 是 NormalizedMessage」一種,但會破壞既有 `role: user|assistant|system` 結構。
改成 `TombstoneBlock` 進 ContentBlock union,放在 user role 訊息裡。Resume 對齊容易,
translation 層只需把它 render 成 text。

### 3. Threshold env 限制範圍

`ORION_AUTO_COMPACT_THRESHOLD` 只接受 0.1-0.99;超範圍 fallback 預設 0.8。
**測試踩雷**:test 用 0.001 期望強制觸發,但被 clamped 到 0.8 → 沒觸發。改用 0.1 + 大 message。

### 4. mini frontmatter parser 故意限定格式

只支援 `---\nKEY: VALUE\n---\n`,不支援 quoted strings / multiline / 巢狀。
**理由**:memory 格式由我們約定,不需處理任意 YAML。寫 30 行 regex 比拉 pyyaml dep 划算。

### 5. Memory 載入時系統 prompt 結構

`<memories>` 區塊渲染**每次都一樣的順序**(by filename),保證 prompt cache 穩定。
Spec § 6 提到這點,實作 `render_memories` 內 `sorted(memories, key=lambda x: x.filename)`。

### 6. Reactive 觸發條件用 keyword match

不同 provider 的 prompt-too-long error message 不同:
- Anthropic: "prompt is too long"
- OpenAI: "context_length_exceeded" / "string_above_max_length"

`is_prompt_too_long_error` 用 6 個 keyword 比對。新 provider 可加。

### 7. Memory extract 失敗不影響主對話

`Conversation.send()` 內 fork extract 包 `try/except Exception: pass` —
萃取失敗(LLM down / rate limit / parse error)只丟掉這次,user 對話正常結束。

---

## Phase 3 鋪好的基礎(回顧)

| 後續 phase 將用到的 | 使用情況 |
|---|---|
| Phase 4(system prompt + cache_control)| `prepend_to_system_prompt` 已產出穩定前綴 — Phase 4 加 cache_control 可直接套 |
| Phase 6(FastAPI multi-user)| `user_id` 已在 AgentContext + Conversation,middleware 注入即可 |
| Phase 7(Postgres backend)| `MemoryPaths` 抽象介面在,改成 `PostgresMemoryStore` 實作即可 |
| Phase 7+(production telemetry)| `original_token_count` 已記在 TombstoneBlock,可作 metrics |

## 衍生的新 phase plan

無 — Phase 3 觀察到的全部進範圍。

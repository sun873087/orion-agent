# Phase 4 — System Prompt + Cache Control 完工記錄

**完成日期**:2026-05-07
**Spec doc**:`docs/phases/04-system-prompt.md`
**狀態**:✅ make check 全綠(234 tests),Anthropic dynamic-env demo 跑通

---

## 交付清單

```
src/orion_agent/prompt/                  [全新,7 檔]
├── __init__.py
├── sections.py                  module-level dict cache(register_section / DANGEROUS_uncached)
├── static_sections.py           7 段靜態 prompt(intro / system_behavior / doing_tasks / actions / tools / tone_style / output_efficiency)
├── context.py                   get_git_context / get_env_info / find_instructions_files(`~/.orion/instructions.md` + `<cwd>/.orion/instructions.md`)
├── dynamic_sections.py          5 段動態 builder(env_info / instructions / memory / language / output_style / session_guidance)
├── boundary.py                  SYSTEM_PROMPT_DYNAMIC_BOUNDARY + split_at_boundary
└── assembler.py                 fetch_system_prompt_parts(並行)+ build_system_prompt_list(回 list[str])

修改既有檔(3 檔):
├── core/conversation.py         send() 改用 fetch_parts + build_list 取代 prepend_to_system_prompt
├── core/query_loop.py           QueryParams.system_prompt 型別 str → str | list[str]
└── main.py                      移除 SYSTEM_PROMPT 寫死;Conversation(system_prompt="") 走 assembler
```

### Tests(全新,6 檔,28 案例)

```
tests/unit/prompt/
├── test_sections.py             5 tests(cache hit / miss / DANGEROUS_uncached / clear)
├── test_static_sections.py      4 tests(7 段順序、render 包所有段、deterministic)
├── test_context.py              7 tests(env_info、git 失敗靜默、instructions global+cwd 雙路徑、UTF-8 fail skip)
├── test_boundary.py             4 tests(三條路徑 + 邊界)
└── test_assembler.py            8 tests(parts、cache 共用、cwd 變化、build list、use_cache=False、instructions.md 整合)
```

---

## 驗證結果

### Static + tests

| 檢查 | 結果 |
|---|---|
| `ruff check` | ✅ |
| `mypy --strict` | ✅(67 → 73 source files) |
| `pytest tests/unit/` | ✅ **234 passed**(206 → 234,+28) |

### 真實 demo

```bash
$ uv run orion --provider anthropic --model claude-sonnet-4-6 \
    --no-persistence --no-memory "What's my current working directory?"
=== orion-agent (anthropic / claude-sonnet-4-6) session=... ===
Your current working directory is `/Users/yuan-sencheng/Desktop/claude-code-source-main/orion-agent/api`.
--- loop terminated: natural_stop (turns=1) ---
=== done — turns=1, tools=0(0 errors), in=330, out=34 ===
```

模型直接從 dynamic env_info 段拿到 cwd,**不需要呼叫任何工具**。
`in=330` 表示 system prompt 簡潔(7 段靜態 + env block)。

---

## System prompt 結構(Phase 4 後)

```
[provider.stream(system=...)]
  ↓
list[str] (2 elements)
  ├─ [0] 靜態合併(享 cache)
  │       ├─ intro
  │       ├─ system_behavior
  │       ├─ doing_tasks
  │       ├─ actions
  │       ├─ tools
  │       ├─ tone_style
  │       └─ output_efficiency
  └─ [1] 動態合併(每 turn 重算)
          ├─ Environment(platform / cwd / date / git status)
          ├─ User instructions(若 ~/.orion + cwd/.orion 有)
          ├─ Memories(Phase 3 ranker 挑選後)
          ├─ Language hint(若指定)
          ├─ Output style(若指定)
          └─ Session guidance(若指定)
```

**Anthropic provider** 把 `cache_control: ephemeral` 標在「倒數第二段」結尾(`_build_system_param`,cache_idx = max(0, len-2))→ 涵蓋穩定 prefix 即靜態段。⚠ Phase 4 完工時實作有誤(誤標在 list[-1]),2026-05-10 修正,見文末「勘誤」。
**OpenAI provider** 自動 `\n\n.join(list)` 成單字串(Phase 0 既有實作),自動 cache > 1024 tokens 的 prefix。

兩家 provider 都不需要本 phase 改動 — Phase 0 抽象設計已預留。

---

## 與 spec doc 的差異

| 項目 | spec | 實作 | 為何 |
|---|---|---|---|
| 模組命名 | `claude_agent_py.prompt` | `orion_agent.prompt` | 沿用 Phase 0 |
| `services/anthropic_client.py` 擴充 | 加 `build_system_prompt_blocks` | **不改** | Phase 0 的 `LLMProvider.stream(system: str | list[str])` 已支援 cache scope,直接用 |
| CLAUDE.md auto-discovery | 多層上溯 | 改成 `~/.orion/instructions.md` + `<cwd>/.orion/instructions.md`(2 層) | orion-agent 慣例 + 簡化 |
| MCP instructions section | 預留 | 不做 | spec 說 Phase 5 |
| 4 cache breakpoint 全用 | spec 提示 | **只用 1 個**(切靜態 / 動態) | YAGNI;tool definitions 之類後續可擴 |

---

## 實作中發現的細節 / 坑

### 1. LLMProvider.stream 已支援 list[str] system

Phase 0 抽象設計時就考慮了這層 — 不需要為 Phase 4 再改 provider。
`AnthropicProvider`:list 模式在「倒數第二段」加 cache_control(2026-05-10 修正前誤標在最後一段,見「勘誤」)。
`OpenAIProvider`:list 模式 `"\n\n".join(...)` 成單字串(Phase 0)。
**Phase 4 只在 Conversation 層產 list,provider 層不動** — 抽象有效隔離。

### 2. Conversation.system_prompt 變 optional

舊:`system_prompt: str`(必填)。
新:`system_prompt: str = ""`(可省)。
- 留空 → assembler 路徑(Phase 4)
- 給字串 → caller 客製,完整覆蓋(向後兼容)

`tools` 也順手從必填改成 `default_factory=list`(子 agent 場景常無 tool)。

### 3. Memory 整合方式變化

Phase 3:`prepend_to_system_prompt(SYSTEM_PROMPT, memories)`(直接 prepend,fixed string)
Phase 4:`memory_section()` 是 `dynamic_sections` 之一,assembler 並行蒐集。
對 user 行為一致,但結構從 ad-hoc 拼接變成 first-class section。

`prepend_to_system_prompt` 函式仍保留(`memory/render.py`)— 沒人用但不刪,因為簡單測試友善。

### 4. Section cache 跨 conversation 共用 OK

Module-level dict + 靜態段 deterministic(`render_static_block()` 不取任何 mutable state)
→ 跨 conversation / 跨 user 共用 cached value 不會出錯。

未來若靜態段內含 user 特定資訊(預期不會),要改成 cache_key 帶 user_id。

### 5. 子進程 git 失敗的多種模式

寫 `get_git_context` 時要處理 3 種失敗:
- `FileNotFoundError`(git 沒裝)
- subprocess 退出 != 0(不在 repo)
- 卡住(rare,但 timeout 防它)

全 try/except + `anyio.move_on_after(3.0)`,失敗回空字串。**spec 有提這點**。

### 6. instructions.md 限大小(100KB)

避免 user 寫太大的 instructions 爆 token。**Phase 1 FileReadTool 用同樣 256KB 上限**;
Phase 4 的 instructions 限更嚴(100KB),因為要全文進 prompt 不能截斷。

### 7. mock Path.home() 寫測試的細節

`monkeypatch.setattr("orion_agent.prompt.context.Path.home", lambda: fake_home)`
而非 `monkeypatch.setenv("HOME", ...)` — 因為 Path.home() 在 macOS 用 `pwd` getpwuid 而非 HOME。

---

## Phase 4 鋪好的基礎(回顧)

| 後續 phase 將用到 | 使用情況 |
|---|---|
| Phase 5(MCP)| `dynamic_sections` 加 `mcp_instructions_section()` 即可 |
| Phase 6(FastAPI)| `fetch_system_prompt_parts(language=req.lang, ...)` per-request 注入 |
| Phase 7(production)| `section_cache` 跨 worker 共用(若 in-process)/ Redis 化(若需要) |
| Phase 8(hooks)| frontmatter / hook section 可加進 `dynamic_sections` |

## 衍生的新 phase plan

無 — Phase 4 觀察到的全部進範圍。

---

## 勘誤(2026-05-10)

**症狀**:Phase 4 設計上要把 `cache_control: ephemeral` 標在 `list[:-1]`(即靜態段結尾),
讓穩定 prefix 享 cache、動態段在 breakpoint 之後不影響 cache 比對。

**實際代碼**(`anthropic_provider.py` 至 2026-05-10 前):
```python
if i == len(system) - 1:           # ← 標在 list[-1](dynamic 段)
    block["cache_control"] = {"type": "ephemeral"}
```

**後果**:cache key 涵蓋整個 system(static + dynamic),
dynamic 每 turn 變 → cache key 每 turn 變 → **靜態段 cache 完全沒生效**。

**為何沒被發現**:
- 沒有測試直接驗 cache_control 標記位置(`test_forked_agent.py` 只驗 system list 形狀)
- Phase 4 完工驗證指標(`in=330` tokens)是 prompt 大小,不是 cache hit rate
- doc 跟代碼 comment 都寫「最後一段」(comment 配合代碼一起寫成的),自我一致沒人察覺
- 跨 phase 引用時(Phase 5 / 13)只看「能不能用」,沒回頭驗 cache 行為

**修正**:
1. 抽出 `_build_system_param()` 純函式,`cache_idx = max(0, len(system) - 2)`
2. 新增 `tests/unit/llm/test_anthropic_provider.py`(5 case 直接驗標記位置)
3. 同步修 `test_forked_agent.py:58` 的過時 comment
4. doc 對應段落(§ System prompt 結構、§ 實作中發現的細節 1)同步更新

**教訓**:設計意圖、代碼、doc、comment 四者必須**互相證偽**,不能只是互相引用。
未來凡涉及 cache scope 的代碼,測試 MUST 直接斷言「cache_control 在哪個 block 上」。

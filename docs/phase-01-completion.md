# Phase 1 — Agent Loop 完工記錄

**完成日期**:2026-05-07
**Spec doc**:`/Users/yuan-sencheng/Desktop/claude-code-source-main/docs/phases/01-agent-loop.md`
**狀態**:✅ make check 全綠 + integration tests 兩家 provider 都通

---

## 交付清單

### 新增模組(28 檔 src + 16 檔 tests)

```
core/
├── transitions.py              [新] Continue / Terminal dataclass
├── tool_execution.py           [新] run_one_tool — 單工具流程(find/parse/preHook/perm/call/postHook)
├── tool_orchestration.py       [新] partition_tool_calls + run_tools(批次模式)+ run_tools_concurrently
├── query_loop.py               [新] query_loop async generator + QueryParams + LoopEvent union
├── conversation.py             [新] Conversation 跨 turn wrapper + ConversationStats
└── streaming_executor.py       [新] StreamingToolExecutor(streaming 模式工具編排)

permissions/
├── __init__.py                 [新]
└── decisions.py                [新] PermissionDecision (StrEnum) + CanUseToolFn + always_allow / always_deny

hooks/
├── __init__.py                 [新]
├── events.py                   [新] PreToolUseEvent / PostToolUseEvent
└── registry.py                 [新] HookRegistry + dispatch / pre_tool_use / post_tool_use

tools/file/
├── write.py                    [新] FileWriteTool(整檔寫,要求父目錄存在)
└── edit.py                     [新] FileEditTool(string replace,unique 或 replace_all)

tools/shell/
└── bash.py                     [新] BashTool(asyncio subprocess + 30s timeout + abort_event 監看)

tools/search/
├── glob.py                     [新] GlobTool(pathlib glob,按 mtime 排序)
└── grep.py                     [新] GrepTool(優先 ripgrep,fallback Python re)

tools/web/
└── fetch.py                    [新] WebFetchTool(httpx + bs4 strip HTML)

tools/agent/
├── agent_tool.py               [新] AgentTool(spawn 子 query_loop,深度限 1)
└── skill_tool.py               [新] SkillTool(讀 ~/.orion/skills/*.md)

tools/todo/
└── todo_write.py               [新] TodoWriteTool(寫 ctx.todos in-memory)

main.py                         [改] 整支重寫成 Conversation + query_loop 入口,註冊全工具

core/state.py                   [改] AgentContext 加 todos / sub_agent_depth 欄位
pyproject.toml                  [改] 加 httpx + beautifulsoup4 deps
```

### Tests

```
tests/conftest.py                       [改] 加 MockProvider + MockTurn + load_dotenv
tests/unit/core/                        9 新檔
  ├── test_transitions.py
  ├── test_partition_tool_calls.py      hypothesis-based
  ├── test_query_loop_terminate.py
  ├── test_query_loop_multi_turn.py
  ├── test_conversation_state.py
  ├── test_run_tools_concurrent.py
  ├── test_streaming_executor.py
  ├── test_tool_execution.py
tests/unit/permissions/                 1 新檔
tests/unit/hooks/                       1 新檔
tests/unit/tools/                       8 新檔
  ├── test_file_write.py / test_file_edit.py
  ├── test_bash.py
  ├── test_glob.py / test_grep.py
  ├── test_web_fetch.py
  ├── test_agent_tool.py / test_skill_tool.py / test_todo_write.py
tests/integration/                      2 新檔
  ├── test_anthropic_loop.py            multi-turn,需 ANTHROPIC_API_KEY
  └── test_openai_loop.py               multi-turn,需 OPENAI_API_KEY
```

---

## 驗證結果

### 靜態檢查全綠

```bash
make check
```

| 檢查 | 結果 |
|---|---|
| `ruff check` | ✅ All checks passed |
| `mypy --strict` | ✅ Success: no issues found in 46 source files |
| `pytest tests/unit/` | ✅ **110 passed** in ~3s(81 新 + 29 Phase 0) |

### Integration tests 全綠

```bash
uv run pytest tests/integration/ -v
```

```
tests/integration/test_anthropic_loop.py::test_multi_turn_with_file_read PASSED
tests/integration/test_openai_loop.py::test_multi_turn_with_file_read    PASSED
```

兩家 provider 都跑通完整 multi-turn loop:
- 模型 call Read 工具
- 結果回填模型
- 模型摘要回覆 magic number
- Terminal natural_stop

### 手動 demo(真實 LLM)

#### Anthropic — 自我修正路徑錯誤,3 turn 完成複雜 task
```
> List the .py files in src/orion_agent/core/ then tell me what core/transitions.py defines
```

執行軌跡:
1. Turn 1: Bash `ls src/orion_agent/core/*.py`
2. Turn 2: Read `transitions.py`(第一次 path 錯,看到 file not found,重試對的 path)
3. Turn 3: 從 ls 結果 + transitions 內容組成 markdown 回覆

`--- loop terminated: natural_stop (turns=3) ---`、3 tool calls(1 error,被 model 自己看見並修正)。

#### OpenAI — 簡單 Bash + 回覆,2 turn
```
> Use the Bash tool to run 'echo hello' and tell me the output
```
2 turns、1 tool call、natural_stop。

---

## 與 spec doc 的差異

| 項目 | spec | 實作 | 為何 |
|---|---|---|---|
| Provider 注入 | 寫死 `AnthropicStreamingClient()` | `provider: LLMProvider` 由 QueryParams 傳入 | spec 寫於 LLMProvider 抽象前;Phase 0 後我們可同時跑 Claude+GPT |
| Message 型別 | 新建 `core/messages.py` 的 AssistantMessage / UserMessage / ... | **不建** — 復用 Phase 0 的 NormalizedMessage + ContentBlock | 少一層轉換,功能等價 |
| Streaming executor 啟用 | spec 說「Week 4 重構」,意指後段 | 已實作完整,但 query_loop 預設仍用 batch 模式;streaming 留作 Phase 1b 直接 swap | 重大架構改動延後;批次模式正確且測過 |
| Sibling abort | BashTool 觸發 → 中止並行兄弟 | 未實作 — Bash 有 abort_event 監看(主 abort)但無 sibling 觸發 | StreamingToolExecutor 集成完成後再加;Phase 1 主 loop 用 batch,沒有需要 sibling abort 的情境 |
| TodoWrite 持久化 | spec 沒提 | in-memory(存 ctx.todos) | Phase 2 才會有 storage |

---

## 實作中發現的細節 / 坑

### 1. Tool Protocol 不能用 `async def` 宣告 call

Phase 0 寫:
```python
class Tool(Protocol[Input_T]):
    async def call(self, ...) -> AsyncIterator[ToolEvent]: ...
```

mypy strict 會把 `async def f(): ...` 解讀為「coroutine function returning AsyncIterator」,即實作型別應是
`(...) -> Coroutine[Any, Any, AsyncIterator[T]]`。但實作是 `async def + yield`(async generator function),
型別是 `(...) -> AsyncGenerator[T, None]`,兩者不相容,83 個 union-attr 錯誤。

**解法**:Protocol 用 sync `def` 宣告:

```python
def call(self, ...) -> AsyncIterator[ToolEvent]: ...
```

實作仍是 `async def + yield`(call() 後得到 AsyncGenerator,subtype of AsyncIterator)。
**這是 Phase 0 的潛在 bug**,Phase 1 才浮出來(因為 Phase 0 main.py 沒透過 Tool[Any] list 抽象)。

### 2. Stop reason 不可信(Phase 0 已警告,Phase 1 確認)

Anthropic 模型 emit tool_use 時 `stop_reason="tool_use"`,OpenAI Responses API 同情境給 `stop_reason="end_turn"`。
**query_loop 終止判斷只看 ContentBlock 裡有無 ToolUseBlock**,不看 stop_reason。實測通過。

### 3. `uv pip install -e .` 會 reset 安裝

每次跑 `uv sync` 後 editable install 偶爾失效(只剩 dist-info,沒 source pth)。
**必跑 `uv pip install -e . --reinstall`** 修正,然後 `uv run orion` / `uv run pytest` 才會找到模組。
這是 Phase 0 已記下的坑,Phase 1 加 deps 時又踩到。

### 4. pytest skipif 不會自動讀 .env

`pytestmark = pytest.mark.skipif(not os.environ.get("ANTHROPIC_API_KEY"), ...)` 在 conftest.py 做 collect-time 判斷,
但 .env 還沒被載入。**conftest.py 頂端要 `load_dotenv()`**,且 `from orion_agent...` 必須加 `# noqa: E402`。

### 5. AgentContext 擴充策略

Phase 0 state.py 註解寫「後續 phase 加入: sandbox, permissions, hooks, plan_mode_state 等」。
Phase 1 加 `todos: list[dict[str, str]]` 和 `sub_agent_depth: int`。**新增欄位有預設值,沒打破既有 caller**。

### 6. AgentTool 的 child_tools 過濾

子 agent 不能再 spawn 子 agent(深度 > 1 禁止)— 用兩道防線:
- **建構期**:`AgentTool.__init__` 過濾掉 child_tools 中的 AgentTool(防 child_tools 內含)
- **執行期**:`AgentTool.call` 檢查 `ctx.sub_agent_depth >= 1` → ErrorEvent
兩道擋掉所有遞迴可能(直接遞迴、間接透過 deeper child_tools)。

### 7. BeautifulSoup find_all 回 NavigableString | Tag union

`soup.find_all(string=...)` 回的是 `NavigableString`(不是 Tag),mypy strict 會擋
混用 `for el in soup.find_all(...): el.decompose()`(因為 NavigableString 沒 decompose)。
**用兩個明確 isinstance Tag 檢查**,別寫 string=lambda 那條邏輯(空白 strip 已含於 get_text(strip=True))。

### 8. StrEnum vs Enum

`PermissionDecision(str, Enum)` 通過 mypy 但 ruff(UP)會建議用 Python 3.11+ 的 `StrEnum`。改用 `StrEnum` 即可。

---

## 留給下個 phase 的 TODO

### Phase 1b(可在 Phase 2 前順手做)

- [ ] StreamingToolExecutor 接到 query_loop 主路徑(目前只有 unit test 覆蓋)
- [ ] BashTool 觸發 sibling_abort,中止並行兄弟工具
- [ ] Conversation.stats 累積 input_tokens / output_tokens(目前都是 0)
- [ ] Glob fallback 對大目錄的記憶體控制(目前一次性 list)

### Phase 2 才該做

- [ ] 工具結果三層持久化(transcript / disk overflow)
- [ ] resume 機制
- [ ] tool_use_id ↔ tool_result 配對的持久化校驗

### 觀察到的後續優化機會

- query_loop 的 LoopEvent union 已經夠用,但 `final_messages` 隨 turn 滾雪球。Phase 3 compaction 會解決
- AgentTool 子 agent 共用 parent provider — 可加 max_concurrent_sub_agents limit(避免一次開太多 LLM 連線)
- WebFetchTool 沒 caching;同 URL 重複 fetch 浪費

---

## 數字總結

| 指標 | 值 |
|---|---|
| 新增源檔 | 28 |
| 新增測試檔 | 16 |
| 新增測試案例 | 81(總計 110) |
| Static check | ✅ 全綠 |
| Integration tests | ✅ 2/2 |
| 真實 demo | ✅ Anthropic 3-turn 自修正 / OpenAI 2-turn |
| 從 Phase 0 commit 到 Phase 1 完工 | ~80 分鐘(計畫估 4-5 小時 — 沒走偏的話 Claude 寫 code 很快) |

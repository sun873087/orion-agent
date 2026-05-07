# Phase 0 — Foundation 完工記錄

**完成日期**:2026-05-07
**Spec doc**:`/Users/yuan-sencheng/Desktop/claude-code-source-main/docs/phases/00-foundation.md`
**狀態**:✅ 全綠 + 兩家 provider 都實際跑通

---

## 交付清單

### 結構
```
orion-agent/
├── api/                          uv project
│   ├── pyproject.toml            anthropic + openai + pydantic + typer + python-dotenv
│   ├── Makefile                  install / test / typecheck / lint / format / check
│   ├── README.md
│   ├── .env.example              key 範本
│   ├── .gitignore                .env / .venv / __pycache__ / uv.lock
│   ├── .pre-commit-config.yaml
│   ├── src/orion_agent/
│   │   ├── __init__.py           __version__ = "0.1.0"
│   │   ├── main.py               typer CLI(--provider 切換)
│   │   ├── core/
│   │   │   ├── tool.py           Tool Protocol + ToolInput / TextEvent / ProgressEvent / ErrorEvent
│   │   │   └── state.py          AgentContext + TokenBudget(取代 TS 的 module-level state)
│   │   ├── llm/
│   │   │   ├── types.py          NormalizedMessage + 5 種 ContentBlock(discriminated union)
│   │   │   ├── events.py         7 種 NormalizedEvent + NormalizedUsage
│   │   │   ├── tool_def.py       ToolDefinition(送給模型看的版本)
│   │   │   ├── provider.py       LLMProvider Protocol + ProviderCapabilities + get_provider()
│   │   │   ├── anthropic_provider.py    呼 client.messages.stream()
│   │   │   ├── openai_provider.py       呼 client.responses.create(stream=True)
│   │   │   ├── pricing.py        per-provider per-model 計價表
│   │   │   └── translation/
│   │   │       ├── anthropic.py
│   │   │       └── openai.py     handles function_call / function_call_output items
│   │   ├── services/
│   │   │   └── feature_flags.py  ORION_FF_* 環境變數
│   │   └── tools/
│   │       └── file/read.py      FileReadTool(唯一示範工具)
│   └── tests/
│       ├── conftest.py
│       ├── unit/                 29 測試,CI 必跑
│       │   ├── test_tool_protocol.py        (3)
│       │   ├── test_agent_context.py        (5)
│       │   ├── llm/test_translation_anthropic.py  (7)
│       │   ├── llm/test_translation_openai.py     (7)
│       │   └── tools/test_file_read.py      (7)
│       └── integration/
│           └── README.md         需 API key,Phase 1+ 才會加實際測試
├── ui/test-ui.html               Phase 6 才會接 backend,目前只是介面樣板
└── docs/
    └── phase-00-completion.md    本文件
```

**檔案數**:33 檔(api/ + ui/ + docs/)

---

## 驗證結果

### 靜態檢查全綠

```bash
cd orion-agent/api/
make check
```

| 檢查 | 結果 |
|---|---|
| `ruff check` | ✅ All checks passed |
| `mypy --strict` | ✅ Success: no issues found in 21 source files |
| `pytest tests/unit/` | ✅ 29 passed in 0.24s |

### 兩家 provider 實際跑通

#### Anthropic(claude-sonnet-4-6)

```
=== orion-agent (anthropic / claude-sonnet-4-6) ===
[tool_use_start] Read (id=toolu_01UgGxcbjLStvffB4tMMBHwY)
[tool_use_stop]  input={'path': '/etc/hosts'}
[message_stop] reason=tool_use in=760 out=55 cache_read=0
--- executing tool locally ---
1	## # Host Database ...(/etc/hosts 內容)
```

#### OpenAI(gpt-4o-mini)

```
=== orion-agent (openai / gpt-4o-mini) ===
[tool_use_start] Read (id=call_jgw49QkUABvCj092Keiqnlko)
[tool_use_stop]  input={'path': '/etc/hosts', 'offset': 0, 'limit': 20}
[message_stop] reason=end_turn in=185 out=25 cache_read=0
--- executing tool locally ---
1	## # Host Database ...(/etc/hosts 內容)
```

**LLMProvider 抽象驗證成功** — 同一段 user code,不同 provider,normalized event 格式一致。

---

## 與 spec doc 的差異

Phase 0 spec(`docs/phases/00-foundation.md`)裡有但**未實作**的:

| 項目 | 為何延後 |
|---|---|
| 完整 multi-turn agent loop | 屬 Phase 1 範圍,Phase 0 只 demo 單 turn + 印 tool 結果 |
| Tool result 回填模型再請求 | 同上 |
| FastAPI / WebSocket | 屬 Phase 6 |
| Pre-commit hook 實際 install | 留 `.pre-commit-config.yaml`,user 自行 `pre-commit install` |
| Integration tests 實際 case | 只留 README,Phase 1+ 寫 |

---

## 實作中發現的細節 / 坑

### 1. mypy strict 對 SDK streaming events 的 union narrow 失敗

Anthropic SDK 把 streaming event 設計成 `RawMessageStartEvent | RawContentBlockStartEvent | ...` union,
但 mypy strict 無法用 string discriminator(`event.type == "message_start"`)narrow。
83 個 union-attr 錯誤直接灌爆。

**解法**:在 `anthropic_provider.py` / `openai_provider.py` 的 stream loop 裡把 raw event cast 成 `Any`:
```python
async for raw_event in stream:
    event: Any = raw_event   # 邊界視為 Any
    etype: str = event.type
    if etype == "message_start": ...
```

emit 出去的 NormalizedEvent 仍會被 strict 完整檢查,只在 SDK 邊界放寬。
**不要** `# mypy: disable-error-code` 整檔粗暴 disable。

### 2. OpenAI stop_reason 與 Anthropic 不同調

| Provider | model 想 call tool 時 |
|---|---|
| Anthropic | `stop_reason=tool_use`(明確要回填) |
| OpenAI Responses | `stop_reason=end_turn`(turn 完成,但 message 內含 function_call item) |

**Phase 1 query loop 不能只看 `stop_reason`,要看 message 裡有沒有 ToolUseBlock 來決定要不要回填**。
本文件留下這個警示給 Phase 1 實作者。

### 3. `uv pip install -e .` 偶爾只裝 dist-info 沒裝 source

跑 `uv sync` 後有時 `uv run orion` 報 ModuleNotFoundError。
`uv pip install -e . --reinstall` 修好。原因尚不明,**Phase 1 開始前**值得查一下,
可能是 hatchling 與 uv editable install 之間的 race。

### 4. `python-dotenv` 必須在 import provider 之前 load

`AnthropicProvider.__init__()` 用 `AsyncAnthropic()`(無參),client 在建構時讀 `os.environ["ANTHROPIC_API_KEY"]`。
所以 `load_dotenv()` 必須在所有 `from orion_agent.llm... import ...` **之前** 呼叫。
解法:`main.py` 用 `# noqa: E402` 抑制 ruff,把 import 排在 load_dotenv 之後。

### 5. `dict` / `list` 在 strict mypy 必須帶 generic argument

預設範例常寫 `data: dict` 或 `content: str | list`,strict mypy 會擋。
全部改成 `dict[str, Any]` / `list[TextBlock | ImageBlock]`。

### 6. TypedDict union 在 strict mypy 不能 `dict()`

`pricing.py` 原本用 `AnthropicModelPricing | OpenAIModelPricing` TypedDict union,
`dict(p)` 會失敗(`SupportsKeysAndGetItem` 不相容)。
**改用 plain `dict[str, dict[str, dict[str, float]]]`** — 簡單多了。

---

## Phase 0 鋪好的基礎(回顧 — 後續 phase 已陸續用上)

| 基礎 | 後續 phase 使用情況 |
|---|---|
| Tool Protocol(`core/tool.py`)| Phase 1 起所有工具實作之依據 |
| AgentContext + abort_event(`core/state.py`)| Phase 1 query_loop turn 邊界 abort + BashTool watch_abort 已用;**stream 中途即時 abort** 升級為獨立 phase plan(`docs/phases/16-abort-stream-mid-flight.md`)|
| LLMProvider 抽象(`llm/provider.py`)| Phase 1 / 2 query_loop 跨 Anthropic + OpenAI |
| NormalizedMessage / ContentBlock | Phase 1 / 2 復用,不另建 message hierarchy |
| FileReadTool 示範 | Phase 1 加了 8 個工具;Phase 2 加持久化 |
| Phase 0 spec 列「query loop / stop_reason / 平行 / 結果序列化」| 全部 Phase 1 / 2 完成 |
| 整合測試框架 `tests/integration/` | Phase 1 加 `test_anthropic_loop.py` + `test_openai_loop.py` |
| `uv pip install -e .` 不穩定根因(坑 #3)| Phase 2b 查出是 iCloud Drive Sync,Makefile + TROUBLESHOOTING.md 修 |

---

## 一個 Phase 0 之外的小發現

**寫到 .env 的 key 在 conversation log + 硬碟 .env 檔都有副本**。Phase 0 demo 用的兩支 key:
- Anthropic key:`sk-ant-api03-bxV0...`
- OpenAI key:`sk-proj-XapWO...`

兩支都該在 Phase 0 收尾後撤銷重建。**這提醒以後不要把 key 貼到聊天訊息裡** — 從 console 直接複製貼到 .env 就好。

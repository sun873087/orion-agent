# Phase 30-B:拆出 `orion-model`

## 速覽

- **預計時程**:1-2 天
- **前置 Phase**:30-A(uv workspace 已建立)
- **狀態**:📝 spec only,**未實作**
- **目標**:把 `api/src/orion_agent/llm/` 整個搬到 `packages/orion-model/src/orion_model/`,變成獨立 workspace package。`api/` 透過 dep 引用,不再直接持有 LLM 抽象層

## 1. 為何先拆這個

`llm/` 是**零反向依賴**的子系統(已用 `grep -rE "^from orion_agent\." api/src/orion_agent/llm/` 驗證 — 它只 import 自己內部的 module,沒有 import core / tools / 任何其他東西)。這代表搬出去後不會有循環依賴,是最安全的第一刀。

## 2. 任務拆解

- [ ] 建立 `packages/orion-model/` 目錄結構
- [ ] 寫 `packages/orion-model/pyproject.toml`(只列 anthropic + openai + httpx + pydantic 等 LLM 必須的 deps)
- [ ] `git mv api/src/orion_agent/llm/* packages/orion-model/src/orion_model/`
- [ ] `api/src/orion_agent/llm/__init__.py` 改成 re-export,避免一次性大改名(漸進遷移橋接層,**Phase C 結束時拆掉**)
- [ ] 或選 hard cut:全域 sed `orion_agent.llm` → `orion_model`(見 §4 取捨)
- [ ] root `pyproject.toml` 把 `packages/orion-model` 加入 `[tool.uv.workspace].members`
- [ ] `api/pyproject.toml` 加 `orion-model` 為 dep(workspace ref)
- [ ] `uv sync` 確認 editable install 通
- [ ] 跑 `pytest`(api 套件)確認既有測試還是綠的
- [ ] 寫 `packages/orion-model/tests/` 把跟 LLM 直接相關的測試搬過去(可選,B 階段可保留在 api/tests/)
- [ ] 加 import-linter contract:`orion_model` 不可 import `orion_agent`(單向依賴)

## 3. 檔案變更

### 3.1 新檔:`packages/orion-model/pyproject.toml`

```toml
[project]
name = "orion-model"
version = "0.1.0"
description = "LLM provider abstraction for Anthropic / OpenAI — normalized events, tool defs, pricing."
readme = "README.md"
requires-python = ">=3.11"
license = { text = "MIT" }
dependencies = [
    "anthropic>=0.40.0",
    "openai>=1.50.0",
    "pydantic>=2.0",
    "httpx>=0.27",
    "structlog>=24.0",     # 事件 logging 用,不掛大型 dep
]

[build-system]
requires = ["hatchling"]
build-backend = "hatchling.build"

[tool.hatch.build.targets.wheel]
packages = ["src/orion_model"]
```

### 3.2 新檔:`packages/orion-model/README.md`(極簡)

```markdown
# orion-model

LLM provider abstraction layer extracted from orion-agent.

- Anthropic + OpenAI providers,統一 `NormalizedMessage` / `NormalizedEvent` 介面
- Tool definition schema(`ToolDefinition`,跟 agent runtime 解耦)
- Pricing / cache config / model catalog(`models.json`)

不含 agent loop,適合單純做 prompt 測試 / benchmark / 純 LLM 呼叫場景。
```

### 3.3 搬移:`api/src/orion_agent/llm/` → `packages/orion-model/src/orion_model/`

用 `git mv` 保留歷史:

```bash
mkdir -p packages/orion-model/src
git mv api/src/orion_agent/llm packages/orion-model/src/orion_model
```

### 3.4 全域 import 改名

搬完後,所有 import path 從 `orion_agent.llm.*` 改成 `orion_model.*`。

```bash
# Dry run 先看影響範圍
grep -rl "orion_agent\.llm" api/src api/tests

# 確認後執行
grep -rl "orion_agent\.llm" api/src api/tests | \
  xargs sed -i '' 's/orion_agent\.llm/orion_model/g'
```

**手動檢查清單**(sed 不一定全 cover):
- `api/src/orion_agent/llm/__init__.py` — 若選漸進方案,改成 `from orion_model import *`
- 字串內的 dotted path(例如 `getattr(module, "orion_agent.llm.provider")`,grep -rE "['\"]orion_agent.llm" 找)
- TS / docs / markdown 內的 reference

### 3.5 修改:`api/pyproject.toml`

```diff
 dependencies = [
+    "orion-model",       # workspace dep,uv 會解析到 packages/orion-model
-    "anthropic>=0.40.0",
-    "openai>=1.50.0",
     ...
 ]

+[tool.uv.sources]
+orion-model = { workspace = true }
```

**注意**:`anthropic` / `openai` 雖然搬到 `orion-model`,但 `api/` 仍可能直接 import(若有的話)。先 grep:
```bash
grep -rE "^import (anthropic|openai)|^from (anthropic|openai)" api/src/orion_agent/ | \
  grep -v "/llm/"
```
若有,代表那些檔案破壞了「只透過 orion-model 用 LLM SDK」的設計,**這不該發生**,應該改用 `orion-model` 暴露的抽象介面。如果有違規,記下來但**不在 Phase B 修**(Phase C 一起整治)。

### 3.6 修改:root `pyproject.toml`

```diff
 [tool.uv.workspace]
-members = ["api"]
+members = ["api", "packages/orion-model"]
```

## 4. 取捨:漸進 re-export 橋接 vs 一次性 hard cut

| 方案 | 優 | 缺 |
|---|---|---|
| **漸進**:`orion_agent/llm/__init__.py` 改 `from orion_model import *`,讓既有 `from orion_agent.llm.X import Y` 還能用 | Phase B 改動最小;import path 改名押到 Phase C | 留一個橋接層短期內;import-linter 會抓到反向 dep,要 ignore |
| **Hard cut**:Phase B 就把所有 `orion_agent.llm` → `orion_model` | 一刀切乾淨,沒尾巴 | Phase B 動的檔案多,review 較大;若漏一個 import,測試會炸 |

**建議:Hard cut**。`llm/` import path 出現的地方 grep 一下其實不多(<30 個檔案),sed + manual review 一輪可以收掉。漸進方案的「橋接層」往往會留很久變成技術債。

## 5. import-linter contract

在 root 加 `.importlinter` 或 `pyproject.toml` 的 `[tool.importlinter]`:

```toml
[tool.importlinter]
root_packages = ["orion_model", "orion_agent"]

[[tool.importlinter.contracts]]
name = "orion-model is independent of orion-agent"
type = "forbidden"
source_modules = ["orion_model"]
forbidden_modules = ["orion_agent"]
```

CI 加一步 `lint-imports`。

## 6. 驗證

```bash
$ uv sync
Resolved N packages

$ uv run --package orion-agent python -c "from orion_model import get_provider; print(get_provider)"
<function get_provider at 0x...>

$ uv run --package orion-agent pytest -q
=========== N passed in X.XXs ===========

$ uv run lint-imports
Contracts: 1 kept, 0 broken.
```

## 7. 常見踩雷

| 症狀 | 原因 | 解法 |
|---|---|---|
| `ModuleNotFoundError: orion_agent.llm` 在某個被遺忘的檔案 | grep + sed 漏 | 把錯誤訊息那條 import 改名,跑下一次 pytest |
| `orion_model.translation.anthropic` import 不到 | 子 package 沒 `__init__.py` | 確認 `translation/__init__.py` 存在(原本就有,git mv 後應該還在) |
| `models.json` 找不到 | `importlib.resources` 路徑變了 | 改 `importlib.resources.files("orion_model")` 找 |
| ruff `I` (isort) 一直噴 | sed 改完 import 順序亂 | `uv run ruff check --fix` 一次性整理 |
| `orion-model` workspace dep 沒生效,還是去 PyPI 找 | 沒寫 `[tool.uv.sources]` workspace ref | 補上 §3.5 那段 |
| Postgres / sqlalchemy 之類也想連帶搬走 | 不該搬,它們是 storage 層的東西 | 只搬 `llm/` 下的東西,storage 留給 Phase C |

## 8. 完成後的狀態

```
orion-agent/
├── pyproject.toml              ← members 多一個 packages/orion-model
├── uv.lock
├── packages/
│   └── orion-model/            ★ 新
│       ├── pyproject.toml
│       ├── README.md
│       └── src/orion_model/    ← 原本 api/src/orion_agent/llm/ 整搬過來
│           ├── __init__.py
│           ├── provider.py
│           ├── anthropic_provider.py
│           ├── openai_provider.py
│           ├── catalog.py
│           ├── events.py
│           ├── pricing.py
│           ├── cache_config.py
│           ├── tool_def.py
│           ├── types.py
│           ├── models.json
│           └── translation/
│               ├── anthropic.py
│               └── openai.py
├── api/
│   ├── pyproject.toml          ← 改 dep 加 orion-model
│   └── src/orion_agent/
│       └── (沒有 llm/ 子目錄了)
└── ...
```

## 9. 下一步

Phase B 完成後,進 Phase C(最大一刀):拆 `orion-sdk` / `orion-cli` / `orion-chat/api`。

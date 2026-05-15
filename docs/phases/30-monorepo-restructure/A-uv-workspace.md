# Phase 30-A:uv workspace 起手

## 速覽

- **預計時程**:0.5 天
- **前置 Phase**:無
- **狀態**:📝 spec only,**未實作**
- **目標**:在 repo root 建立 uv workspace,把現有 `api/` 註冊為唯一 member,驗證 `uv sync` 跟 `uv run` 都跑得起來,**完全不動程式碼**

## 1. 為何先做這一步

把 workspace 機制先驗證通,後面 Phase B-F 加新 member 才有信心。這步幾乎零風險,但能提早發現:

- uv workspace 跟 hatchling build backend 的相容性
- editable install 在這個 repo 結構下能不能正常運作
- CI 需不需要調 `uv sync` 的 flags

## 2. 任務拆解

- [ ] 在 repo root 建立 `pyproject.toml`,只含 `[tool.uv.workspace]` 設定
- [ ] 把 `api/` 列為 workspace member
- [ ] `uv sync` 在 root 跑得通(產生 root 的 `uv.lock`)
- [ ] `uv run --package orion-agent pytest -q` 跑得通(等同 `cd api && pytest`)
- [ ] `uv run --package orion-agent orion --help` 印出 typer help
- [ ] 把原本 `api/uv.lock` 刪掉(改用 root 的)
- [ ] `.gitignore` 確認沒漏掉 `.venv/`(root 跟 api/ 共用 root `.venv`)
- [ ] 跑一次完整 `cd api && pytest` 確認既有測試還是綠的

## 3. 檔案變更

### 3.1 新檔:`/pyproject.toml`(repo root)

```toml
[tool.uv.workspace]
members = ["api"]

# Workspace root 沒有自己的程式碼,只當 workspace marker。
# 之後 Phase B 加 packages/orion-model,Phase C 加 packages/orion-sdk
# + apps/orion-cli + apps/orion-chat/api。
```

### 3.2 刪檔:`api/uv.lock`

uv workspace 用 root 的 lock file,member 不該有自己的 lock。

### 3.3 不動的檔

- `api/pyproject.toml` 完全不動(它本身就是 workspace member 的 manifest)
- `api/src/` 不動
- `api/tests/` 不動

## 4. 驗證

```bash
# 在 repo root
$ uv sync
Resolved 87 packages in 142ms
Audited 87 packages in 0.5ms

$ ls .venv/  # 確認有共用 venv
bin/  include/  lib/  ...

$ uv run --package orion-agent orion --help
Usage: orion [OPTIONS] COMMAND [ARGS]...
...

$ uv run --package orion-agent pytest -q
...
=========== N passed in X.XXs ===========
```

## 5. 常見踩雷

| 症狀 | 原因 | 解法 |
|---|---|---|
| `error: Workspace member declares non-workspace dependency` | `api/pyproject.toml` 寫 `orion-something>=X.Y`,但 X.Y 在 workspace 內找得到 | 之後 Phase B-C 才會碰到;Phase A 不該動到 deps |
| `hatchling: package not found` | root pyproject 沒設 `[build-system]` 但 hatchling 想找 | root pyproject 不需要 `[build-system]`(它不 build,只是 workspace marker)|
| `editable install fails` | hatchling 的 `[tool.hatch.build.targets.wheel].packages` 路徑相對位置變了 | 不會變 — Phase A 沒搬檔,`api/pyproject.toml` 裡的相對路徑仍對 |
| pytest 在 root 找不到測試 | pytest 預設從 cwd 找 testpaths | `uv run --package orion-agent pytest` 等同 `cd api && pytest`,不會有問題 |

## 6. 完成後的狀態

```
orion-agent/
├── pyproject.toml              ← 新:workspace root,3 行
├── uv.lock                     ← 新:統一 lock(從 api/uv.lock 升級而來)
├── .venv/                       ← root 共用 venv(uv 自動建)
├── api/                        ← workspace member,內部不變
│   ├── pyproject.toml          (不變)
│   ├── src/orion_agent/        (不變)
│   ├── tests/                  (不變)
│   ├── alembic.ini             (不變)
│   ├── Makefile                (可能需要小調,把 `cd api && X` 改 `uv run --package orion-agent X`)
│   └── orion.db                (不變)
├── deploy/                     (不變)
├── docs/                       (不變)
└── frontend/                   (不變)
```

## 7. 下一步

Phase A 跑通後可進 Phase B(拆 `orion-model`)。Phase B 加第二個 member 時,可以驗證 workspace cross-package import 的行為。

# Run tests

6 個 workspace member 各自有獨立 test suite。1100+ tests 全綠是基線。

## All at once

```bash
make test
# 跑 6 個 package 的 unit + (skip integration tests that need real API)
```

預期輸出大致:

```
=== orion-model        ===  77 passed
=== orion-sdk          === 741 passed (+2 skipped)
=== orion-cli          ===  68 passed
=== orion-chat-api     === 102 passed (+8 deselected)
=== orion-cowork-sidecar === 51 passed (+2 skipped)
=== orion-model-proxy  ===  75 passed
```

## Per package

```bash
make test-model        # orion-model
make test-sdk          # orion-sdk
make test-cli          # orion-cli
make test-chat-api     # orion-chat-api
make test-sidecar      # orion-cowork-sidecar
make test-proxy        # orion-model-proxy
```

或直接 uv:

```bash
uv run --directory packages/orion-model pytest -x -q
uv run --directory apps/orion-cowork/sidecar pytest -x -q
```

## TypeScript typecheck

```bash
cd apps/orion-cowork && pnpm typecheck
# 跑 renderer + electron 兩個 tsconfig
```

```bash
cd apps/orion-chat/web && pnpm typecheck
```

## E2E(需要 real API key)

```bash
# Cowork vision e2e — 預設 skip,有 key 才跑
OPENAI_API_KEY=sk-... ANTHROPIC_API_KEY=sk-ant-... \
  uv run --directory apps/orion-cowork/sidecar pytest tests/test_vision_e2e.py
```

```bash
# CLI integration
OPENAI_API_KEY=sk-... \
  uv run --directory apps/orion-cli pytest tests/integration/
```

## Pre-push

```bash
make lint typecheck test
```

## Debugging tests

```bash
# -s:不抓 stdout
# --pdb:fail 進 pdb
# -k:by name
uv run --directory packages/orion-model-proxy pytest -x -s --pdb -k "test_audit"
```

## 加新 test

```
packages/<pkg>/tests/
├── conftest.py                  shared fixture(如 tmp DB)
├── test_<feature>.py            module-level tests
└── integration/                 e2e tests(預設 skip 除非設 env)
```

慣例:
- 一 test 一個 assertion(可多個但聚焦)
- `pytest-asyncio` auto mode — `async def test_...` 直接寫
- Fixture 用 `pytest_asyncio.fixture` 給 async setup
- 避免共享 state(每 test 獨立 tmp dir / tmp DB)

## CI

GitHub Actions(`.github/workflows/`)在 PR / push 跑全部:lint + typecheck + test。
6 個 package 平行跑 matrix。

## 測試紀律

- 不 mock SDK 內部 LLM call,改 mock provider 介面層
- DB test 用 SQLite tmp(`tempfile.mkdtemp`),避免污染
- Integration test 用 env 守門(`@pytest.mark.skipif(not os.environ.get("OPENAI_API_KEY"))`),沒 key 自動 skip
- 失敗的 test **不要** disable / xfail 跳過 — 修 bug 或砍 test

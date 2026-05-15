# Run tests

5 個 package 各自有獨立 test suite。914 tests 全綠是基線。

## 一鍵跑全部

```bash
make test
```

平行跑:`make test` 內部是 5 個 `cd <pkg> && uv run pytest -q` 順序執行(總時間 ~60 秒)。

## 跑單個 package

```bash
make test-model       # orion-model (46 tests, ~1s)
make test-sdk         # orion-sdk (704 tests + 4 skip, ~45s)
make test-cli         # orion-cli (55 tests, ~1s)
make test-chat-api    # orion-chat-api (102 tests, ~30s)
make test-sidecar     # orion-cowork-sidecar (7 tests, ~3s)
```

## 跑單個檔案 / 函式

```bash
cd packages/orion-sdk
uv run pytest tests/unit/core/test_query_loop_multi_turn.py -v
uv run pytest tests/unit/core/test_query_loop_multi_turn.py::test_basic_send -v
uv run pytest -k "memory and not extract"  # 用 keyword filter
```

## 跑 integration tests(需要 API key)

預設 skip(`@pytest.mark.integration`):

```bash
cd packages/orion-sdk
uv run pytest -m integration tests/integration/
```

確認 `.env` 有 `ANTHROPIC_API_KEY` 或 `OPENAI_API_KEY`。會打真 API,有成本。

## E2e tests

**尚未實作**。設計骨架見:

- `apps/orion-chat/tests/e2e/README.md` — Server + WS + Auth 完整 stack
- `apps/orion-cowork/tests/e2e/README.md` — Headless Electron

兩個都需要先解決 CI 環境(Postgres testcontainer + xvfb)。

## Coverage

```bash
cd packages/orion-sdk
uv run pytest --cov=orion_sdk --cov-report=html
open htmlcov/index.html
```

## Lint / Typecheck

```bash
make lint        # uv run ruff check .
make typecheck   # uv run mypy packages apps
```

## Test fixture 機制

各 package 的 `tests/conftest.py` 用 `pytest_plugins = ["orion_sdk._testing"]` 拉共用 fixtures(`isolate_sessions_dir` autouse、`tmp_ctx`、`mock_provider` 等)。

`orion_sdk._testing` 是 SDK wheel 內的 private module(雙底線開頭),由 sqlalchemy.testing / numpy.testing 同款 pattern。

`orion-model` 不依賴 SDK,自己的 `conftest.py` 是空的(只 `load_dotenv()`)。

## CI

(尚未設定 GitHub Actions / CI server。Phase 30+ 後補。)

## 相關

- [`../architecture/design-decisions.md`](../architecture/design-decisions.md) §9 — 為何 tests 分散到 package
- [troubleshooting.md](./troubleshooting.md)

.PHONY: help install test test-model test-sdk test-cli test-chat-api test-e2e-chat-api test-sidecar test-all lint typecheck \
        gen-types \
        dev-cli dev-api dev-web dev-cowork \
        demo-anthropic demo-openai \
        build-web build-cowork build-sidecar build-cowork-dist \
        clean

help:
	@echo "orion-agent monorepo (Phase 30+)"
	@echo ""
	@echo "Setup:"
	@echo "  install         uv sync + npm install"
	@echo ""
	@echo "Test / check:"
	@echo "  test            跑全部 5 個 package 的 pytest"
	@echo "  test-model      orion-model (LLM 抽象層)"
	@echo "  test-sdk        orion-sdk (agent runtime)"
	@echo "  test-cli        orion-cli (CLI 殼)"
	@echo "  test-chat-api   orion-chat-api (FastAPI + WS unit tests)"
	@echo "  test-e2e-chat-api  chat-api full-stack e2e (uvicorn + SQLite + WS)"
	@echo "  test-sidecar    orion-cowork-sidecar (stdio RPC)"
	@echo "  lint            uv run ruff check ."
	@echo "  typecheck       uv run mypy packages apps"
	@echo ""
	@echo "Type contract pipeline (chat 產品):"
	@echo "  gen-types       openapi + ws-schema → web/src/types/*.gen.ts"
	@echo ""
	@echo "Dev mode:"
	@echo "  dev-cli PROMPT='hello'   orion \"<PROMPT>\""
	@echo "  dev-api                  orion-chat-api serve --reload --port 8000"
	@echo "  dev-web                  vite dev (apps/orion-chat/web)"
	@echo "  dev-cowork               Electron + Vite + sidecar (apps/orion-cowork)"
	@echo "  demo-anthropic           跑 Claude demo:讀 /etc/hosts"
	@echo "  demo-openai              跑 GPT demo:讀 /etc/hosts"
	@echo ""
	@echo "Build:"
	@echo "  build-web                npm run build -w @orion/chat-web"
	@echo "  build-cowork             npm run build -w @orion/cowork (renderer + electron only)"
	@echo "  build-sidecar            PyInstaller → single-binary sidecar"
	@echo "  build-cowork-dist        完整 installer (sidecar + electron + electron-builder)"
	@echo ""
	@echo "Misc:"
	@echo "  clean                    清 caches + node_modules"

install:
	uv sync
	npm install

# ───── Tests ─────
test: test-model test-sdk test-cli test-chat-api test-sidecar

test-model:
	cd packages/orion-model && uv run pytest -q

test-sdk:
	cd packages/orion-sdk && uv run pytest -q

test-cli:
	cd apps/orion-cli && uv run pytest -q

test-chat-api:
	cd apps/orion-chat/api && uv run pytest -q

# Phase 31-E:chat-api full-stack e2e (uvicorn + SQLite + WS) — 顯式 opt-in。
test-e2e-chat-api:
	cd apps/orion-chat/api && uv run pytest tests/e2e -v -m e2e

test-sidecar:
	cd apps/orion-cowork/sidecar && uv run pytest -q

test-all: test test-e2e-chat-api
	@echo "(integration tests need API keys; cd packages/orion-sdk && uv run pytest -m integration)"
	@echo "(cowork e2e not implemented — see apps/orion-cowork/tests/e2e/README.md)"

# ───── Quality ─────
lint:
	uv run ruff check .

typecheck:
	uv run mypy packages apps

# ───── Type contract pipeline ─────
gen-types:
	npm run gen:types

# ───── Dev mode ─────
PROMPT ?= hello

dev-cli:
	uv run --package orion-cli orion "$(PROMPT)"

# Demo:跑一個讀檔案的 prompt 驗證 provider + tools 整條鏈通。
demo-anthropic:
	uv run --package orion-cli orion --provider anthropic --model claude-sonnet-4-6 \
	  "Read /etc/hosts and tell me what's in it"

demo-openai:
	uv run --package orion-cli orion --provider openai --model gpt-4o-mini \
	  "Read /etc/hosts and tell me what's in it"

dev-api:
	uv run --package orion-chat-api orion-chat-api serve --reload --port 8000

dev-web:
	npm run dev -w @orion/chat-web

dev-cowork:
	npm run dev -w @orion/cowork

# ───── Build ─────
build-web:
	npm run build -w @orion/chat-web

build-cowork:
	npm run build -w @orion/cowork

# Phase 31-A:把 sidecar 打包成 single binary。
# 輸出:apps/orion-cowork/dist/sidecar/orion-cowork-sidecar (host arch)
build-sidecar:
	cd apps/orion-cowork && rm -rf dist/sidecar build/pyinstaller
	uv run --package orion-cowork-sidecar pyinstaller \
	  --distpath apps/orion-cowork/dist/sidecar \
	  --workpath apps/orion-cowork/build/pyinstaller \
	  --noconfirm \
	  apps/orion-cowork/sidecar/pyinstaller.spec

# Phase 31-A:完整 Cowork installer(本機 host platform)。
# Build chain:sidecar binary → renderer + electron compile → electron-builder
build-cowork-dist: build-sidecar
	npm run build -w @orion/cowork
	npm run dist -w @orion/cowork

# ───── Clean ─────
clean:
	rm -rf .venv node_modules
	find . -type d -name __pycache__ -not -path "./.git/*" -exec rm -rf {} +
	find . -type d -name .pytest_cache -not -path "./.git/*" -exec rm -rf {} +
	find . -type d -name .mypy_cache -not -path "./.git/*" -exec rm -rf {} +
	find . -type d -name dist -not -path "./.git/*" -not -path "./node_modules/*" -exec rm -rf {} +

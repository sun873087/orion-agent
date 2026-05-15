.PHONY: help install test test-sdk test-sidecar test-all lint typecheck \
        gen-types \
        dev-cli dev-api dev-web dev-cowork \
        demo-anthropic demo-openai \
        build-web build-cowork \
        clean

help:
	@echo "orion-agent monorepo (Phase 30+)"
	@echo ""
	@echo "Setup:"
	@echo "  install         uv sync + npm install"
	@echo ""
	@echo "Test / check:"
	@echo "  test            跑 orion-sdk + orion-cowork-sidecar 兩套 pytest (預設)"
	@echo "  test-sdk        cd packages/orion-sdk && uv run pytest -q"
	@echo "  test-sidecar    cd apps/orion-cowork/sidecar && uv run pytest -q"
	@echo "  lint            uv run ruff check ."
	@echo "  typecheck       uv run mypy packages apps"
	@echo ""
	@echo "Type contract pipeline (chat 產品):"
	@echo "  gen-types       openapi + ws-schema → web/src/types/*.gen.ts"
	@echo ""
	@echo "Dev mode:"
	@echo "  dev-cli PROMPT='hello'   orion run \"<PROMPT>\""
	@echo "  dev-api                  orion-chat-api serve --reload --port 8000"
	@echo "  dev-web                  vite dev (apps/orion-chat/web)"
	@echo "  dev-cowork               Electron + Vite + sidecar (apps/orion-cowork)"
	@echo "  demo-anthropic           跑 Claude demo:讀 /etc/hosts"
	@echo "  demo-openai              跑 GPT demo:讀 /etc/hosts"
	@echo ""
	@echo "Build:"
	@echo "  build-web                npm run build -w @orion/chat-web"
	@echo "  build-cowork             npm run build -w @orion/cowork"
	@echo ""
	@echo "Misc:"
	@echo "  clean                    清 caches + node_modules"

install:
	uv sync
	npm install

# ───── Tests ─────
test: test-sdk test-sidecar

test-sdk:
	cd packages/orion-sdk && uv run pytest -q

test-sidecar:
	cd apps/orion-cowork/sidecar && uv run pytest -q

test-all: test
	@echo "(integration tests need API keys; cd packages/orion-sdk && uv run pytest -m integration)"

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
	uv run --package orion-cli orion run "$(PROMPT)"

# Demo:跑一個讀檔案的 prompt 驗證 provider + tools 整條鏈通。
demo-anthropic:
	uv run --package orion-cli orion run --provider anthropic --model claude-sonnet-4-6 \
	  "Read /etc/hosts and tell me what's in it"

demo-openai:
	uv run --package orion-cli orion run --provider openai --model gpt-4o-mini \
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

# ───── Clean ─────
clean:
	rm -rf .venv node_modules
	find . -type d -name __pycache__ -not -path "./.git/*" -exec rm -rf {} +
	find . -type d -name .pytest_cache -not -path "./.git/*" -exec rm -rf {} +
	find . -type d -name .mypy_cache -not -path "./.git/*" -exec rm -rf {} +
	find . -type d -name dist -not -path "./.git/*" -not -path "./node_modules/*" -exec rm -rf {} +

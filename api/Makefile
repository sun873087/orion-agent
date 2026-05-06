.PHONY: install test test-all typecheck lint format check run-anthropic run-openai clean help

help:
	@echo "Targets:"
	@echo "  install          Install dependencies via uv"
	@echo "  test             Run unit tests (no API key needed)"
	@echo "  test-all         Run unit + integration tests (needs API keys)"
	@echo "  typecheck        Run mypy --strict"
	@echo "  lint             Run ruff lint check"
	@echo "  format           Run ruff format"
	@echo "  check            Run lint + typecheck + test"
	@echo "  run-anthropic    Demo: read /etc/hosts via Claude"
	@echo "  run-openai       Demo: read /etc/hosts via GPT"
	@echo "  clean            Remove caches"

install:
	uv sync

test:
	uv run pytest tests/unit/ -v

test-all:
	uv run pytest tests/ -v

typecheck:
	uv run mypy --strict src/

lint:
	uv run ruff check src/ tests/

format:
	uv run ruff format src/ tests/

check: lint typecheck test

run-anthropic:
	uv run python -m orion_agent --provider anthropic --model claude-sonnet-4-6 \
	  "Read /etc/hosts and tell me what's in it"

run-openai:
	uv run python -m orion_agent --provider openai --model gpt-5 \
	  "Read /etc/hosts and tell me what's in it"

clean:
	rm -rf .pytest_cache .mypy_cache .ruff_cache htmlcov .coverage
	find . -type d -name __pycache__ -exec rm -rf {} +

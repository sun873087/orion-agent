.PHONY: install fix-install test test-all typecheck lint format check \
        run-anthropic run-openai clean clean-venv help

help:
	@echo "Targets:"
	@echo "  install          uv sync + 確保 editable install"
	@echo "  fix-install      清掉 iCloud 殘留的 dupe 檔再裝(macOS Desktop sync 救援)"
	@echo "  test             unit tests(無 API key)"
	@echo "  test-all         unit + integration(需 API keys)"
	@echo "  typecheck        mypy --strict"
	@echo "  lint             ruff check"
	@echo "  format           ruff format"
	@echo "  check            lint + typecheck + test"
	@echo "  run-anthropic    demo:read /etc/hosts via Claude"
	@echo "  run-openai       demo:read /etc/hosts via GPT"
	@echo "  clean            刪 caches(.pytest / .mypy / __pycache__)"
	@echo "  clean-venv       刪整個 .venv(碰到 import 異常時用)"

# uv sync 在 macOS Desktop(被 iCloud 同步)會偶發 file 重命名(.venv/.../X 2、X 3 ...)
# 所以 install target 連跑兩步:sync + reinstall editable,確保 .pth 真的存在
install:
	uv sync
	uv pip install -e . --reinstall

fix-install:
	@echo "==> 清 .venv 內的 iCloud-rename 殘檔(* 2、* 3 ...)"
	@find .venv -name "* [2-9]*" -print -delete 2>/dev/null || true
	@$(MAKE) install

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
	uv run orion --provider anthropic --model claude-sonnet-4-6 \
	  "Read /etc/hosts and tell me what's in it"

run-openai:
	uv run orion --provider openai --model gpt-4o-mini \
	  "Read /etc/hosts and tell me what's in it"

clean:
	rm -rf .pytest_cache .mypy_cache .ruff_cache htmlcov .coverage
	find . -type d -name __pycache__ -exec rm -rf {} +

clean-venv:
	rm -rf .venv

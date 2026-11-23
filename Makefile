# Development commands. Run `make` or `make help` for the list.

.DEFAULT_GOAL := help
.PHONY: help install test lint format format-check validate clean

help: ## Show available commands
	@grep -E '^[a-z-]+:.*## ' $(MAKEFILE_LIST) | awk 'BEGIN {FS = ":.*## "}; {printf "  %-14s %s\n", $$1, $$2}'

install: ## Install dependencies (including dev tools) into .venv
	uv sync

test: ## Run the tests
	uv run pytest

lint: ## Check code with ruff
	uv run ruff check .

format: ## Fix imports and lint issues ruff can fix, then format with black
	uv run ruff check --fix .
	uv run black .

format-check: ## Check formatting without changing files
	uv run black --check .

validate: lint format-check test ## Everything CI would run: lint, format check, tests

clean: ## Remove caches (keeps data/ and .venv)
	rm -rf .pytest_cache .ruff_cache
	find . -path ./.venv -prune -o -type d -name __pycache__ -print -exec rm -rf {} +

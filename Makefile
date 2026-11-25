# Development commands. Run `make` or `make help` for the list.

.DEFAULT_GOAL := help
.PHONY: help install test lint format format-check validate clean api dev \
	api-types api-types-check web-validate web-e2e web-build

help: ## Show available commands
	@grep -E '^[a-z-]+:.*## ' $(MAKEFILE_LIST) | awk 'BEGIN {FS = ":.*## "}; {printf "  %-16s %s\n", $$1, $$2}'

WEB := cd web && pnpm

install: ## Install Python (.venv) and web (web/node_modules) dependencies, with dev tools
	uv sync
	$(WEB) install --frozen-lockfile
	$(WEB) exec playwright install chromium-headless-shell

# Reinstall web dependencies when the lockfile changes (e.g. after a pull).
web/node_modules: web/package.json web/pnpm-lock.yaml
	$(WEB) install --frozen-lockfile
	touch $@

test: ## Run the tests
	uv run pytest

lint: ## Check code with ruff
	uv run ruff check .

format: web/node_modules ## Fix what ruff can fix, format with black; format web/ with Prettier
	uv run ruff check --fix --exit-zero .
	uv run black .
	$(WEB) run format

format-check: ## Check formatting without changing files
	uv run black --check .

validate: lint format-check test web-validate ## Everything CI would run (Python and web)

web-validate: web/node_modules api-types-check ## Web: types up to date, type check, lint, format, tests
	$(WEB) run typecheck
	$(WEB) run lint
	$(WEB) run format-check
	$(WEB) run test
	$(WEB) run e2e

web-e2e: web/node_modules ## Browser tests (Playwright, headless Chromium) on the production build
	$(WEB) run e2e

api-types: web/node_modules ## Regenerate web/src/api/types.ts after changing API models
	scripts/api-types.sh

api-types-check: web/node_modules ## Fail if web/src/api/types.ts is out of date
	scripts/api-types.sh --check

web-build: web/node_modules ## Build the web app into web/dist
	$(WEB) run build

api: ## Run the API on http://127.0.0.1:8000 with reload (try it at /docs)
	uv run map-routing api --reload

dev: web/node_modules ## API + web dev server with live reload: http://127.0.0.1:5173
	scripts/dev.sh

clean: ## Remove caches (keeps data/ and .venv)
	rm -rf .pytest_cache .ruff_cache web/dist web/test-results web/playwright-report
	find . -path ./.venv -prune -o -type d -name __pycache__ -print -exec rm -rf {} +

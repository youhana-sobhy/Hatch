PY ?= python
VENV ?= .venv
BIN := $(VENV)/bin

.PHONY: help install dev-api dev-ztp dev-ui test lint format templates demo up down

help: ## Show this help
	@grep -E '^[a-zA-Z_-]+:.*?## ' $(MAKEFILE_LIST) | awk 'BEGIN {FS = ":.*?## "}; {printf "  %-12s %s\n", $$1, $$2}'

install: ## Create the virtualenv and install everything
	$(PY) -m venv $(VENV)
	$(BIN)/pip install -e "orchestrator[dev]" -e "ztp-service[dev]" httpx
	cd ui && npm install

dev-api: ## Run the orchestrator with auto-reload on :8000
	cd orchestrator && ../$(BIN)/uvicorn app.main:app --reload --port 8000

dev-ztp: ## Run the ZTP edge service on :8081
	cd ztp-service && ../$(BIN)/uvicorn ztp.main:app --port 8081

dev-ui: ## Run the UI with hot reload on :5173
	cd ui && npm run dev

test: ## Run every test suite
	cd orchestrator && ../$(BIN)/pytest --cov=app
	cd ztp-service && ../$(BIN)/pytest
	cd ui && npm test

lint: ## Lint and type-check
	cd orchestrator && ../$(BIN)/ruff check app tests && ../$(BIN)/ruff format --check app tests && ../$(BIN)/mypy app
	cd ui && npx tsc -b --noEmit

format: ## Auto-format Python code
	cd orchestrator && ../$(BIN)/ruff format app tests && ../$(BIN)/ruff check --fix app tests

templates: ## Test-render every golden template against the baseline
	$(BIN)/hatchctl templates lint

demo: ## Seed demo onboardings and boot the ZTP devices
	$(BIN)/python tools/hatch_demo.py seed
	sleep 2
	$(BIN)/python tools/hatch_demo.py boot-all

up: ## Start the full stack with Docker Compose
	docker compose up --build -d

down: ## Stop the stack
	docker compose down

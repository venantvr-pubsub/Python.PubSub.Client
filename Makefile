.PHONY: install dev test test-simple clean build help venv

# Variables
VENV = .venv
PYTHON = $(VENV)/bin/python
PIP = $(VENV)/bin/pip
PYTEST = $(VENV)/bin/pytest

help: ## Show this help message
	@grep -E '^[a-zA-Z_-]+:.*?## .*$$' $(MAKEFILE_LIST) | awk 'BEGIN {FS = ":.*?## "}; {printf "\033[36m%-15s\033[0m %s\n", $$1, $$2}'

venv: ## Create virtual environment if it doesn't exist
	@if [ ! -d "$(VENV)" ]; then python3 -m venv $(VENV); fi
	@echo "Virtual environment ready at $(VENV)"

install: venv ## Install package in production mode
	$(PIP) install .

dev: venv ## Install package in development mode with dev dependencies
	$(PIP) install --upgrade pip
	$(PIP) install -e ".[dev]"

test: dev ## Run tests with coverage (requires dev dependencies)
	$(PYTEST) tests/

test-simple: venv ## Run tests without coverage (minimal dependencies)
	$(PYTHON) -m unittest discover tests -v

lint: dev ## Run code quality checks
	$(VENV)/bin/black --check --extend-exclude=".*\.md$$" src/ tests/
	$(VENV)/bin/isort --check-only --skip-glob="*.md" src/ tests/
	$(VENV)/bin/flake8 --max-line-length=140 --extend-ignore=E203,W503 --extend-exclude="*.md" src/ tests/

format: dev ## Format code
	$(VENV)/bin/black --extend-exclude=".*\.md$$" src/ tests/
	$(VENV)/bin/isort --skip-glob="*.md" src/ tests/

clean: ## Clean build artifacts
	rm -rf build/ dist/ *.egg-info .coverage htmlcov/ .pytest_cache/
	find . -type d -name __pycache__ -exec rm -rf {} + 2>/dev/null || true

build: clean dev ## Build package
	$(PIP) install --upgrade build
	$(PYTHON) -m build

.DEFAULT_GOAL := help
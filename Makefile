.PHONY: install dev test clean build help

help: ## Show this help message
	@grep -E '^[a-zA-Z_-]+:.*?## .*$$' $(MAKEFILE_LIST) | awk 'BEGIN {FS = ":.*?## "}; {printf "\033[36m%-15s\033[0m %s\n", $$1, $$2}'

install: ## Install package in production mode
	pip install .

dev: ## Install package in development mode
	pip install -e ".[dev]"

test: ## Run tests with coverage
	pytest tests/ --cov=pubsub --cov-report=term-missing

clean: ## Clean build artifacts
	rm -rf build/ dist/ *.egg-info .coverage htmlcov/ .pytest_cache/
	find . -type d -name __pycache__ -exec rm -rf {} + 2>/dev/null || true

build: clean ## Build package
	python -m build

.DEFAULT_GOAL := help
.PHONY: install dev test lint format clean build help

help: ## Show this help message
	@grep -E '^[a-zA-Z_-]+:.*?## .*$$' $(MAKEFILE_LIST) | awk 'BEGIN {FS = ":.*?## "}; {printf "\033[36m%-15s\033[0m %s\n", $$1, $$2}'

install: ## Install production dependencies
	pip install -r requirements.txt

dev: ## Install development dependencies
	pip install -r requirements-dev.txt
	pre-commit install

test: ## Run tests with coverage
	pytest tests/ --cov=pubsub --cov-report=term-missing

lint: ## Run linters (flake8, mypy)
	flake8 src/ tests/ --max-line-length=100
	mypy src/pubsub --ignore-missing-imports

format: ## Format code with black and isort
	isort src/ tests/ examples/
	black src/ tests/ examples/ --line-length=100

clean: ## Clean build artifacts
	rm -rf build/ dist/ *.egg-info .coverage htmlcov/ .pytest_cache/
	find . -type d -name __pycache__ -exec rm -rf {} + 2>/dev/null || true

build: clean ## Build package
	python -m build

.DEFAULT_GOAL := help
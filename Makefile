.PHONY: install test lint format example clean

install:
	pip install -e ".[dev]"

test:
	pytest tests/ -v --tb=short

test-cov:
	pytest tests/ --cov=migrationmind --cov-report=html --cov-report=term-missing

lint:
	ruff check .

format:
	ruff format .

typecheck:
	mypy migrationmind/

example:
	migrationmind analyze \
		--migration examples/migrations/0042_add_last_active.sql \
		--schema examples/schemas/ecommerce_schema.sql \
		--queries examples/query_logs/sample_slow_queries.log \
		--no-llm

clean:
	find . -type f -name "*.pyc" -delete
	find . -type d -name "__pycache__" -exec rm -rf {} + 2>/dev/null || true
	find . -type d -name "*.egg-info" -exec rm -rf {} + 2>/dev/null || true
	rm -rf build/ dist/ .coverage htmlcov/ .pytest_cache/ .ruff_cache/ .mypy_cache/

ci: lint typecheck test

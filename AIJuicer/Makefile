.PHONY: install test lint fmt type migrate run clean

install:
	pip install -e ".[dev]"
	pre-commit install

test:
	pytest -v --cov=scheduler --cov-report=term-missing

lint:
	ruff check scheduler sdk
	ruff format --check scheduler sdk

fmt:
	ruff format scheduler sdk
	ruff check --fix scheduler sdk

type:
	mypy scheduler sdk/aijuicer_sdk

migrate:
	alembic upgrade head

run:
	uvicorn scheduler.main:app --reload --host 0.0.0.0 --port 8000

clean:
	find . -type d -name __pycache__ -exec rm -rf {} +
	rm -rf .pytest_cache .mypy_cache .ruff_cache .coverage htmlcov

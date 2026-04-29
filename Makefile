.PHONY: help install hooks lint format type test cov eval replay ingest clean

help:
	@echo "Tongue-Doctor — common tasks"
	@echo ""
	@echo "  make install     uv sync (runtime + dev deps, Python 3.12)"
	@echo "  make hooks       install pre-commit hooks"
	@echo "  make lint        ruff check"
	@echo "  make format      ruff format"
	@echo "  make type        mypy on src/"
	@echo "  make test        pytest with coverage"
	@echo "  make cov         pytest with HTML coverage report"
	@echo "  make eval        run eval harness (chest_pain slice; raises until Phase 1)"
	@echo "  make replay      replay a case (placeholder)"
	@echo "  make ingest      run ingestion scripts (placeholder)"
	@echo "  make clean       remove caches + build artifacts"

install:
	uv sync

hooks:
	uv run pre-commit install

lint:
	uv run ruff check src tests eval scripts

format:
	uv run ruff format src tests eval scripts

type:
	uv run mypy src

test:
	uv run pytest

cov:
	uv run pytest --cov-report=html
	@echo "HTML coverage at htmlcov/index.html"

eval:
	uv run python -m eval.runner --slice chest_pain

replay:
	uv run python -m scripts.replay

ingest:
	@echo "Ingestion scripts are placeholders pending open item 22 (premium subs) and 23 (textbooks)."
	@echo "See scripts/ingest_statpearls.py once GCP project (item 21) is decided."

clean:
	rm -rf .mypy_cache .ruff_cache .pytest_cache .coverage htmlcov dist build
	find . -type d -name __pycache__ -prune -exec rm -rf {} +
	find . -type d -name '*.egg-info' -prune -exec rm -rf {} +

.PHONY: help install hooks lint format type test cov eval replay ingest clean \
	ingest-icd10cm ingest-uspstf ingest-openstax ingest-dailymed ingest-statpearls \
	ingest-pmc-oa ingest-stern acquire-quick acquire-corpus-status \
	extract-stern-templates

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
	@echo ""
	@echo "  Resource acquisition (free / public-domain corpora):"
	@echo "  make ingest-icd10cm    full ICD-10-CM (CMS, ~100K codes)"
	@echo "  make ingest-uspstf     all current USPSTF recommendations"
	@echo "  make ingest-openstax   OpenStax A&P 2e (PDF, ~470 MB)"
	@echo "  make ingest-dailymed   DailyMed SPL labels (full corpus, hours)"
	@echo "  make ingest-statpearls StatPearls full corpus (~9.6K articles, hours)"
	@echo "  make ingest-pmc-oa     PMC OA — pass QUERY=… (see scripts/ingest_pmc_oa.py)"
	@echo "  make ingest-stern      Stern, Symptoms to Diagnosis (user-provided PDF)"
	@echo "  make extract-stern-templates  Vision-augmented per-chapter template extraction"
	@echo "  make acquire-quick     small smoke run of every ingester"
	@echo "  make acquire-corpus-status   summary of knowledge/_local/MANIFEST.json"
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
	@echo "Pick a specific ingester: ingest-icd10cm, ingest-uspstf, ingest-openstax,"
	@echo "  ingest-dailymed, ingest-statpearls, ingest-pmc-oa, or acquire-quick."

ingest-icd10cm:
	uv run python scripts/ingest_icd10cm.py

ingest-uspstf:
	uv run python scripts/ingest_uspstf.py

ingest-openstax:
	uv run python scripts/ingest_openstax.py

ingest-dailymed:
	uv run python scripts/ingest_dailymed.py

ingest-statpearls:
	uv run python scripts/ingest_statpearls.py

# Override QUERY=... on the command line; default is a small case-report slice.
QUERY ?= open access[filter] AND case reports[publication type]
ingest-pmc-oa:
	uv run python scripts/ingest_pmc_oa.py --query "$(QUERY)"

ingest-stern:
	uv run python scripts/ingest_stern.py

# Vision-augmented extraction of Stern complaint chapters into templates.
# Pass CHAPTER=N for a single chapter (default: 9 = Chest Pain) or ALL=1 for all 31.
CHAPTER ?= 9
extract-stern-templates:
ifeq ($(ALL),1)
	uv run python scripts/extract_stern_to_templates.py --all
else
	uv run python scripts/extract_stern_to_templates.py --chapter $(CHAPTER)
endif

acquire-quick:
	uv run python scripts/ingest_icd10cm.py
	uv run python scripts/ingest_uspstf.py
	uv run python scripts/ingest_openstax.py
	uv run python scripts/ingest_dailymed.py --max-pages 2
	uv run python scripts/ingest_statpearls.py --max-articles 50
	uv run python scripts/ingest_pmc_oa.py \
	  --query "open access[filter] AND case reports[publication type]" \
	  --max-articles 50

acquire-corpus-status:
	@uv run python -c "import json,pathlib;m=json.loads(pathlib.Path('knowledge/_local/MANIFEST.json').read_text());print(f\"generated_at: {m['generated_at']}\");[print(f\"  {s['source']:25s} tier={s['authority_tier']} docs={s['doc_count']:>7d} chunks={s['chunk_count']:>7d}  ({s['license']})\") for s in m['sources']]"

clean:
	rm -rf .mypy_cache .ruff_cache .pytest_cache .coverage htmlcov dist build
	find . -type d -name __pycache__ -prune -exec rm -rf {} +
	find . -type d -name '*.egg-info' -prune -exec rm -rf {} +

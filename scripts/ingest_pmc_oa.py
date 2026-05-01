"""CLI: ingest a PMC Open Access query result.

Each invocation runs one E-utilities query and merges results into
``knowledge/_local/pmc_oa/``. Cached id lists and per-batch XML files mean
re-runs are cheap; pass ``--max-articles`` to cap a smoke.

Examples::

    # Smoke (50 case reports):
    uv run python scripts/ingest_pmc_oa.py \\
      --query 'open access[filter] AND case reports[publication type]' \\
      --max-articles 50

    # Bigger run:
    uv run python scripts/ingest_pmc_oa.py \\
      --query 'open access[filter] AND clinical trial[publication type] AND 2024[pdat]'

The tool refuses to run without ``--query``.
"""

from __future__ import annotations

import sys

import typer

from tongue_doctor.knowledge.ingest.base import default_root
from tongue_doctor.knowledge.ingest.sources.pmc_oa import PmcOaIngester
from tongue_doctor.knowledge.ingest.storage import LocalCorpusStore

app = typer.Typer(add_completion=False, help="Ingest a PMC OA query slice.")


@app.command()
def run(
    query: str = typer.Option(..., help="NCBI E-utilities query."),
    max_articles: int | None = typer.Option(
        None, help="Cap article count (None = walk full result list)."
    ),
    polite_interval_s: float = typer.Option(0.4, help="Min seconds between requests."),
    batch_size: int = typer.Option(50, help="Articles per efetch batch."),
) -> None:
    store = LocalCorpusStore(default_root())
    ingester = PmcOaIngester(
        store,
        query=query,
        max_articles=max_articles,
        polite_interval_s=polite_interval_s,
        batch_size=batch_size,
    )
    manifest = ingester.run()
    typer.echo(
        f"pmc_oa: ingested {manifest.chunk_count} chunks across {manifest.doc_count} articles."
    )


def main() -> int:
    app()
    return 0


if __name__ == "__main__":
    sys.exit(main())

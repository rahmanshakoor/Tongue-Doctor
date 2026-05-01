"""CLI: ingest DailyMed SPL labels via NLM REST API.

Examples::

    # Smoke (first 200 labels):
    uv run python scripts/ingest_dailymed.py --max-pages 2

    # Full corpus (~80K labels — many hours):
    uv run python scripts/ingest_dailymed.py
"""

from __future__ import annotations

import sys

import typer

from tongue_doctor.knowledge.ingest.base import default_root
from tongue_doctor.knowledge.ingest.sources.dailymed import DailyMedIngester
from tongue_doctor.knowledge.ingest.storage import LocalCorpusStore

app = typer.Typer(add_completion=False, help="Ingest DailyMed SPL labels.")


@app.command()
def run(
    pagesize: int = typer.Option(100, help="Items per API page (max 100)."),
    start_page: int = typer.Option(1, help="Resume from this page."),
    max_pages: int | None = typer.Option(
        None, help="Stop after this many pages (default: walk to end)."
    ),
    polite_interval_s: float = typer.Option(0.4, help="Min seconds between detail fetches."),
) -> None:
    store = LocalCorpusStore(default_root())
    ingester = DailyMedIngester(
        store,
        pagesize=pagesize,
        start_page=start_page,
        max_pages=max_pages,
        polite_interval_s=polite_interval_s,
    )
    manifest = ingester.run()
    typer.echo(
        f"dailymed: ingested {manifest.chunk_count} chunks across {manifest.doc_count} labels."
    )


def main() -> int:
    app()
    return 0


if __name__ == "__main__":
    sys.exit(main())

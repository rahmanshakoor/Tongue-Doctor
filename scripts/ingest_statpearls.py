"""CLI: ingest StatPearls articles via NCBI Bookshelf.

Examples::

    # Smoke (50 articles, ~3 min):
    uv run python scripts/ingest_statpearls.py --max-articles 50

    # Full corpus (~9.6K articles — many hours):
    uv run python scripts/ingest_statpearls.py
"""

from __future__ import annotations

import sys

import typer

from tongue_doctor.knowledge.ingest.base import default_root
from tongue_doctor.knowledge.ingest.sources.statpearls import StatPearlsIngester
from tongue_doctor.knowledge.ingest.storage import LocalCorpusStore

app = typer.Typer(add_completion=False, help="Ingest StatPearls (NCBI Bookshelf).")


@app.command()
def run(
    max_articles: int | None = typer.Option(
        None, help="Cap article count (None = full corpus)."
    ),
    polite_interval_s: float = typer.Option(0.4, help="Min seconds between requests."),
    batch_size: int = typer.Option(200, help="PubMed efetch batch size."),
) -> None:
    store = LocalCorpusStore(default_root())
    ingester = StatPearlsIngester(
        store,
        max_articles=max_articles,
        polite_interval_s=polite_interval_s,
        batch_size=batch_size,
    )
    manifest = ingester.run()
    typer.echo(
        f"statpearls: ingested {manifest.chunk_count} chunks across {manifest.doc_count} articles."
    )


def main() -> int:
    app()
    return 0


if __name__ == "__main__":
    sys.exit(main())

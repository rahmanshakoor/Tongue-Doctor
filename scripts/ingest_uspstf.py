"""CLI: scrape USPSTF recommendation pages.

Run::

    uv run python scripts/ingest_uspstf.py
"""

from __future__ import annotations

import sys

import typer

from tongue_doctor.knowledge.ingest.base import default_root
from tongue_doctor.knowledge.ingest.sources.uspstf import UspstfIngester
from tongue_doctor.knowledge.ingest.storage import LocalCorpusStore

app = typer.Typer(add_completion=False, help="Ingest USPSTF into knowledge/_local/uspstf/")


@app.command()
def run(
    polite_interval_s: float = typer.Option(1.0, help="Min seconds between HTTP requests."),
) -> None:
    store = LocalCorpusStore(default_root())
    ingester = UspstfIngester(store, polite_interval_s=polite_interval_s)
    manifest = ingester.run()
    typer.echo(
        f"uspstf: ingested {manifest.chunk_count} chunks across {manifest.doc_count} topics."
    )


def main() -> int:
    app()
    return 0


if __name__ == "__main__":
    sys.exit(main())

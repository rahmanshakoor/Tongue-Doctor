"""CLI: ingest the user-provided Stern PDF.

The PDF must already be at
``knowledge/_local/stern/raw/Symptom to Diagnosis 4th ed 2020.pdf`` (drop it manually;
this is not a download).

Run::

    uv run python scripts/ingest_stern.py
    uv run python scripts/ingest_stern.py --pdf-filename "Symptom to Diagnosis 5th ed 2025.pdf"
"""

from __future__ import annotations

import sys

import typer

from tongue_doctor.knowledge.ingest.base import default_root
from tongue_doctor.knowledge.ingest.sources.stern import (
    DEFAULT_EDITION,
    DEFAULT_PDF_FILENAME,
    DEFAULT_YEAR,
    SternIngester,
)
from tongue_doctor.knowledge.ingest.storage import LocalCorpusStore

app = typer.Typer(add_completion=False, help="Ingest the user-provided Stern PDF.")


@app.command()
def run(
    pdf_filename: str = typer.Option(
        DEFAULT_PDF_FILENAME,
        help="PDF filename inside knowledge/_local/stern/raw/.",
    ),
    edition: str = typer.Option(DEFAULT_EDITION, help="Edition string for citations."),
    year: str = typer.Option(DEFAULT_YEAR, help="Publication year for citations."),
) -> None:
    store = LocalCorpusStore(default_root())
    ingester = SternIngester(
        store, pdf_filename=pdf_filename, edition=edition, year=year
    )
    manifest = ingester.run()
    typer.echo(
        f"stern: ingested {manifest.chunk_count} chunks across "
        f"{manifest.doc_count} chapters."
    )


def main() -> int:
    app()
    return 0


if __name__ == "__main__":
    sys.exit(main())

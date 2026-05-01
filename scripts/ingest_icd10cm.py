"""CLI: ingest ICD-10-CM (CMS annual release).

Run::

    uv run python scripts/ingest_icd10cm.py
"""

from __future__ import annotations

import sys

import typer

from tongue_doctor.knowledge.ingest.base import default_root
from tongue_doctor.knowledge.ingest.sources.icd10cm import (
    DEFAULT_RELEASE,
    DEFAULT_URL,
    Icd10CmIngester,
)
from tongue_doctor.knowledge.ingest.storage import LocalCorpusStore

app = typer.Typer(add_completion=False, help="Ingest ICD-10-CM into knowledge/_local/icd10cm/")


@app.command()
def run(
    release: str = typer.Option(DEFAULT_RELEASE, help="CMS release year (matches URL)."),
    url: str = typer.Option(DEFAULT_URL, help="Override CMS download URL."),
) -> None:
    store = LocalCorpusStore(default_root())
    ingester = Icd10CmIngester(store, zip_url=url, release=release)
    manifest = ingester.run()
    typer.echo(
        f"icd10cm: ingested {manifest.chunk_count} chunks across {manifest.doc_count} codes "
        f"(release {release})."
    )


def main() -> int:
    app()
    return 0


if __name__ == "__main__":
    sys.exit(main())

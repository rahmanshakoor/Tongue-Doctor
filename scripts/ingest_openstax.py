"""CLI: ingest an OpenStax title (default: Anatomy & Physiology 2e).

Run::

    uv run python scripts/ingest_openstax.py
    uv run python scripts/ingest_openstax.py --slug microbiology
"""

from __future__ import annotations

import sys

import typer

from tongue_doctor.knowledge.ingest.base import default_root
from tongue_doctor.knowledge.ingest.sources.openstax import OpenStaxIngester
from tongue_doctor.knowledge.ingest.storage import LocalCorpusStore

app = typer.Typer(add_completion=False, help="Ingest an OpenStax book PDF.")


@app.command()
def run(
    slug: str = typer.Option(
        "anatomy-and-physiology-2e",
        help="OpenStax book slug (URL fragment under /books/).",
    ),
    min_toc_depth: int = typer.Option(
        2,
        help="TOC depth treated as section (1=chapter, 2=section, 3=subsection).",
    ),
) -> None:
    store = LocalCorpusStore(default_root())
    ingester = OpenStaxIngester(store, slug=slug, min_toc_depth=min_toc_depth)
    manifest = ingester.run()
    typer.echo(
        f"openstax/{slug}: ingested {manifest.chunk_count} chunks across "
        f"{manifest.doc_count} chapters."
    )


def main() -> int:
    app()
    return 0


if __name__ == "__main__":
    sys.exit(main())

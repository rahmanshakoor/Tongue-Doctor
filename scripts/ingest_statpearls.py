"""Ingest the StatPearls bulk download.

Phase 0 placeholder. Blocked on open kickoff item 21 (GCP project) for the dense-index
target. Once unblocked, this script:

1. Downloads the StatPearls XML bulk dump from NCBI Bookshelf.
2. Extracts article-level → section-level chunks (300-600 tokens), preserving citations.
3. Embeds chunks via ``text-embedding-005`` (Vertex).
4. Writes a BM25 index (in-process pickle) under ``knowledge/_local/statpearls/``.
5. Upserts dense embeddings into a Vertex Vector Search index.

See ``docs/RESOURCE_ACQUISITION.md``.
"""

from __future__ import annotations

import sys

import typer

app = typer.Typer(add_completion=False, help=__doc__.strip())


@app.command()
def run() -> None:
    """Run the StatPearls ingestion pipeline (not yet implemented)."""
    typer.echo(
        "ingest_statpearls.py is a placeholder. Blocked on open kickoff item 21 (GCP "
        "project) for dense-index target; the BM25-only path can run earlier.",
        err=True,
    )
    raise typer.Exit(code=2)


def main() -> int:
    app()
    return 0


if __name__ == "__main__":
    sys.exit(main())

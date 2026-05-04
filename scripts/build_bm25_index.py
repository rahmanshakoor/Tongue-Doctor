"""Build BM25 indices over every ingested corpus.

Walks ``knowledge/_local/<source>/`` for any directory containing ``chunks.jsonl``,
tokenizes each chunk, fits ``BM25Okapi``, and persists the index to
``knowledge/_local/<source>/bm25.pkl``. Run after ingestion or whenever a corpus
has been re-ingested.

::

    uv run python scripts/build_bm25_index.py
    uv run python scripts/build_bm25_index.py --only stern,statpearls
"""

from __future__ import annotations

import sys
import time
from pathlib import Path

import typer

from tongue_doctor.knowledge.ingest.base import default_root
from tongue_doctor.knowledge.ingest.storage import LocalCorpusStore
from tongue_doctor.retrieval.bm25 import build_index, save_index

app = typer.Typer(add_completion=False, help="Build BM25 indices over ingested corpora.")


@app.command()
def build(
    corpus_root: Path = typer.Option(
        None,
        "--corpus-root",
        help="Override the default corpus root (defaults to knowledge/_local).",
    ),
    only: str = typer.Option(
        "",
        "--only",
        help="Comma-separated list of source names to (re)build. Default: all discovered.",
    ),
) -> None:
    root = corpus_root or default_root()
    store = LocalCorpusStore(root)
    if not store.root.is_dir():
        typer.echo(f"corpus root not found: {store.root}", err=True)
        raise typer.Exit(code=1)

    if only:
        sources = [s.strip() for s in only.split(",") if s.strip()]
    else:
        sources = []
        for child in sorted(store.root.iterdir()):
            if child.is_dir() and (child / "chunks.jsonl").is_file():
                sources.append(child.name)

    if not sources:
        typer.echo(f"no corpora found under {store.root}", err=True)
        raise typer.Exit(code=1)

    total_chunks = 0
    typer.echo(f"building BM25 indices under {store.root}")
    for source in sources:
        t0 = time.perf_counter()
        index = build_index(source, store)
        path = save_index(index, store)
        n = len(index.chunk_ids)
        total_chunks += n
        size_mb = path.stat().st_size / (1024 * 1024)
        elapsed = time.perf_counter() - t0
        typer.echo(
            f"  {source:40s}  chunks={n:>7d}  pkl={size_mb:6.1f} MB  built in {elapsed:5.1f}s"
        )
    typer.echo(f"done. total_chunks={total_chunks} across {len(sources)} corpora.")


def main() -> int:
    app()
    return 0


if __name__ == "__main__":
    sys.exit(main())

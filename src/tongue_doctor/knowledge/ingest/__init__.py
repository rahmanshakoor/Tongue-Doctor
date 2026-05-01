"""Concrete ingestion pipelines for individual sources.

Each module in this package is responsible for one corpus: fetch raw artefacts,
parse them into ``Section`` lists, hand off to the shared chunker, and write
deduplicated :class:`tongue_doctor.knowledge.schema.Chunk` records to the
per-source directory under ``knowledge/_local/<source>/``.

The runtime never imports concrete modules from here — it reads ``chunks.jsonl``
files via :class:`tongue_doctor.knowledge.ingest.storage.LocalCorpusStore`.
"""

from tongue_doctor.knowledge.ingest.base import BaseIngester
from tongue_doctor.knowledge.ingest.storage import LocalCorpusStore

__all__ = ["BaseIngester", "LocalCorpusStore"]

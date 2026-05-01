"""Base class shared by every per-source ingester.

Subclasses implement :meth:`fetch` (download/raw) and :meth:`parse_documents`
(yield ``ParsedDocument`` records). The base wires chunking, chunk-id stamping,
manifest writing, and idempotent storage.
"""

from __future__ import annotations

import hashlib
from abc import ABC, abstractmethod
from collections.abc import Iterable, Iterator
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path

from tongue_doctor.knowledge.chunkers import Section, chunk_sections
from tongue_doctor.knowledge.ingest.storage import LocalCorpusStore
from tongue_doctor.knowledge.schema import AuthorityTier, Chunk, IngestionManifest


@dataclass(frozen=True)
class ParsedDocument:
    """One source document expanded into named sections.

    Citation is built per-document because each article / drug / guideline has its
    own bibliographic stub. Authority tier is set per-document too (a corpus may
    contain mixed tiers — guidelines vs. their attached patient leaflets).
    """

    source_doc_id: str
    title: str
    sections: list[Section]
    citation: str
    authority_tier: AuthorityTier
    url: str | None
    license: str
    metadata: dict[str, object]


class BaseIngester(ABC):
    """Abstract pipeline: fetch → parse → chunk → write."""

    source: str
    citation_template: str = ""
    notes: str = ""

    def __init__(self, store: LocalCorpusStore) -> None:
        self.store = store

    @abstractmethod
    def fetch(self) -> None:
        """Populate ``store.source_dir(self.source) / 'raw'`` from the network.

        Implementations may skip download if cached files are already present and
        usable; print a one-liner for visibility.
        """

    @abstractmethod
    def parse_documents(self) -> Iterator[ParsedDocument]:
        """Walk the raw artefacts and yield one :class:`ParsedDocument` each."""

    def run(self) -> IngestionManifest:
        self.fetch()
        chunks = list(self._build_chunks())
        chunk_count = self.store.write_chunks(self.source, chunks)
        doc_count = len({c.source_doc_id for c in chunks})
        manifest = IngestionManifest(
            source=self.source,
            authority_tier=self._dominant_tier(chunks),
            chunk_count=chunk_count,
            doc_count=doc_count,
            license=chunks[0].license if chunks else "unknown",
            ingested_at=datetime.now(UTC),
            citation_template=self.citation_template,
            notes=self.notes,
        )
        self.store.write_manifest(manifest)
        return manifest

    def _build_chunks(self) -> Iterable[Chunk]:
        ingested_at = datetime.now(UTC)
        for doc in self.parse_documents():
            payloads = chunk_sections(doc.sections)
            for payload in payloads:
                cid = self._chunk_id(doc.source_doc_id, payload.section, payload.ord)
                yield Chunk(
                    chunk_id=cid,
                    source=self.source,
                    source_doc_id=doc.source_doc_id,
                    title=doc.title,
                    section=payload.section,
                    source_location=payload.location,
                    text=payload.text,
                    token_count=payload.token_count,
                    citation=doc.citation,
                    authority_tier=doc.authority_tier,
                    url=doc.url,
                    license=doc.license,
                    ingested_at=ingested_at,
                    metadata=doc.metadata,
                )

    def _chunk_id(self, doc_id: str, section: str, ord_: int) -> str:
        h = hashlib.sha256(f"{self.source}|{doc_id}|{section}|{ord_}".encode()).hexdigest()
        return h[:16]

    @staticmethod
    def _dominant_tier(chunks: list[Chunk]) -> AuthorityTier:
        if not chunks:
            return AuthorityTier.TEXTBOOK
        counts: dict[AuthorityTier, int] = {}
        for c in chunks:
            counts[c.authority_tier] = counts.get(c.authority_tier, 0) + 1
        return min(counts.items(), key=lambda kv: (kv[0].value, -kv[1]))[0]


def default_root() -> Path:
    return Path(__file__).resolve().parents[4] / "knowledge" / "_local"

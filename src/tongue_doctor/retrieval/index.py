"""Multi-corpus BM25 facade.

Wraps a set of :class:`CorpusBM25Index` instances with:

- Authority-tier weighted score merging (GUIDELINE > CLINICAL_REFERENCE > TEXTBOOK).
- Lazy chunk resolution — the pickle stores only ``chunk_id``s; on first ``search()``
  per corpus, we read ``chunks.jsonl`` once into a dict for ``chunk_id`` → :class:`Chunk`
  lookup.
- Auto-discovery of corpora from ``knowledge/_local/`` (any subdirectory containing a
  ``chunks.jsonl`` and a ``bm25.pkl``).

This is the retrieval surface every agent calls. It is intentionally synchronous — BM25
queries are sub-millisecond on the merged 109K corpus and adding ``async`` would be cosmetic.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import TYPE_CHECKING

from pydantic import BaseModel, ConfigDict

from tongue_doctor.knowledge.ingest.base import default_root
from tongue_doctor.knowledge.ingest.storage import LocalCorpusStore
from tongue_doctor.knowledge.schema import AuthorityTier, Chunk
from tongue_doctor.retrieval.bm25 import (
    CorpusBM25Index,
    build_index,
    load_index,
    save_index,
    tokenize,
)

if TYPE_CHECKING:
    from collections.abc import Iterable


# Default authority weights. GUIDELINE outranks CLINICAL_REFERENCE outranks TEXTBOOK.
DEFAULT_AUTHORITY_WEIGHTS: dict[AuthorityTier, float] = {
    AuthorityTier.GUIDELINE: 1.5,
    AuthorityTier.CLINICAL_REFERENCE: 1.2,
    AuthorityTier.TEXTBOOK: 1.0,
}


class ScoredChunk(BaseModel):
    """A retrieved chunk with its merged score and rank."""

    model_config = ConfigDict(extra="forbid")

    chunk: Chunk
    score: float
    rank: int


@dataclass
class _CorpusEntry:
    source: str
    index: CorpusBM25Index
    chunks_by_id: dict[str, Chunk] = field(default_factory=dict)
    loaded: bool = False


class BM25Index:
    """Multi-corpus retrieval facade.

    Build/load on construction. Indexes that are missing on disk get built on the fly
    (so a fresh checkout works without an explicit ``build_bm25_index`` step) — but for
    production runs you should call ``scripts/build_bm25_index.py`` once to amortize.
    """

    def __init__(
        self,
        *,
        corpus_root: Path | None = None,
        sources: Iterable[str] | None = None,
        autobuild_missing: bool = False,
    ) -> None:
        self.store = LocalCorpusStore(corpus_root or default_root())
        self.entries: dict[str, _CorpusEntry] = {}
        discovered = list(sources) if sources is not None else self._discover_sources()
        for source in discovered:
            index = load_index(source, self.store)
            if index is None:
                if not autobuild_missing:
                    continue
                index = build_index(source, self.store)
                save_index(index, self.store)
            self.entries[source] = _CorpusEntry(source=source, index=index)

    @property
    def sources(self) -> list[str]:
        return sorted(self.entries.keys())

    def _discover_sources(self) -> list[str]:
        if not self.store.root.is_dir():
            return []
        out: list[str] = []
        for child in sorted(self.store.root.iterdir()):
            if not child.is_dir():
                continue
            chunks = child / "chunks.jsonl"
            if chunks.is_file():
                out.append(child.name)
        return out

    def _ensure_chunks_loaded(self, entry: _CorpusEntry) -> None:
        if entry.loaded:
            return
        for chunk in self.store.read_chunks(entry.source):
            entry.chunks_by_id[chunk.chunk_id] = chunk
        entry.loaded = True

    def search(
        self,
        query: str,
        *,
        corpora: list[str] | None = None,
        top_k: int = 25,
        per_corpus_top_k: int | None = None,
        min_authority_tier: AuthorityTier | None = None,
        authority_weight: dict[AuthorityTier, float] | None = None,
    ) -> list[ScoredChunk]:
        """Search the corpora and return up to ``top_k`` :class:`ScoredChunk`s.

        - ``corpora`` selects which sources to query; default is all available.
        - ``per_corpus_top_k`` controls how many candidates each corpus contributes
          before the global merge (default: ``2 * top_k`` to give the merge headroom).
        - ``authority_weight`` overrides the default tier multipliers.
        """

        weights = {**DEFAULT_AUTHORITY_WEIGHTS, **(authority_weight or {})}
        per_k = per_corpus_top_k if per_corpus_top_k is not None else max(top_k * 2, 50)
        active = corpora if corpora is not None else self.sources

        query_tokens = tokenize(query)
        merged: list[tuple[str, str, float]] = []  # (source, chunk_id, weighted_score)
        for source in active:
            entry = self.entries.get(source)
            if entry is None:
                continue
            self._ensure_chunks_loaded(entry)
            hits = entry.index.query(query_tokens, top_k=per_k)
            for chunk_id, score in hits:
                chunk = entry.chunks_by_id.get(chunk_id)
                if chunk is None:
                    continue
                tier = chunk.authority_tier
                if min_authority_tier is not None and tier > min_authority_tier:
                    # IntEnum: 1 (GUIDELINE) is most authoritative; tiers above the
                    # threshold int are dropped.
                    continue
                weight = weights.get(tier, 1.0)
                merged.append((source, chunk_id, score * weight))

        merged.sort(key=lambda x: x[2], reverse=True)
        merged = merged[:top_k]

        results: list[ScoredChunk] = []
        for rank, (source, chunk_id, weighted) in enumerate(merged, start=1):
            chunk = self.entries[source].chunks_by_id[chunk_id]
            results.append(ScoredChunk(chunk=chunk, score=weighted, rank=rank))
        return results

    def __contains__(self, source: str) -> bool:
        return source in self.entries

    def __repr__(self) -> str:
        sizes = {s: len(e.index.chunk_ids) for s, e in self.entries.items()}
        return f"BM25Index(sources={sizes})"


__all__ = [
    "DEFAULT_AUTHORITY_WEIGHTS",
    "BM25Index",
    "ScoredChunk",
]

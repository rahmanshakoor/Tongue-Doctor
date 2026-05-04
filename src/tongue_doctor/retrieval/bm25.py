"""Per-corpus BM25 index over ingested chunks.

Implements a light index that wraps ``rank_bm25.BM25Okapi`` and persists it to
``knowledge/_local/<source>/bm25.pkl`` so subsequent processes can mmap-load instead
of rebuilding.

Tokenization is intentionally simple — lowercase, regex split on word boundaries,
drop tokens shorter than 2 characters, drop a small stoplist. Medical-jargon is
preserved (no stemming, no clinical-acronym table). This is good enough for trial
retrieval; Phase 1b adds dense embeddings + reranker on top.
"""

from __future__ import annotations

import pickle
import re
from collections.abc import Iterable
from dataclasses import dataclass
from pathlib import Path

from rank_bm25 import BM25Okapi  # type: ignore[import-untyped]

from tongue_doctor.knowledge.ingest.storage import LocalCorpusStore

_TOKEN_RE = re.compile(r"[A-Za-z][A-Za-z0-9]+|\d+")

_STOPWORDS = frozenset(
    {
        "the", "is", "and", "or", "of", "to", "for", "with", "in", "on",
        "at", "by", "as", "be", "was", "are", "this", "that", "which",
        "from", "an", "a", "it", "its", "but", "if", "not", "no", "yes",
        "we", "you", "they", "he", "she", "him", "her", "his", "their",
        "them", "our", "your", "my", "i", "do", "does", "did", "have",
        "has", "had", "will", "would", "should", "can", "could", "may",
        "might", "shall", "than", "then", "so", "such", "also", "into",
        "between", "while", "when", "where", "who", "whom", "what", "why",
        "how", "all", "any", "some", "each", "every", "both", "either",
        "neither", "more", "most", "less", "least", "up", "down", "out",
        "over", "under", "after", "before", "during", "about", "above",
        "below", "since", "until", "though", "although", "because",
    }
)


def tokenize(text: str) -> list[str]:
    """Tokenize text for BM25 indexing.

    - Lowercase
    - Match alpha tokens (>= 2 chars) and digit tokens
    - Drop common-English stopwords
    - Preserve medical jargon and acronyms (no stemming, no acronym list)
    """

    out: list[str] = []
    for match in _TOKEN_RE.finditer(text):
        tok = match.group(0).lower()
        if len(tok) < 2:
            continue
        if tok in _STOPWORDS:
            continue
        out.append(tok)
    return out


@dataclass
class CorpusBM25Index:
    """A single-corpus BM25 index plus its parallel ``chunk_ids`` array.

    The pickle on disk is ``{tokenized: list[list[str]], chunk_ids: list[str], bm25: BM25Okapi}``.
    """

    source: str
    tokenized: list[list[str]]
    chunk_ids: list[str]
    bm25: BM25Okapi

    def query(self, query_tokens: list[str], *, top_k: int) -> list[tuple[str, float]]:
        """Return ``[(chunk_id, score), …]`` for the top-k matches."""

        if not self.chunk_ids:
            return []
        scores = self.bm25.get_scores(query_tokens)
        indexed = sorted(enumerate(scores), key=lambda x: x[1], reverse=True)[:top_k]
        return [(self.chunk_ids[i], float(s)) for i, s in indexed if s > 0.0]


def build_index(source: str, store: LocalCorpusStore) -> CorpusBM25Index:
    """Read ``chunks.jsonl`` for ``source``, tokenize each chunk, fit BM25, return the index."""

    tokenized: list[list[str]] = []
    chunk_ids: list[str] = []
    for chunk in store.read_chunks(source):
        tokens = tokenize(chunk.text)
        tokenized.append(tokens)
        chunk_ids.append(chunk.chunk_id)
    if not tokenized:
        # rank_bm25 raises on empty corpora; emit a sentinel index instead.
        return CorpusBM25Index(
            source=source, tokenized=[], chunk_ids=[], bm25=BM25Okapi([[""]])
        )
    bm25 = BM25Okapi(tokenized)
    return CorpusBM25Index(source=source, tokenized=tokenized, chunk_ids=chunk_ids, bm25=bm25)


def index_path(source: str, store: LocalCorpusStore) -> Path:
    """Path to the pickle file for ``source``."""

    return store.source_dir(source) / "bm25.pkl"


def save_index(index: CorpusBM25Index, store: LocalCorpusStore) -> Path:
    """Write the BM25 index to disk and return the path."""

    path = index_path(index.source, store)
    payload = {
        "source": index.source,
        "tokenized": index.tokenized,
        "chunk_ids": index.chunk_ids,
        "bm25": index.bm25,
    }
    with path.open("wb") as f:
        pickle.dump(payload, f, protocol=pickle.HIGHEST_PROTOCOL)
    return path


def load_index(source: str, store: LocalCorpusStore) -> CorpusBM25Index | None:
    """Load the BM25 index from disk; return ``None`` if it doesn't exist."""

    path = index_path(source, store)
    if not path.is_file():
        return None
    with path.open("rb") as f:
        payload = pickle.load(f)
    return CorpusBM25Index(
        source=payload["source"],
        tokenized=payload["tokenized"],
        chunk_ids=payload["chunk_ids"],
        bm25=payload["bm25"],
    )


def build_all(sources: Iterable[str], store: LocalCorpusStore) -> dict[str, Path]:
    """Build and persist BM25 indexes for every named corpus.

    Returns a ``{source: pickle_path}`` map for caller-side reporting.
    """

    out: dict[str, Path] = {}
    for source in sources:
        index = build_index(source, store)
        path = save_index(index, store)
        out[source] = path
    return out

"""Tests for BM25 retrieval over ingested corpora.

Builds tiny on-disk fixture corpora under a tmp_path so the test exercises the same
:class:`LocalCorpusStore` read path the runtime uses, and the same on-disk pickle
serialization. No real corpora are touched.
"""

from __future__ import annotations

from datetime import UTC, datetime
from pathlib import Path

import pytest

from tongue_doctor.knowledge.ingest.storage import LocalCorpusStore
from tongue_doctor.knowledge.schema import AuthorityTier, Chunk
from tongue_doctor.retrieval.bm25 import (
    build_index,
    load_index,
    save_index,
    tokenize,
)
from tongue_doctor.retrieval.index import BM25Index

# --- tokenize ---


def test_tokenize_lowercases_and_drops_short_tokens() -> None:
    tokens = tokenize("Acute MI in 55-year-old man with chest pain.")
    assert "acute" in tokens
    assert "mi" in tokens  # 2-char acronym preserved
    assert "55" in tokens  # numeric preserved
    assert "the" not in tokens  # stopword stripped
    assert "in" not in tokens  # 2-char stopword stripped


def test_tokenize_strips_common_stopwords() -> None:
    tokens = tokenize("the patient was admitted for the workup")
    assert "the" not in tokens
    assert "was" not in tokens
    assert "patient" in tokens
    assert "admitted" in tokens
    assert "workup" in tokens


def test_tokenize_preserves_medical_jargon_and_acronyms() -> None:
    tokens = tokenize("CHF, DM, COPD, and HTN are common")
    for term in ["chf", "dm", "copd", "htn", "common"]:
        assert term in tokens


def test_tokenize_handles_empty() -> None:
    assert tokenize("") == []
    assert tokenize("    ") == []


# --- index build / save / load ---


def _mk_chunk(
    *,
    source: str,
    chunk_id: str,
    text: str,
    tier: AuthorityTier = AuthorityTier.TEXTBOOK,
    title: str = "Doc",
) -> Chunk:
    return Chunk(
        chunk_id=chunk_id,
        source=source,
        source_doc_id="doc1",
        title=title,
        section=None,
        source_location="p.1",
        text=text,
        token_count=len(text.split()),
        citation=f"{source} test",
        authority_tier=tier,
        url=None,
        license="test",
        ingested_at=datetime.now(UTC),
        metadata={},
    )


def _seed_corpus(store: LocalCorpusStore, source: str, chunks: list[Chunk]) -> None:
    store.write_chunks(source, chunks)


@pytest.fixture
def store(tmp_path: Path) -> LocalCorpusStore:
    return LocalCorpusStore(tmp_path / "knowledge")


def test_build_index_over_small_corpus(store: LocalCorpusStore) -> None:
    chunks = [
        _mk_chunk(source="stern", chunk_id="a", text="Acute chest pain in MI"),
        _mk_chunk(source="stern", chunk_id="b", text="Aortic dissection presents with tearing pain"),
        _mk_chunk(source="stern", chunk_id="c", text="Hypertension management lifestyle and medications"),
    ]
    _seed_corpus(store, "stern", chunks)

    idx = build_index("stern", store)
    assert idx.source == "stern"
    assert len(idx.chunk_ids) == 3
    assert idx.chunk_ids == ["a", "b", "c"]


def test_save_and_load_roundtrip(store: LocalCorpusStore) -> None:
    chunks = [
        _mk_chunk(source="stern", chunk_id="a", text="Acute chest pain"),
        _mk_chunk(source="stern", chunk_id="b", text="Severe headache thunderclap"),
    ]
    _seed_corpus(store, "stern", chunks)

    idx = build_index("stern", store)
    path = save_index(idx, store)
    assert path.is_file()

    loaded = load_index("stern", store)
    assert loaded is not None
    assert loaded.chunk_ids == idx.chunk_ids
    assert loaded.tokenized == idx.tokenized


def test_load_index_missing_returns_none(store: LocalCorpusStore) -> None:
    # No chunks written, no pickle exists.
    assert load_index("nonexistent", store) is None


def test_query_returns_top_k_in_descending_score(store: LocalCorpusStore) -> None:
    chunks = [
        _mk_chunk(source="stern", chunk_id="a", text="acute MI chest pain ECG"),
        _mk_chunk(source="stern", chunk_id="b", text="hypertension management lifestyle"),
        _mk_chunk(source="stern", chunk_id="c", text="acute MI workup ECG troponin"),
        _mk_chunk(source="stern", chunk_id="d", text="diabetes glucose insulin"),
        _mk_chunk(source="stern", chunk_id="e", text="asthma bronchodilator wheezing"),
    ]
    _seed_corpus(store, "stern", chunks)
    idx = build_index("stern", store)

    hits = idx.query(["acute", "mi", "ecg"], top_k=3)
    assert len(hits) >= 2
    scores = [s for _, s in hits]
    assert scores == sorted(scores, reverse=True)
    # The two MI-relevant chunks should outrank everything else.
    top_ids = {chunk_id for chunk_id, _ in hits[:2]}
    assert top_ids == {"a", "c"}


# --- BM25Index facade ---


def test_facade_searches_single_corpus(store: LocalCorpusStore) -> None:
    # BM25 IDF is unstable on tiny corpora (terms appearing in > N/2 docs get
    # negative IDF, near-zero scores). Use enough documents that a clear winner
    # emerges.
    chunks = [
        _mk_chunk(source="stern", chunk_id="a", text="acute MI ECG ST elevation troponin"),
        _mk_chunk(source="stern", chunk_id="b", text="otitis media middle ear infection"),
        _mk_chunk(source="stern", chunk_id="c", text="diabetes mellitus type 2 insulin resistance"),
        _mk_chunk(source="stern", chunk_id="d", text="hypertension blood pressure systolic"),
        _mk_chunk(source="stern", chunk_id="e", text="asthma bronchodilator wheezing"),
    ]
    _seed_corpus(store, "stern", chunks)
    save_index(build_index("stern", store), store)

    facade = BM25Index(corpus_root=store.root, sources=["stern"])
    results = facade.search("MI ECG troponin", top_k=5)
    assert len(results) >= 1
    assert results[0].chunk.chunk_id == "a"
    assert results[0].rank == 1


def test_facade_multi_corpus_authority_weighting(store: LocalCorpusStore) -> None:
    """A GUIDELINE chunk should outrank an equally-scoring TEXTBOOK chunk."""

    target = "screening guideline for hypertension in adults"
    # Pad each corpus so BM25 IDF is non-degenerate.
    pad = [
        ("p1", "asthma bronchodilator wheezing children"),
        ("p2", "diabetes mellitus insulin glucose"),
        ("p3", "fracture orthopedic cast immobilization"),
    ]
    _seed_corpus(
        store,
        "uspstf",
        [_mk_chunk(source="uspstf", chunk_id="g1", text=target, tier=AuthorityTier.GUIDELINE)]
        + [_mk_chunk(source="uspstf", chunk_id=cid, text=t, tier=AuthorityTier.GUIDELINE) for cid, t in pad],
    )
    _seed_corpus(
        store,
        "stern",
        [_mk_chunk(source="stern", chunk_id="t1", text=target, tier=AuthorityTier.TEXTBOOK)]
        + [_mk_chunk(source="stern", chunk_id=cid, text=t, tier=AuthorityTier.TEXTBOOK) for cid, t in pad],
    )
    save_index(build_index("uspstf", store), store)
    save_index(build_index("stern", store), store)

    facade = BM25Index(corpus_root=store.root, sources=["uspstf", "stern"])
    results = facade.search("hypertension screening guideline adults", top_k=4)
    # The two target chunks should top the list; GUIDELINE wins on equal raw BM25.
    top_two_sources = [r.chunk.source for r in results[:2]]
    assert top_two_sources[0] == "uspstf"
    assert "stern" in top_two_sources


def test_facade_filters_by_min_authority_tier(store: LocalCorpusStore) -> None:
    target = "diabetes screening recommendations adults"
    pad = [
        ("p1", "asthma bronchodilator wheezing children"),
        ("p2", "fracture orthopedic cast immobilization"),
        ("p3", "anemia iron deficiency hemoglobin"),
    ]
    _seed_corpus(
        store,
        "uspstf",
        [_mk_chunk(source="uspstf", chunk_id="g1", text=target, tier=AuthorityTier.GUIDELINE)]
        + [_mk_chunk(source="uspstf", chunk_id=cid, text=t, tier=AuthorityTier.GUIDELINE) for cid, t in pad],
    )
    _seed_corpus(
        store,
        "stern",
        [_mk_chunk(source="stern", chunk_id="t1", text=target, tier=AuthorityTier.TEXTBOOK)]
        + [_mk_chunk(source="stern", chunk_id=cid, text=t, tier=AuthorityTier.TEXTBOOK) for cid, t in pad],
    )
    save_index(build_index("uspstf", store), store)
    save_index(build_index("stern", store), store)

    facade = BM25Index(corpus_root=store.root, sources=["uspstf", "stern"])
    results = facade.search(
        "diabetes screening recommendations",
        top_k=10,
        min_authority_tier=AuthorityTier.CLINICAL_REFERENCE,
    )
    # Only GUIDELINE (tier=1) and CLINICAL_REFERENCE (tier=2) should pass; TEXTBOOK (tier=3) drops.
    sources = {r.chunk.source for r in results}
    assert sources == {"uspstf"}


def test_facade_corpora_filter(store: LocalCorpusStore) -> None:
    target = "acute coronary syndrome workup ECG troponin"
    pad = [
        ("p1", "asthma bronchodilator wheezing"),
        ("p2", "fracture orthopedic cast"),
        ("p3", "anemia iron deficiency hemoglobin"),
    ]
    _seed_corpus(
        store,
        "stern",
        [_mk_chunk(source="stern", chunk_id="a", text=target)]
        + [_mk_chunk(source="stern", chunk_id=cid, text=t) for cid, t in pad],
    )
    _seed_corpus(
        store,
        "statpearls",
        [_mk_chunk(source="statpearls", chunk_id="b", text=target)]
        + [_mk_chunk(source="statpearls", chunk_id=cid, text=t) for cid, t in pad],
    )
    save_index(build_index("stern", store), store)
    save_index(build_index("statpearls", store), store)

    facade = BM25Index(corpus_root=store.root, sources=["stern", "statpearls"])
    results = facade.search("acute coronary syndrome", corpora=["stern"], top_k=5)
    assert all(r.chunk.source == "stern" for r in results)
    assert len(results) >= 1


def test_facade_handles_empty_query_gracefully(store: LocalCorpusStore) -> None:
    pad_chunks = [
        _mk_chunk(source="stern", chunk_id="a", text="acute coronary syndrome"),
        _mk_chunk(source="stern", chunk_id="b", text="diabetes mellitus management"),
        _mk_chunk(source="stern", chunk_id="c", text="hypertension blood pressure"),
    ]
    _seed_corpus(store, "stern", pad_chunks)
    save_index(build_index("stern", store), store)

    facade = BM25Index(corpus_root=store.root, sources=["stern"])
    # An empty/stopword-only query returns no hits, not an error.
    assert facade.search("the and or", top_k=5) == []


def test_facade_autobuild_missing(store: LocalCorpusStore) -> None:
    """When the pickle is missing and ``autobuild_missing=True``, we build on the fly."""

    chunks = [
        _mk_chunk(source="stern", chunk_id="a", text="screening for diabetes mellitus"),
        _mk_chunk(source="stern", chunk_id="b", text="hypertension blood pressure"),
        _mk_chunk(source="stern", chunk_id="c", text="asthma bronchodilator therapy"),
    ]
    _seed_corpus(store, "stern", chunks)
    # No save_index call — the pickle should be missing.

    facade = BM25Index(corpus_root=store.root, sources=["stern"], autobuild_missing=True)
    assert "stern" in facade.sources
    results = facade.search("diabetes screening", top_k=2)
    assert len(results) >= 1
    assert results[0].chunk.chunk_id == "a"

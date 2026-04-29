"""Retrieval client + hybrid (BM25 + dense + rerank) pipeline.

Phase 0 ships an empty package. Concrete modules (``client.py``, ``router.py``,
``bm25.py``, ``dense.py``, ``hybrid.py``, ``reranker.py``, ``authority.py``) land in
Phase 1 alongside the first corpus ingestion. See ``KICKOFF_PLAN.md`` §8.
"""

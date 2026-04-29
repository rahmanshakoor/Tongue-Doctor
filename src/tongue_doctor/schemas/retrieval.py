"""Retrieval result schema."""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, ConfigDict

AuthorityTier = Literal[1, 2, 3]
"""1 = guideline (highest), 2 = clinical reference, 3 = textbook concept (lowest)."""


class RetrievalResult(BaseModel):
    """One chunk returned by the Retriever, ready for prompt context."""

    model_config = ConfigDict(extra="forbid")

    query: str
    index: str
    chunk_id: str
    text: str
    source: str
    citation: str
    authority_tier: AuthorityTier
    score: float
    embedding_model: str | None = None
    reranker: str | None = None

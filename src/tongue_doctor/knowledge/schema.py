"""Chunk and manifest schemas for ingested corpora.

A :class:`Chunk` is the atomic retrieval unit. Section-level granularity (300-600
tokens) per kickoff §9. Each chunk carries a citation, authority tier, license, and
enough provenance (``source``, ``source_doc_id``, ``url``) that the Reasoner can
construct a verifiable reference and any downstream consumer can re-fetch the source.

An :class:`IngestionManifest` summarises one corpus drop on disk so the runtime can
discover what's available without re-walking large directory trees.
"""

from __future__ import annotations

from datetime import datetime
from enum import IntEnum
from typing import Any

from pydantic import BaseModel, ConfigDict, Field


class AuthorityTier(IntEnum):
    """Per kickoff §8 — guideline > clinical reference > textbook."""

    GUIDELINE = 1
    CLINICAL_REFERENCE = 2
    TEXTBOOK = 3


class Chunk(BaseModel):
    """A single retrieval unit.

    ``chunk_id`` is a deterministic hash of (source, source_doc_id, section_id, ord)
    so re-ingestion is idempotent and BM25/dense indices stay aligned.
    """

    model_config = ConfigDict(extra="forbid", frozen=True)

    chunk_id: str
    source: str
    source_doc_id: str
    title: str
    section: str | None
    source_location: str
    """Precise pointer back to the source artefact.

    Format is source-specific but always reproducible — never invent values:

    - PDFs (OpenStax, WHO, AHA): ``"p.145-148"`` or ``"p.145"`` if single page.
    - StatPearls: ``"NBK430685#etiology"`` (Bookshelf ID + section heading).
    - DailyMed SPL: ``"setid:abc-123/loinc:34067-9"``.
    - ICD-10-CM: ``"code:I20.9"`` (the code itself is the citation).
    - PMC OA: ``"PMC1234567#sec-2"`` or ``"PMC1234567/p.<para-id>"``.
    - HTML scrapes: ``"<canonical-url>#<anchor>"``.

    Used by the synthesizer to render verifiable citations in user-facing output.
    """
    text: str
    token_count: int
    citation: str
    authority_tier: AuthorityTier
    url: str | None
    license: str
    ingested_at: datetime
    metadata: dict[str, Any] = Field(default_factory=dict)


class IngestionManifest(BaseModel):
    """Per-source manifest written next to ``chunks.jsonl``.

    The runtime reads ``MANIFEST.json`` to enumerate available corpora and their
    counts/versions without scanning chunk files.
    """

    model_config = ConfigDict(extra="forbid", frozen=True)

    source: str
    authority_tier: AuthorityTier
    chunk_count: int
    doc_count: int
    license: str
    ingested_at: datetime
    source_version: str | None = None
    notes: str = ""
    citation_template: str = ""

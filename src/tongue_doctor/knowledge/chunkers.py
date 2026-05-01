"""Token-aware section chunker.

Strategy (per kickoff §9, "section-level chunking 300-600 tokens"):

- A section ≤ ``max_tokens`` is emitted whole.
- A larger section is sliced at paragraph then sentence boundaries, packed into
  windows of ``target_tokens`` with ``overlap_tokens`` of overlap so adjacent chunks
  share context.
- Each emitted chunk inherits the section title; the chunker prepends it as a header
  line so retrieval gets section-level signal even with bag-of-words BM25.

The ``cl100k_base`` tokenizer is good enough for length budgeting; we don't need the
exact tokenizer of any specific model at ingest time.
"""

from __future__ import annotations

import re
from collections.abc import Iterator
from dataclasses import dataclass

import tiktoken

_TOKENIZER = tiktoken.get_encoding("cl100k_base")

_PARAGRAPH_BREAK = re.compile(r"\n\s*\n")
_SENTENCE_BREAK = re.compile(r"(?<=[.!?])\s+(?=[A-Z0-9])")


@dataclass(frozen=True)
class Section:
    """A titled span of source text destined for chunking.

    ``location`` is a source-specific pointer (page range, anchor, NBK section ID,
    SPL LOINC code, …). It propagates to every chunk this section produces so the
    Reasoner can surface a precise citation, not just a document-level reference.
    """

    title: str
    text: str
    location: str


@dataclass(frozen=True)
class ChunkPayload:
    """Output of the chunker — section title and location are preserved separately
    so the caller attaches them to the structured :class:`Chunk` rather than
    baking them into the body silently."""

    section: str
    text: str
    token_count: int
    ord: int
    location: str


def count_tokens(text: str) -> int:
    return len(_TOKENIZER.encode(text))


def _split_paragraphs(text: str) -> list[str]:
    return [p.strip() for p in _PARAGRAPH_BREAK.split(text) if p.strip()]


def _split_sentences(paragraph: str) -> list[str]:
    return [s.strip() for s in _SENTENCE_BREAK.split(paragraph) if s.strip()]


def _pack(units: list[str], target: int, overlap: int) -> Iterator[tuple[str, int]]:
    """Pack ``units`` (paragraphs or sentences) into windows ≤ ``target`` tokens with
    ``overlap`` carry-over. Yields ``(window_text, token_count)``."""

    buf: list[str] = []
    buf_tokens = 0
    for unit in units:
        unit_tokens = count_tokens(unit)
        if unit_tokens >= target and not buf:
            yield unit, unit_tokens
            continue
        if buf_tokens + unit_tokens > target and buf:
            window = "\n\n".join(buf)
            yield window, buf_tokens
            if overlap > 0:
                tail = buf[-1]
                tail_tokens = count_tokens(tail)
                if tail_tokens <= overlap:
                    buf = [tail]
                    buf_tokens = tail_tokens
                else:
                    buf = []
                    buf_tokens = 0
            else:
                buf = []
                buf_tokens = 0
        buf.append(unit)
        buf_tokens += unit_tokens
    if buf:
        yield "\n\n".join(buf), buf_tokens


def chunk_sections(
    sections: list[Section],
    *,
    target_tokens: int = 450,
    max_tokens: int = 600,
    overlap_tokens: int = 60,
) -> list[ChunkPayload]:
    """Slice ``sections`` into retrieval-sized payloads.

    Sections shorter than ``max_tokens`` are emitted whole. Longer ones are packed
    into ``target_tokens`` windows with ``overlap_tokens`` of carry-over.
    """

    out: list[ChunkPayload] = []
    ord_counter = 0
    for section in sections:
        text = section.text.strip()
        if not text:
            continue
        total_tokens = count_tokens(text)
        if total_tokens <= max_tokens:
            out.append(
                ChunkPayload(
                    section=section.title,
                    text=text,
                    token_count=total_tokens,
                    ord=ord_counter,
                    location=section.location,
                )
            )
            ord_counter += 1
            continue

        paragraphs = _split_paragraphs(text)
        units: list[str] = []
        for p in paragraphs:
            if count_tokens(p) <= target_tokens:
                units.append(p)
            else:
                units.extend(_split_sentences(p))

        for window, tokens in _pack(units, target=target_tokens, overlap=overlap_tokens):
            out.append(
                ChunkPayload(
                    section=section.title,
                    text=window,
                    token_count=tokens,
                    ord=ord_counter,
                    location=section.location,
                )
            )
            ord_counter += 1
    return out

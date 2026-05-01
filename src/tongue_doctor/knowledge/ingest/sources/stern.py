"""Stern, Cifu & Altkorn — *Symptoms to Diagnosis* (4th ed., 2020) ingester.

The PDF is **user-provided** under
``knowledge/_local/stern/raw/Symptom to Diagnosis 4th ed 2020.pdf`` (personal-research
copy). ``fetch`` therefore only verifies presence — it does not download.

Stern's TOC is flat: 33 numbered chapters at level 1 plus front matter and Index. We
filter to entries matching ``"^\\d+\\.\\s+"`` to keep only the numbered chapters, then
emit **one ``ParsedDocument`` per chapter, one ``Section`` per page**. Per the project
directive, every chunk inherits a precise per-page ``source_location = "p.<n>"`` so
the Reasoner can cite an exact page rather than a chapter range.

Authority tier: TEXTBOOK (3). Citation per-document carries the chapter page range;
the per-page reference lives in the chunk's ``source_location`` so consumers can
combine the two for full bibliographic precision.

License: ``personal-research; user-provided digital copy``. Per ADR 0003 (research-demo
ToS posture) the corpus stays inside the IAP-gated demo, never shipped verbatim.
"""

from __future__ import annotations

import re
from collections.abc import Iterator
from typing import cast

import fitz  # pymupdf

from tongue_doctor.knowledge.chunkers import Section
from tongue_doctor.knowledge.ingest.base import BaseIngester, ParsedDocument
from tongue_doctor.knowledge.ingest.storage import LocalCorpusStore
from tongue_doctor.knowledge.schema import AuthorityTier

DEFAULT_PDF_FILENAME = "Symptom to Diagnosis 4th ed 2020.pdf"
DEFAULT_EDITION = "4th"
DEFAULT_YEAR = "2020"

_CHAPTER_RE = re.compile(r"^(\d+)\.\s+(.+)$")


class SternIngester(BaseIngester):
    source = "stern"
    citation_template = (
        "Stern, Cifu, Altkorn. Symptoms to Diagnosis ({edition} ed., {year}), "
        "Ch. {ch_num}: {title}, pp. {page_range}."
    )
    notes = (
        "Symptoms to Diagnosis (4th ed., 2020); user-provided personal copy. "
        "One document per chapter, one section per page; chunk source_location is "
        "the rendered PDF page (p.<n>)."
    )

    def __init__(
        self,
        store: LocalCorpusStore,
        *,
        pdf_filename: str = DEFAULT_PDF_FILENAME,
        edition: str = DEFAULT_EDITION,
        year: str = DEFAULT_YEAR,
    ) -> None:
        super().__init__(store)
        self.pdf_filename = pdf_filename
        self.edition = edition
        self.year = year

    def fetch(self) -> None:
        raw_dir = self.store.source_dir(self.source) / "raw"
        pdf_path = raw_dir / self.pdf_filename
        if not pdf_path.is_file():
            raise FileNotFoundError(
                f"Stern PDF not found at {pdf_path}. Drop the user-provided PDF there "
                "(filename must match exactly, including spaces and case)."
            )
        print(f"[stern] using {pdf_path.name} ({pdf_path.stat().st_size} bytes)")

    def parse_documents(self) -> Iterator[ParsedDocument]:
        raw_dir = self.store.source_dir(self.source) / "raw"
        pdf_path = raw_dir / self.pdf_filename
        with fitz.open(pdf_path) as doc:
            for ch_num, title, start, end in self._extract_chapter_ranges(doc):
                sections = self._build_sections(doc, ch_num, title, start, end)
                if not sections:
                    continue
                page_range = f"{start}" if start == end else f"{start}-{end}"
                doc_id = f"ch{ch_num:02d}_{_slugify(title)}"
                yield ParsedDocument(
                    source_doc_id=doc_id,
                    title=f"Stern Ch. {ch_num}: {title}",
                    sections=sections,
                    citation=self.citation_template.format(
                        edition=self.edition,
                        year=self.year,
                        ch_num=ch_num,
                        title=title,
                        page_range=page_range,
                    ),
                    authority_tier=AuthorityTier.TEXTBOOK,
                    url=None,
                    license="personal-research; user-provided digital copy",
                    metadata={
                        "chapter_num": ch_num,
                        "chapter_title": title,
                        "page_start": start,
                        "page_end": end,
                        "edition": self.edition,
                        "year": self.year,
                    },
                )

    @staticmethod
    def _extract_chapter_ranges(
        doc: fitz.Document,
    ) -> list[tuple[int, str, int, int]]:
        """Walk the flat TOC, keep numbered chapters, compute end-pages."""

        toc = doc.get_toc(simple=True)
        return chapter_ranges_from_toc(toc, doc.page_count)

    @staticmethod
    def _build_sections(
        doc: fitz.Document,
        ch_num: int,
        title: str,
        start: int,
        end: int,
    ) -> list[Section]:
        """Emit one Section per page so each chunk inherits a precise ``p.<n>`` location.

        TOC pages are 1-indexed; pymupdf is 0-indexed.
        """

        sections: list[Section] = []
        for p in range(start, end + 1):
            if p < 1 or p > doc.page_count:
                continue
            text = doc.load_page(p - 1).get_text("text").strip()
            if not text:
                continue
            sections.append(
                Section(
                    title=f"Ch. {ch_num}: {title} — p. {p}",
                    text=text,
                    location=f"p.{p}",
                )
            )
        return sections


def _slugify(text: str) -> str:
    """Lowercase, replace non-alphanumerics with ``_``, collapse repeats.

    Per the project slug rule: "Chest Pain" → "chest_pain";
    "Kidney Injury, Acute" → "kidney_injury_acute";
    "AIDS/HIV Infection" → "aids_hiv_infection".
    """

    return re.sub(r"[^a-z0-9]+", "_", text.lower()).strip("_") or "section"


def chapter_ranges_from_toc(
    toc: list[list[object]], total_pages: int
) -> list[tuple[int, str, int, int]]:
    """Pure TOC walker. Keep numbered chapters; compute end-pages.

    TOC entries that don't match ``^\\d+\\.\\s+`` (Cover, Title Page, Preface,
    Index, etc.) are filtered out. End-page is the next TOC entry's start minus
    one; for the final chapter, end is the next non-chapter TOC entry (Index)
    start minus one, falling back to ``total_pages``. Exposed at module level so
    unit tests can hit it without opening a real PDF.
    """

    toc_pages: list[int] = [cast(int, page) for _, _, page in toc]
    chapters: list[tuple[int, str, int]] = []
    for level, title, page in toc:
        if cast(int, level) != 1:
            continue
        m = _CHAPTER_RE.match(cast(str, title).strip())
        if m:
            chapters.append((int(m.group(1)), m.group(2).strip(), cast(int, page)))
    ranges: list[tuple[int, str, int, int]] = []
    for i, (ch_num, ch_title, start) in enumerate(chapters):
        if i + 1 < len(chapters):
            end = chapters[i + 1][2] - 1
        else:
            later = [p for p in toc_pages if p > start]
            end = (later[0] - 1) if later else total_pages
        if end < start:
            end = start
        ranges.append((ch_num, ch_title, start, end))
    return ranges

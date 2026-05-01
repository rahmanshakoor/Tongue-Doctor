"""OpenStax textbook ingester.

OpenStax titles are published under CC-BY-NC-SA 4.0 and cleanly bookmarked, so
the PDF table of contents drives section boundaries directly. Each TOC entry at
``min_toc_depth`` becomes a section with the natural page range as
``source_location``.

We default to the *Anatomy and Physiology 2e* title (canonical PDF URL discovered
via the OpenStax CMS API at ingest time) but the ingester is parametric so the
same code can pull other OpenStax books later (Microbiology, Biology, etc.).
"""

from __future__ import annotations

from collections.abc import Iterator
from pathlib import Path
from typing import cast

import fitz  # pymupdf

from tongue_doctor.knowledge.chunkers import Section
from tongue_doctor.knowledge.ingest._http import download_to, http_client
from tongue_doctor.knowledge.ingest.base import BaseIngester, ParsedDocument
from tongue_doctor.knowledge.ingest.storage import LocalCorpusStore
from tongue_doctor.knowledge.schema import AuthorityTier

CMS_BOOK_URL = "https://openstax.org/apps/cms/api/v2/pages/?type=books.Book&fields=*&slug={slug}"


class OpenStaxIngester(BaseIngester):
    citation_template = "OpenStax. {title} (pp. {page_range}). CC-BY-NC-SA 4.0."
    notes = "OpenStax title; CC-BY-NC-SA 4.0; chapter/section page ranges from PDF bookmarks."

    def __init__(
        self,
        store: LocalCorpusStore,
        *,
        slug: str,
        source: str | None = None,
        min_toc_depth: int = 2,
    ) -> None:
        super().__init__(store)
        self.slug = slug
        self.source = source or f"openstax_{slug.replace('-', '_')}"
        self.min_toc_depth = min_toc_depth
        self._title: str = slug
        self._pdf_url: str = ""
        self._html_url: str = ""

    def fetch(self) -> None:
        raw_dir: Path = self.store.source_dir(self.source) / "raw"
        meta = self._fetch_book_meta()
        self._title = str(meta.get("title") or self.slug)
        self._pdf_url = str(meta.get("high_resolution_pdf_url") or "")
        meta_block = meta.get("meta")
        if isinstance(meta_block, dict):
            self._html_url = str(meta_block.get("html_url") or "")
        if not self._pdf_url:
            raise RuntimeError(f"No PDF URL listed for OpenStax slug {self.slug!r}")
        pdf_path = raw_dir / f"{self.slug}.pdf"
        if pdf_path.exists() and pdf_path.stat().st_size > 0:
            print(f"[openstax/{self.slug}] cached {pdf_path.name}")
            return
        print(f"[openstax/{self.slug}] downloading {self._pdf_url} -> {pdf_path}")
        with http_client(timeout_s=180.0) as client:
            download_to(client, self._pdf_url, pdf_path)
        print(f"[openstax/{self.slug}] downloaded {pdf_path.stat().st_size} bytes")

    def _fetch_book_meta(self) -> dict[str, object]:
        with http_client() as client:
            response = client.get(CMS_BOOK_URL.format(slug=self.slug))
            response.raise_for_status()
            payload = response.json()
        items = payload.get("items") or []
        if not items:
            raise RuntimeError(f"OpenStax CMS returned no book for slug {self.slug!r}")
        return cast(dict[str, object], items[0])

    def parse_documents(self) -> Iterator[ParsedDocument]:
        raw_dir: Path = self.store.source_dir(self.source) / "raw"
        pdf_path = raw_dir / f"{self.slug}.pdf"
        if not pdf_path.is_file():
            return
        if not self._title:
            self._fetch_book_meta()
        with fitz.open(pdf_path) as doc:
            toc = doc.get_toc(simple=True)
            if not toc:
                yield self._whole_book(doc)
                return
            yield from self._documents_from_toc(doc, toc)

    def _documents_from_toc(
        self, doc: fitz.Document, toc: list[list[object]]
    ) -> Iterator[ParsedDocument]:
        leaves = [
            (cast(int, level), cast(str, title), cast(int, page))
            for level, title, page in toc
            if cast(int, level) >= self.min_toc_depth
        ]
        if not leaves:
            yield self._whole_book(doc)
            return
        total_pages = doc.page_count
        bounded: list[tuple[str, int, int]] = []
        for i, (_, title, start_page) in enumerate(leaves):
            end_page = (leaves[i + 1][2] - 1) if i + 1 < len(leaves) else total_pages
            if end_page < start_page:
                end_page = start_page
            bounded.append((title, start_page, end_page))
        chapter_groups = self._group_by_chapter(toc, bounded)
        for chapter_title, sections_meta in chapter_groups:
            sections = []
            min_page = total_pages
            max_page = 1
            for section_title, start, end in sections_meta:
                text = self._extract_pages(doc, start, end)
                if not text.strip():
                    continue
                page_range = f"{start}" if start == end else f"{start}-{end}"
                sections.append(
                    Section(
                        title=section_title,
                        text=text,
                        location=f"{self._html_url}#p.{page_range}",
                    )
                )
                min_page = min(min_page, start)
                max_page = max(max_page, end)
            if not sections:
                continue
            doc_id = _slugify(chapter_title)
            page_range = f"{min_page}" if min_page == max_page else f"{min_page}-{max_page}"
            yield ParsedDocument(
                source_doc_id=doc_id,
                title=f"{self._title}: {chapter_title}",
                sections=sections,
                citation=self.citation_template.format(
                    title=self._title, page_range=page_range
                ),
                authority_tier=AuthorityTier.TEXTBOOK,
                url=self._html_url,
                license="CC-BY-NC-SA-4.0",
                metadata={
                    "openstax_slug": self.slug,
                    "chapter_title": chapter_title,
                    "page_start": min_page,
                    "page_end": max_page,
                },
            )

    @staticmethod
    def _group_by_chapter(
        toc: list[list[object]], bounded: list[tuple[str, int, int]]
    ) -> list[tuple[str, list[tuple[str, int, int]]]]:
        """Use TOC depth-1 entries (chapters) as grouping keys for depth-2+ leaves."""

        chapters_by_first_page: dict[int, str] = {}
        for level, title, page in toc:
            if cast(int, level) == 1:
                chapters_by_first_page[cast(int, page)] = cast(str, title)
        chapter_starts = sorted(chapters_by_first_page.items())
        groups: dict[str, list[tuple[str, int, int]]] = {}
        order: list[str] = []
        for section_title, start, end in bounded:
            chapter = "Front matter"
            for first_page, title in chapter_starts:
                if start >= first_page:
                    chapter = title
                else:
                    break
            if chapter not in groups:
                groups[chapter] = []
                order.append(chapter)
            groups[chapter].append((section_title, start, end))
        return [(chapter, groups[chapter]) for chapter in order]

    def _whole_book(self, doc: fitz.Document) -> ParsedDocument:
        text = self._extract_pages(doc, 1, doc.page_count)
        return ParsedDocument(
            source_doc_id=self.slug,
            title=self._title,
            sections=[
                Section(
                    title=self._title,
                    text=text,
                    location=f"{self._html_url}#p.1-{doc.page_count}",
                )
            ],
            citation=self.citation_template.format(
                title=self._title, page_range=f"1-{doc.page_count}"
            ),
            authority_tier=AuthorityTier.TEXTBOOK,
            url=self._html_url,
            license="CC-BY-NC-SA-4.0",
            metadata={"openstax_slug": self.slug, "no_toc": True},
        )

    @staticmethod
    def _extract_pages(doc: fitz.Document, start_page: int, end_page: int) -> str:
        # pymupdf is 0-indexed; TOC pages are 1-indexed.
        out: list[str] = []
        for p in range(max(0, start_page - 1), min(doc.page_count, end_page)):
            out.append(doc.load_page(p).get_text("text"))
        return "\n".join(out).strip()


def _slugify(text: str) -> str:
    import re

    return re.sub(r"[^a-z0-9]+", "-", text.lower()).strip("-") or "section"

"""StatPearls ingester (NCBI Bookshelf via PubMed metadata + HTML scrape).

NCBI E-utilities expose StatPearls article metadata cleanly (PMID → NBK + section
titles) but not section bodies. Bodies live on the rendered Bookshelf page. We
combine the two:

1. ``esearch`` PubMed for ``statpearls[publisher]`` → list of PMIDs (paginated).
2. ``efetch`` PubMed XML in batches of 200 → maps each PMID to its NBK accession,
   title, abstract, and ordered section titles.
3. For each NBK, fetch ``https://www.ncbi.nlm.nih.gov/books/NBK<id>/`` once and
   slice it by heading using the section titles from step 2 as canonical anchors.

Source location format: ``NBK<id>#<section-anchor>``. Authority tier 3 (textbook
content; review-style, peer-edited but not guideline-grade).

Resumable: cached PubMed XML batches and per-article HTML survive between runs.
``--max-articles`` lets you cap a smoke run.

License posture: StatPearls articles carry a Creative-Commons-like Bookshelf
licence allowing personal-research use with attribution; full ingestion for
public redistribution would require separate review. We retrieve, cite, and use
internally only. See ``docs/RESOURCE_ACQUISITION.md``.
"""

from __future__ import annotations

import time
from collections.abc import Iterator
from pathlib import Path

from bs4 import BeautifulSoup, Tag
from lxml import etree

from tongue_doctor.knowledge.chunkers import Section
from tongue_doctor.knowledge.ingest._http import get_with_retry, http_client
from tongue_doctor.knowledge.ingest.base import BaseIngester, ParsedDocument
from tongue_doctor.knowledge.schema import AuthorityTier

EUTILS = "https://eutils.ncbi.nlm.nih.gov/entrez/eutils"
ESEARCH = (
    EUTILS
    + "/esearch.fcgi?db=pubmed&term=statpearls%5Bpublisher%5D&retstart={start}&retmax={size}"
)
EFETCH = EUTILS + "/efetch.fcgi?db=pubmed&id={ids}&rettype=xml"
BOOKSHELF_URL = "https://www.ncbi.nlm.nih.gov/books/{nbk}/"


class StatPearlsIngester(BaseIngester):
    source = "statpearls"
    citation_template = "{title}. StatPearls Publishing. NCBI Bookshelf {nbk}, PMID {pmid}."
    notes = (
        "StatPearls articles via NCBI Bookshelf; personal-research access with citation. "
        "Full corpus is ~9.6K articles; run with --max-articles for smoke or unlimited for "
        "long-running background ingest."
    )

    def __init__(
        self,
        store: object,
        *,
        max_articles: int | None = None,
        polite_interval_s: float = 0.4,
        batch_size: int = 200,
    ) -> None:
        super().__init__(store)  # type: ignore[arg-type]
        self.max_articles = max_articles
        self.polite_interval_s = polite_interval_s
        self.batch_size = batch_size

    def fetch(self) -> None:
        raw_dir: Path = self.store.source_dir(self.source) / "raw"  # type: ignore[attr-defined]
        meta_dir = raw_dir / "metadata"
        html_dir = raw_dir / "html"
        meta_dir.mkdir(exist_ok=True)
        html_dir.mkdir(exist_ok=True)

        with http_client(timeout_s=120.0) as client:
            pmids = self._collect_pmids(client, meta_dir)
            if self.max_articles is not None:
                pmids = pmids[: self.max_articles]
            print(f"[statpearls] target articles: {len(pmids)}")
            metadata_by_pmid = self._fetch_pubmed_metadata(client, meta_dir, pmids)
            self._fetch_html(client, html_dir, metadata_by_pmid)

    def _collect_pmids(self, client: object, meta_dir: Path) -> list[str]:
        cache = meta_dir / "pmids.txt"
        if cache.exists() and cache.stat().st_size > 0:
            cached = [line.strip() for line in cache.read_text().splitlines() if line.strip()]
            print(f"[statpearls] using cached PMID list ({len(cached)})")
            return cached

        pmids: list[str] = []
        start = 0
        size = 9999
        while True:
            response = get_with_retry(
                client,  # type: ignore[arg-type]
                ESEARCH.format(start=start, size=size),
            )
            ids = etree.fromstring(response.content).xpath("//IdList/Id/text()")
            ids = [str(i) for i in ids]
            if not ids:
                break
            pmids.extend(ids)
            if len(ids) < size:
                break
            start += size
            time.sleep(self.polite_interval_s)
        cache.write_text("\n".join(pmids) + "\n", encoding="utf-8")
        print(f"[statpearls] discovered {len(pmids)} StatPearls PMIDs")
        return pmids

    def _fetch_pubmed_metadata(
        self, client: object, meta_dir: Path, pmids: list[str]
    ) -> dict[str, dict[str, object]]:
        out: dict[str, dict[str, object]] = {}
        for batch_start in range(0, len(pmids), self.batch_size):
            batch = pmids[batch_start : batch_start + self.batch_size]
            cache = meta_dir / f"batch_{batch_start:06d}.xml"
            if not cache.exists() or cache.stat().st_size == 0:
                response = get_with_retry(
                    client,  # type: ignore[arg-type]
                    EFETCH.format(ids=",".join(batch)),
                )
                cache.write_bytes(response.content)
                time.sleep(self.polite_interval_s)
            for record in self._parse_pubmed_batch(cache):
                out[record["pmid"]] = record  # type: ignore[index]
        print(f"[statpearls] parsed metadata for {len(out)} articles")
        return out

    @staticmethod
    def _parse_pubmed_batch(xml_path: Path) -> Iterator[dict[str, object]]:
        tree = etree.parse(str(xml_path))
        for book in tree.xpath("//PubmedBookArticle"):
            pmid = (book.xpath(".//PMID/text()") or [""])[0]
            nbk = (book.xpath('.//ArticleId[@IdType="bookaccession"]/text()') or [""])[0]
            title = (book.xpath(".//ArticleTitle/text()") or [""])[0]
            abstract = " ".join(book.xpath(".//Abstract/AbstractText//text()")).strip()
            sections = [
                str(t).strip()
                for t in book.xpath(".//Sections/Section/SectionTitle/text()")
                if str(t).strip()
            ]
            authors = [
                f"{(a.xpath('LastName/text()') or [''])[0]}, "
                f"{(a.xpath('ForeName/text()') or [''])[0]}".strip(", ")
                for a in book.xpath(".//AuthorList/Author")
            ]
            if not pmid or not nbk:
                continue
            yield {
                "pmid": pmid,
                "nbk": nbk,
                "title": title.strip() or nbk,
                "abstract": abstract,
                "section_titles": sections,
                "authors": authors,
            }

    def _fetch_html(
        self,
        client: object,
        html_dir: Path,
        metadata: dict[str, dict[str, object]],
    ) -> None:
        fetched = 0
        for pmid, meta in metadata.items():
            nbk = str(meta["nbk"])
            dest = html_dir / f"{nbk}.html"
            if dest.exists() and dest.stat().st_size > 0:
                continue
            try:
                response = get_with_retry(client, BOOKSHELF_URL.format(nbk=nbk))  # type: ignore[arg-type]
            except Exception as exc:
                print(f"[statpearls] skip {nbk} (PMID {pmid}): {exc}")
                continue
            dest.write_text(response.text, encoding="utf-8")
            fetched += 1
            time.sleep(self.polite_interval_s)
            if fetched and fetched % 100 == 0:
                print(f"[statpearls] fetched {fetched} HTML pages")
        print(f"[statpearls] fetched {fetched} new HTML pages")

    def parse_documents(self) -> Iterator[ParsedDocument]:
        raw_dir: Path = self.store.source_dir(self.source) / "raw"  # type: ignore[attr-defined]
        meta_dir = raw_dir / "metadata"
        html_dir = raw_dir / "html"

        metadata: dict[str, dict[str, object]] = {}
        for batch_xml in sorted(meta_dir.glob("batch_*.xml")):
            for record in self._parse_pubmed_batch(batch_xml):
                metadata[str(record["nbk"])] = record  # type: ignore[index]

        for html_path in sorted(html_dir.glob("NBK*.html")):
            nbk = html_path.stem
            meta = metadata.get(nbk)
            if not meta:
                continue
            sections = self._extract_sections(html_path, meta)
            if not sections:
                continue
            url = BOOKSHELF_URL.format(nbk=nbk)
            yield ParsedDocument(
                source_doc_id=nbk,
                title=str(meta["title"]),
                sections=sections,
                citation=self.citation_template.format(
                    title=meta["title"], nbk=nbk, pmid=meta["pmid"]
                ),
                authority_tier=AuthorityTier.TEXTBOOK,
                url=url,
                license="StatPearls Publishing (personal-research use with citation)",
                metadata={
                    "pmid": meta["pmid"],
                    "nbk": nbk,
                    "authors": meta.get("authors") or [],
                },
            )

    @staticmethod
    def _extract_sections(html_path: Path, meta: dict[str, object]) -> list[Section]:
        soup = BeautifulSoup(html_path.read_text(encoding="utf-8"), "lxml")
        body_root = (
            soup.find("div", class_="body-content")
            or soup.find("div", id="maincontent")
            or soup.find("article")
            or soup
        )
        # StatPearls headings are <h2> with the section title text.
        section_titles = [str(t).strip() for t in (meta.get("section_titles") or [])]  # type: ignore[arg-type]
        nbk = html_path.stem
        out: list[Section] = []
        # Strategy: walk the body tags in order; whenever we hit an <h2> whose
        # normalized text matches one of the expected section titles, start a new
        # section and collect text until the next <h2>.
        norm_expected = {_norm(t): t for t in section_titles}
        if not norm_expected:
            return out
        active_title: str | None = None
        active_anchor: str = ""
        buf: list[str] = []
        for el in body_root.descendants:
            if isinstance(el, Tag) and el.name == "h2":
                if active_title is not None:
                    text = "\n\n".join(b for b in buf if b).strip()
                    if text:
                        out.append(
                            Section(
                                title=active_title,
                                text=text,
                                location=f"{nbk}#{active_anchor}",
                            )
                        )
                heading_text = el.get_text(separator=" ", strip=True)
                norm = _norm(heading_text)
                if norm in norm_expected:
                    active_title = norm_expected[norm]
                    raw_id = el.get("id") or ""
                    anchor = (
                        raw_id if isinstance(raw_id, str) else (raw_id[0] if raw_id else "")
                    ) or _slugify(active_title)
                    active_anchor = anchor
                    buf = []
                else:
                    active_title = None
                    buf = []
            elif active_title is not None and isinstance(el, Tag) and el.name in {
                "p",
                "li",
                "td",
                "div",
            }:
                # Collect prose text only — skip nav/ref blocks that BeautifulSoup
                # also yields. Limit to direct paragraph-class elements to reduce
                # duplication from nested descendants.
                if el.name == "p":
                    text = el.get_text(separator=" ", strip=True)
                    if text:
                        buf.append(text)
                elif el.name == "li":
                    text = el.get_text(separator=" ", strip=True)
                    if text:
                        buf.append("- " + text)
        # tail flush
        if active_title is not None:
            text = "\n\n".join(b for b in buf if b).strip()
            if text:
                out.append(
                    Section(
                        title=active_title,
                        text=text,
                        location=f"{nbk}#{active_anchor}",
                    )
                )
        return out


def _norm(text: str) -> str:
    return " ".join(text.lower().replace("/", " ").split())


def _slugify(text: str) -> str:
    import re

    return re.sub(r"[^a-z0-9]+", "-", text.lower()).strip("-") or "section"

"""PMC Open Access ingester (NCBI E-utilities).

PMC (PubMed Central) hosts full-text biomedical articles. The Open Access subset
is freely redistributable per the NIH Public Access Policy and individual
publisher licences (CC-BY, CC-BY-NC, etc.). Full XML is available via
``efetch db=pmc&rettype=xml`` — no HTML scraping needed.

PMC OA is multi-million articles, far beyond a single run. The ingester is
**query-driven**: each invocation supplies an E-utilities query (``--query``)
and writes results to ``knowledge/_local/pmc_oa/``. Run multiple queries to
build the corpus incrementally; ``chunks.jsonl`` is rebuilt each time so the
last run wins — use ``--query`` like a saved corpus slice.

Example queries:

- ``open access[filter] AND case reports[publication type]``
- ``open access[filter] AND clinical trial[publication type] AND 2024[pdat]``
- ``open access[filter] AND chest pain[mesh]``

The tool refuses to run without an explicit ``--query`` to prevent an accidental
multi-million-article download.
"""

from __future__ import annotations

import time
from collections.abc import Iterator
from pathlib import Path
from urllib.parse import quote

from lxml import etree

from tongue_doctor.knowledge.chunkers import Section
from tongue_doctor.knowledge.ingest._http import get_with_retry, http_client
from tongue_doctor.knowledge.ingest.base import BaseIngester, ParsedDocument
from tongue_doctor.knowledge.schema import AuthorityTier

EUTILS = "https://eutils.ncbi.nlm.nih.gov/entrez/eutils"
ESEARCH = EUTILS + "/esearch.fcgi?db=pmc&term={term}&retstart={start}&retmax={size}"
EFETCH = EUTILS + "/efetch.fcgi?db=pmc&id={ids}&rettype=xml"
HUMAN_URL = "https://www.ncbi.nlm.nih.gov/pmc/articles/PMC{pmcid}/"


class PmcOaIngester(BaseIngester):
    source = "pmc_oa"
    citation_template = "{title}. {journal}. PMC{pmcid}. {citation_extra}"
    notes = (
        "PMC Open Access subset; full XML via E-utilities. Query-driven; each run "
        "filters with the supplied --query and merges results into the same store."
    )

    def __init__(
        self,
        store: object,
        *,
        query: str,
        max_articles: int | None,
        polite_interval_s: float = 0.4,
        batch_size: int = 50,
    ) -> None:
        super().__init__(store)  # type: ignore[arg-type]
        if not query.strip():
            raise ValueError("PMC OA ingester requires an explicit --query")
        self.query = query
        self.max_articles = max_articles
        self.polite_interval_s = polite_interval_s
        self.batch_size = batch_size

    def fetch(self) -> None:
        raw_dir: Path = self.store.source_dir(self.source) / "raw"  # type: ignore[attr-defined]
        with http_client(timeout_s=120.0) as client:
            pmcids = self._collect_ids(client, raw_dir)
            if self.max_articles is not None:
                pmcids = pmcids[: self.max_articles]
            print(f"[pmc_oa] target articles for query={self.query!r}: {len(pmcids)}")
            self._fetch_batches(client, raw_dir, pmcids)

    def _collect_ids(self, client: object, raw_dir: Path) -> list[str]:
        cache_name = "ids_" + _slugify(self.query) + ".txt"
        cache = raw_dir / cache_name
        if cache.exists() and cache.stat().st_size > 0:
            cached = [line.strip() for line in cache.read_text().splitlines() if line.strip()]
            print(f"[pmc_oa] reusing cached id list ({len(cached)}) at {cache.name}")
            return cached
        ids: list[str] = []
        start = 0
        size = 9999
        while True:
            response = get_with_retry(
                client,  # type: ignore[arg-type]
                ESEARCH.format(term=quote(self.query), start=start, size=size),
            )
            batch = etree.fromstring(response.content).xpath("//IdList/Id/text()")
            batch = [str(b) for b in batch]
            if not batch:
                break
            ids.extend(batch)
            if len(batch) < size:
                break
            start += size
            time.sleep(self.polite_interval_s)
            if self.max_articles is not None and len(ids) >= self.max_articles:
                break
        cache.write_text("\n".join(ids) + "\n", encoding="utf-8")
        print(f"[pmc_oa] discovered {len(ids)} PMC IDs for query")
        return ids

    def _fetch_batches(self, client: object, raw_dir: Path, pmcids: list[str]) -> None:
        for batch_start in range(0, len(pmcids), self.batch_size):
            batch = pmcids[batch_start : batch_start + self.batch_size]
            cache = raw_dir / f"batch_{batch_start:07d}.xml"
            if cache.exists() and cache.stat().st_size > 0:
                continue
            try:
                response = get_with_retry(
                    client,  # type: ignore[arg-type]
                    EFETCH.format(ids=",".join(batch)),
                )
            except Exception as exc:
                print(f"[pmc_oa] skip batch {batch_start}: {exc}")
                continue
            cache.write_bytes(response.content)
            time.sleep(self.polite_interval_s)
            if (batch_start // self.batch_size) % 10 == 0:
                print(
                    f"[pmc_oa] fetched batches up to {batch_start + len(batch)}"
                )

    def parse_documents(self) -> Iterator[ParsedDocument]:
        raw_dir: Path = self.store.source_dir(self.source) / "raw"  # type: ignore[attr-defined]
        for batch_xml in sorted(raw_dir.glob("batch_*.xml")):
            try:
                tree = etree.parse(str(batch_xml))
            except etree.XMLSyntaxError as exc:
                print(f"[pmc_oa] parse-error {batch_xml.name}: {exc}")
                continue
            for article in tree.xpath("//article"):
                yield from self._documents_from_article(article)

    def _documents_from_article(
        self, article: etree._Element
    ) -> Iterator[ParsedDocument]:
        pmcid = (
            article.xpath('.//article-id[@pub-id-type="pmc"]/text()')
            or article.xpath('.//article-id[@pub-id-type="pmcid"]/text()')
            or [""]
        )[0]
        if not pmcid:
            return
        title_parts = article.xpath(".//title-group/article-title//text()")
        title = " ".join(p.strip() for p in title_parts if p.strip()) or f"PMC{pmcid}"
        journal = (article.xpath(".//journal-title/text()") or [""])[0]
        license_text = " ".join(article.xpath(".//license//text()")).strip()[:200] or "OA"
        year = (article.xpath('.//pub-date[@pub-type="epub"]/year/text()') or
                article.xpath(".//pub-date/year/text()") or [""])[0]
        authors = []
        for c in article.xpath('.//contrib[@contrib-type="author"]'):
            sn = (c.xpath(".//surname/text()") or [""])[0]
            gn = (c.xpath(".//given-names/text()") or [""])[0]
            label = ", ".join(filter(None, [sn, gn])).strip(", ")
            if label:
                authors.append(label)
        doi = (article.xpath('.//article-id[@pub-id-type="doi"]/text()') or [""])[0]

        sections: list[Section] = []
        # Abstract
        abstract = " ".join(article.xpath(".//abstract//text()")).strip()
        if abstract:
            sections.append(
                Section(
                    title="Abstract",
                    text=" ".join(abstract.split()),
                    location=f"PMC{pmcid}#abstract",
                )
            )
        # Body sections
        for sec in article.xpath('.//body//sec[@id] | .//body/sec'):
            sec_id = sec.get("id") or _slugify(
                (sec.xpath("./title/text()") or ["section"])[0]
            )
            sec_title_parts = sec.xpath("./title/text()")
            sec_title = " ".join(p.strip() for p in sec_title_parts if p.strip()) or sec_id
            sec_text_parts = sec.xpath(".//p//text()")
            sec_text = " ".join(p.strip() for p in sec_text_parts if p.strip())
            if not sec_text or len(sec_text) < 80:
                continue
            sections.append(
                Section(
                    title=sec_title,
                    text=sec_text,
                    location=f"PMC{pmcid}#{sec_id}",
                )
            )

        if not sections:
            return

        citation_extra = ", ".join(filter(None, [year, f"DOI {doi}" if doi else ""]))
        yield ParsedDocument(
            source_doc_id=f"PMC{pmcid}",
            title=title,
            sections=sections,
            citation=self.citation_template.format(
                title=title,
                journal=journal,
                pmcid=pmcid,
                citation_extra=citation_extra,
            ),
            authority_tier=AuthorityTier.CLINICAL_REFERENCE,
            url=HUMAN_URL.format(pmcid=pmcid),
            license=f"PMC OA: {license_text}",
            metadata={
                "pmcid": pmcid,
                "doi": doi,
                "journal": journal,
                "year": year,
                "authors": authors,
                "ingest_query": self.query,
            },
        )


def _slugify(text: str) -> str:
    import re

    return re.sub(r"[^a-z0-9]+", "-", text.lower()).strip("-")[:60] or "query"

"""USPSTF (US Preventive Services Task Force) ingester.

USPSTF publishes consensus screening + preventive recommendations as HTML pages,
no public JSON API. Strategy: walk paginated search listing, scrape per-topic
detail pages, extract the "Final Recommendation Statement" content under
H2/H3 anchors as separate sections.

Authority tier 1 (US government clinical guideline). Public domain (US government
work). Politely rate-limited at ≥ 1s between requests per kickoff §9.
"""

from __future__ import annotations

import re
import time
from collections.abc import Iterator
from pathlib import Path

from bs4 import BeautifulSoup, Tag

from tongue_doctor.knowledge.chunkers import Section
from tongue_doctor.knowledge.ingest._http import get_with_retry, http_client
from tongue_doctor.knowledge.ingest.base import BaseIngester, ParsedDocument
from tongue_doctor.knowledge.schema import AuthorityTier

BASE = "https://www.uspreventiveservicestaskforce.org"
DETAIL_TEMPLATE = BASE + "{slug}"

# The site's Drupal search caps each result page at 20 and ignores `page=N`.
# To enumerate the full corpus, union the A+B index, each grade-filtered search,
# and the unfiltered default. Dedupe by slug.
_LISTING_URLS = [
    BASE + "/uspstf/recommendation-topics/uspstf-a-and-b-recommendations",
    BASE + "/uspstf/topic_search_results?searchterm=",
    BASE + "/uspstf/topic_search_results?searchterm=&grades%5B%5D=A",
    BASE + "/uspstf/topic_search_results?searchterm=&grades%5B%5D=B",
    BASE + "/uspstf/topic_search_results?searchterm=&grades%5B%5D=C",
    BASE + "/uspstf/topic_search_results?searchterm=&grades%5B%5D=D",
    BASE + "/uspstf/topic_search_results?searchterm=&grades%5B%5D=I",
]

_SLUG_RE = re.compile(r"/uspstf/recommendation/[a-z0-9-]+")


class UspstfIngester(BaseIngester):
    source = "uspstf"
    citation_template = "USPSTF: {title} ({url})"
    notes = "Scraped from public HTML pages; US government work, public domain."

    def __init__(
        self,
        store: object,
        *,
        polite_interval_s: float = 1.0,
    ) -> None:
        super().__init__(store)  # type: ignore[arg-type]
        self.polite_interval_s = polite_interval_s

    def fetch(self) -> None:
        raw_dir: Path = self.store.source_dir(self.source) / "raw"  # type: ignore[attr-defined]
        slugs = self._discover_slugs(raw_dir)
        with http_client() as client:
            for slug in slugs:
                dest = raw_dir / f"{slug.rsplit('/', 1)[-1]}.html"
                if dest.exists() and dest.stat().st_size > 0:
                    continue
                url = DETAIL_TEMPLATE.format(slug=slug)
                response = get_with_retry(client, url)
                dest.write_text(response.text, encoding="utf-8")
                time.sleep(self.polite_interval_s)
        print(f"[uspstf] cached {sum(1 for _ in raw_dir.glob('*.html'))} topic pages")

    def _discover_slugs(self, raw_dir: Path) -> list[str]:
        seen: set[str] = set()
        with http_client() as client:
            for url in _LISTING_URLS:
                response = get_with_retry(client, url)
                for slug in _SLUG_RE.findall(response.text):
                    seen.add(slug)
                time.sleep(self.polite_interval_s)
        slugs = sorted(seen)
        listing_path = raw_dir / "_slugs.txt"
        listing_path.write_text("\n".join(slugs) + "\n", encoding="utf-8")
        print(f"[uspstf] discovered {len(slugs)} topic slugs across listing pages")
        return slugs

    def parse_documents(self) -> Iterator[ParsedDocument]:
        raw_dir: Path = self.store.source_dir(self.source) / "raw"  # type: ignore[attr-defined]
        for html_path in sorted(raw_dir.glob("*.html")):
            slug = html_path.stem
            url = f"{BASE}/uspstf/recommendation/{slug}"
            soup = BeautifulSoup(html_path.read_text(encoding="utf-8"), "lxml")
            title_tag = soup.find("h1", attrs={"data-qa": "extendedtitle"})
            title = title_tag.get_text(strip=True) if title_tag else slug
            sections = self._extract_sections(soup, url)
            if not sections:
                continue
            yield ParsedDocument(
                source_doc_id=slug,
                title=title,
                sections=sections,
                citation=self.citation_template.format(title=title, url=url),
                authority_tier=AuthorityTier.GUIDELINE,
                url=url,
                license="public-domain (US government work)",
                metadata={"scraped_from": url, "slug": slug},
            )

    @staticmethod
    def _extract_sections(soup: BeautifulSoup, url: str) -> list[Section]:
        """Extract H2/H3-anchored sections of the recommendation body.

        The detail-page template puts the substantive content under
        ``<h2>Final Recommendation Statement</h2>`` and following H3 subsections.
        Promotional / FAQ sidebars use distinct CSS classes — we filter those out.
        """

        sections: list[Section] = []
        for h in soup.find_all(["h2", "h3"]):
            if not isinstance(h, Tag):
                continue
            heading_text = h.get_text(strip=True)
            heading_classes = h.get("class") or []
            if not heading_text:
                continue
            if any("bcei" in c for c in heading_classes):
                continue
            if heading_text.lower() in {
                "main navigation",
                "share to facebook",
                "share to x",
                "share to whatsapp",
                "share to email",
                "print",
                "media contact",
                "newsroom",
                "frequently asked questions",
                "get the facts",
            }:
                continue
            buf: list[str] = []
            for sib in h.next_siblings:
                if isinstance(sib, Tag) and sib.name in {"h2", "h3"}:
                    break
                if isinstance(sib, Tag):
                    chunk_text = sib.get_text(separator=" ", strip=True)
                    if chunk_text:
                        buf.append(chunk_text)
            text = "\n\n".join(buf).strip()
            if len(text) < 80:
                continue
            anchor = h.get("id") or _slugify(heading_text)
            sections.append(
                Section(
                    title=heading_text,
                    text=text,
                    location=f"{url}#{anchor}",
                )
            )
        return sections


def _slugify(text: str) -> str:
    return re.sub(r"[^a-z0-9]+", "-", text.lower()).strip("-")

"""DailyMed (NLM Structured Product Labeling) ingester.

DailyMed publishes every FDA-approved drug labeling as SPL XML. Full corpus is
~80K labels; the REST API lists them paginated, and per-label XML lives at
``/dailymed/services/v2/spls/<setid>.xml``.

Sections inside an SPL are LOINC-coded (Indications, Contraindications, Dosage
and Administration, Warnings, Adverse Reactions, Drug Interactions, …) — we use
those LOINC codes verbatim for ``source_location`` so the citation points to the
exact regulatory section.

This ingester is incremental: ``--max-pages`` and ``--start-page`` let you walk
the corpus in stages without losing progress (cached XMLs survive between runs).
"""

from __future__ import annotations

import time
from collections.abc import Iterator
from pathlib import Path

from lxml import etree

from tongue_doctor.knowledge.chunkers import Section
from tongue_doctor.knowledge.ingest._http import get_with_retry, http_client
from tongue_doctor.knowledge.ingest.base import BaseIngester, ParsedDocument
from tongue_doctor.knowledge.schema import AuthorityTier

API_BASE = "https://dailymed.nlm.nih.gov/dailymed/services/v2"
LIST_URL = API_BASE + "/spls.json?pagesize={pagesize}&page={page}"
XML_URL = API_BASE + "/spls/{setid}.xml"
HUMAN_URL = "https://dailymed.nlm.nih.gov/dailymed/drugInfo.cfm?setid={setid}"

NS = {"v3": "urn:hl7-org:v3"}

# Clinically substantive sections we keep. LOINC codes per FDA SPL spec.
KEEP_LOINC = {
    "34067-9",  # Indications and Usage
    "34068-7",  # Dosage and Administration
    "34070-3",  # Contraindications
    "34071-1",  # Warnings and Precautions
    "34073-7",  # Drug Interactions
    "34072-9",  # Adverse Reactions
    "42229-5",  # SPL Patient Package Insert (skip if also have prescriber sections)
    "43377-1",  # Pharmacokinetics
    "43680-8",  # Mechanism of Action
    "34076-0",  # Pregnancy
    "34081-0",  # Description
    "34089-3",  # Clinical Studies
    "34069-5",  # Boxed Warning
}


class DailyMedIngester(BaseIngester):
    source = "dailymed"
    citation_template = "DailyMed (FDA SPL): {drug} [setid {setid}, section {loinc}]"
    notes = "FDA-approved drug labeling via DailyMed REST API; public domain."

    def __init__(
        self,
        store: object,
        *,
        pagesize: int = 100,
        start_page: int = 1,
        max_pages: int | None = None,
        polite_interval_s: float = 0.4,
    ) -> None:
        super().__init__(store)  # type: ignore[arg-type]
        self.pagesize = pagesize
        self.start_page = start_page
        self.max_pages = max_pages
        self.polite_interval_s = polite_interval_s

    def fetch(self) -> None:
        raw_dir: Path = self.store.source_dir(self.source) / "raw"  # type: ignore[attr-defined]
        with http_client(timeout_s=120.0) as client:
            page = self.start_page
            fetched = 0
            cached = 0
            while True:
                if self.max_pages is not None and page >= self.start_page + self.max_pages:
                    break
                listing = get_with_retry(
                    client, LIST_URL.format(pagesize=self.pagesize, page=page)
                ).json()
                items = listing.get("data") or []
                if not items:
                    print(f"[dailymed] page {page}: empty, stopping")
                    break
                for item in items:
                    setid = item.get("setid")
                    if not setid:
                        continue
                    xml_path = raw_dir / f"{setid}.xml"
                    if xml_path.exists() and xml_path.stat().st_size > 0:
                        cached += 1
                        continue
                    try:
                        response = get_with_retry(client, XML_URL.format(setid=setid))
                    except Exception as exc:
                        print(f"[dailymed] skip {setid}: {exc}")
                        continue
                    xml_path.write_bytes(response.content)
                    fetched += 1
                    time.sleep(self.polite_interval_s)
                print(
                    f"[dailymed] page {page}: items={len(items)} fetched_total={fetched} "
                    f"cached_total={cached}"
                )
                page += 1
        print(f"[dailymed] done: {fetched} fetched, {cached} already cached")

    def parse_documents(self) -> Iterator[ParsedDocument]:
        raw_dir: Path = self.store.source_dir(self.source) / "raw"  # type: ignore[attr-defined]
        for xml_path in sorted(raw_dir.glob("*.xml")):
            setid = xml_path.stem
            try:
                tree = etree.parse(str(xml_path))
            except etree.XMLSyntaxError as exc:
                print(f"[dailymed] parse-error {setid}: {exc}")
                continue
            root = tree.getroot()
            drug_name = self._first_text(root, ".//v3:title")
            if not drug_name:
                drug_name = self._first_text(root, ".//v3:manufacturedProduct/v3:name")
            drug_name = (drug_name or setid).strip().splitlines()[0][:200]

            sections = self._extract_sections(root, setid)
            if not sections:
                continue
            url = HUMAN_URL.format(setid=setid)
            yield ParsedDocument(
                source_doc_id=setid,
                title=drug_name,
                sections=sections,
                citation=f"DailyMed (FDA SPL): {drug_name} [setid {setid}]",
                authority_tier=AuthorityTier.CLINICAL_REFERENCE,
                url=url,
                license="public-domain (FDA submission)",
                metadata={"setid": setid},
            )

    @staticmethod
    def _first_text(element: etree._Element, xpath: str) -> str:
        result = element.xpath(xpath, namespaces=NS)
        if not result:
            return ""
        return etree.tostring(result[0], method="text", encoding="unicode").strip()

    def _extract_sections(self, root: etree._Element, setid: str) -> list[Section]:
        sections: list[Section] = []
        for section in root.iterfind(".//v3:section", NS):
            code_el = section.find("./v3:code", NS)
            if code_el is None:
                continue
            loinc = code_el.get("code") or ""
            display = code_el.get("displayName") or ""
            if loinc not in KEEP_LOINC:
                continue
            text = etree.tostring(section, method="text", encoding="unicode").strip()
            text = " ".join(text.split())  # collapse whitespace
            if len(text) < 100:
                continue
            sections.append(
                Section(
                    title=display or f"LOINC {loinc}",
                    text=text,
                    location=f"setid:{setid}/loinc:{loinc}",
                )
            )
        return sections

"""ICD-10-CM ingester (CMS canonical release).

CMS publishes one annual release as a public-domain zip. The ``order`` file is the
authoritative flat list — fixed-width columns, one row per code. Each code emits
exactly one chunk because individual codes are tiny and self-contained.

Authority is tier 2 (regulatory reference, not a guideline). Public domain (US
government work). Citation format: ``ICD-10-CM 2025: <code> — <long description>``.
"""

from __future__ import annotations

import zipfile
from collections.abc import Iterator
from pathlib import Path

from tongue_doctor.knowledge.chunkers import Section
from tongue_doctor.knowledge.ingest._http import download_to, http_client
from tongue_doctor.knowledge.ingest.base import BaseIngester, ParsedDocument
from tongue_doctor.knowledge.ingest.storage import LocalCorpusStore
from tongue_doctor.knowledge.schema import AuthorityTier

DEFAULT_URL = "https://www.cms.gov/files/zip/2025-code-descriptions-tabular-order.zip"
ORDER_FILE_NAME = "icd10cm-order-April-2025.txt"
DEFAULT_RELEASE = "2025"


class Icd10CmIngester(BaseIngester):
    source = "icd10cm"
    citation_template = "ICD-10-CM {release}: {code} - {description}"
    notes = "CMS annual release; public domain (US government work)."

    def __init__(
        self,
        store: LocalCorpusStore,
        *,
        zip_url: str = DEFAULT_URL,
        release: str = DEFAULT_RELEASE,
    ) -> None:
        super().__init__(store)
        self.zip_url = zip_url
        self.release = release

    def fetch(self) -> None:
        raw_dir = self.store.source_dir(self.source) / "raw"
        zip_path = raw_dir / f"icd10cm_{self.release}.zip"
        if zip_path.exists() and zip_path.stat().st_size > 0:
            print(f"[icd10cm] cached {zip_path.name} ({zip_path.stat().st_size} bytes)")
            return
        print(f"[icd10cm] downloading {self.zip_url} -> {zip_path}")
        with http_client() as client:
            download_to(client, self.zip_url, zip_path)
        print(f"[icd10cm] downloaded {zip_path.stat().st_size} bytes")

    def parse_documents(self) -> Iterator[ParsedDocument]:
        raw_dir = self.store.source_dir(self.source) / "raw"
        zip_path = next(raw_dir.glob("icd10cm_*.zip"))
        with zipfile.ZipFile(zip_path) as z:
            order_name = self._find_order_file(z)
            with z.open(order_name) as f:
                for raw_line in f:
                    line = raw_line.decode("utf-8", errors="replace").rstrip("\n")
                    parsed = self._parse_order_line(line)
                    if parsed is None:
                        continue
                    code, header, short_desc, long_desc = parsed
                    yield ParsedDocument(
                        source_doc_id=code,
                        title=long_desc,
                        sections=[
                            Section(
                                title=long_desc,
                                text=f"{code} - {long_desc}\n\nShort description: {short_desc}",
                                location=f"code:{code}",
                            )
                        ],
                        citation=self.citation_template.format(
                            release=self.release, code=code, description=long_desc
                        ),
                        authority_tier=AuthorityTier.CLINICAL_REFERENCE,
                        url=f"https://icd10cmtool.cdc.gov/?fy=FY{self.release}&query={code}",
                        license="public-domain (US government work)",
                        metadata={
                            "release": self.release,
                            "header_code": header == "0",
                            "short_description": short_desc,
                        },
                    )

    @staticmethod
    def _find_order_file(z: zipfile.ZipFile) -> str:
        for name in z.namelist():
            base = Path(name).name.lower()
            if base.startswith("icd10cm") and "order" in base and base.endswith(".txt"):
                return name
        raise FileNotFoundError(
            "Expected an icd10cm-order*.txt inside the CMS zip. Inspect the archive: "
            f"{z.namelist()}"
        )

    @staticmethod
    def _parse_order_line(line: str) -> tuple[str, str, str, str] | None:
        """Fixed-width parser. CMS's ``order`` file uses these column offsets:

        - cols 0-4   order number (5 chars)
        - col  6     header flag (1 char: '0' = header / category, '1' = billable)
        - cols 8-14  code (7 chars, right-padded)
        - cols 16-75 short description (60 chars, right-padded)
        - cols 77-   long description (variable, to end of line)

        See CMS readme accompanying the release.
        """

        if len(line) < 77:
            return None
        code = line[6:14].strip()
        header = line[14:16].strip()
        short_desc = line[16:77].strip()
        long_desc = line[77:].strip()
        if not code or not long_desc:
            return None
        return code, header, short_desc, long_desc

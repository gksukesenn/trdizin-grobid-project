from __future__ import annotations

from io import BytesIO
from typing import Any
from xml.etree import ElementTree

import requests

from trdizin_app.domain.models import ExtractionResult
from trdizin_app.infrastructure.external.trdizin_http_client import ExternalServiceError


class GrobidHttpClient:
    def __init__(
        self,
        base_url: str,
        connect_timeout: float = 10,
        read_timeout: float = 120,
        session: requests.Session | None = None,
    ) -> None:
        self.base_url = base_url.rstrip("/")
        self.timeout = (connect_timeout, read_timeout)
        self.session = session or requests.Session()

    def extract_references(self, pdf_content: bytes, filename: str) -> ExtractionResult:
        try:
            response = self.session.post(
                f"{self.base_url}/api/processReferences",
                files={"input": (filename, BytesIO(pdf_content), "application/pdf")},
                data={"consolidateCitations": "0", "includeRawCitations": "1"},
                timeout=self.timeout,
            )
            response.raise_for_status()
        except requests.RequestException as error:
            raise ExternalServiceError(f"GROBID isteği başarısız: {error}") from error
        tei_xml = response.text
        if not tei_xml.strip():
            raise ExternalServiceError("GROBID boş TEI XML döndürdü.")
        return ExtractionResult(
            references=self._parse_references(tei_xml),
            tei_xml=tei_xml,
        )

    @staticmethod
    def _parse_references(tei_xml: str) -> list[dict[str, Any]]:
        try:
            root = ElementTree.fromstring(tei_xml)
        except ElementTree.ParseError as error:
            raise ExternalServiceError("GROBID geçersiz TEI XML döndürdü.") from error
        ns = {"tei": "http://www.tei-c.org/ns/1.0"}
        references: list[dict[str, Any]] = []
        for index, item in enumerate(root.findall(".//tei:listBibl/tei:biblStruct", ns), 1):
            def text(path: str) -> str | None:
                node = item.find(path, ns)
                value = " ".join(node.itertext()).strip() if node is not None else ""
                return value or None
            authors = []
            for author in item.findall(".//tei:author", ns):
                name = " ".join(author.itertext()).strip()
                if name:
                    authors.append(name)
            doi = None
            for idno in item.findall(".//tei:idno", ns):
                if str(idno.attrib.get("type", "")).lower() == "doi":
                    doi = (idno.text or "").strip() or None
                    break
            raw = text("tei:note[@type='raw_reference']")
            date_node = item.find(".//tei:date", ns)
            references.append({
                "reference_index": index,
                "title": text(".//tei:title[@level='a']") or text(".//tei:title"),
                "authors": authors,
                "year": date_node.attrib.get("when") if date_node is not None else None,
                "journal": text(".//tei:title[@level='j']"),
                "doi": doi,
                "raw_reference": raw,
            })
        return references

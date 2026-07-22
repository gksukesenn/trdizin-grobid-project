from __future__ import annotations

import time
from typing import Any

from trdizin_app.application.ports.reference_extractor import ReferenceExtractor
from trdizin_app.application.ports.trdizin_gateway import TrDizinGateway


class ProcessTrDizinArticleUseCase:
    def __init__(
        self,
        gateway: TrDizinGateway,
        extractor: ReferenceExtractor,
    ) -> None:
        self.gateway = gateway
        self.extractor = extractor

    def execute(self, publication_id: int) -> dict[str, Any]:
        started = time.monotonic()
        article = self.gateway.get_article(publication_id)
        if not article.pdf_uuid:
            raise ValueError("Makalenin TR Dizin PDF kimliği bulunmuyor.")

        pdf_url = self.gateway.resolve_pdf_url(article.pdf_uuid)
        pdf_content = self.gateway.fetch_pdf(pdf_url)
        extraction = self.extractor.extract_references(
            pdf_content,
            f"{publication_id}.pdf",
        )
        duration_ms = round((time.monotonic() - started) * 1000)
        return {
            "publication_id": publication_id,
            "article": article.to_dict(),
            "processing": {
                "source": "trdizin_api",
                "extractor": "grobid",
                "reference_count": len(extraction.references),
                "duration_ms": duration_ms,
            },
            "references": extraction.references,
            "tei_xml": extraction.tei_xml,
        }

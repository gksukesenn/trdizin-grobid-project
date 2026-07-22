from __future__ import annotations

import time
from typing import Any

from trdizin_app.application.ports.reference_extractor import ReferenceExtractor
from trdizin_app.application.ports.trdizin_gateway import TrDizinGateway
from trdizin_app.application.services.reference_mapper import map_trdizin_references
from trdizin_app.application.services.reference_matcher import compare_references


class ProcessAndCompareTrDizinArticleUseCase:
    def __init__(self, gateway: TrDizinGateway, extractor: ReferenceExtractor) -> None:
        self.gateway = gateway
        self.extractor = extractor

    def execute(self, publication_id: int) -> dict[str, Any]:
        started = time.monotonic()
        article = self.gateway.get_article(publication_id)
        if not article.pdf_uuid:
            raise ValueError("Makalenin TR Dizin PDF kimliği bulunmuyor.")
        tr_refs = [ref.to_dict() for ref in map_trdizin_references(article)]
        pdf_url = self.gateway.resolve_pdf_url(article.pdf_uuid)
        extraction = self.extractor.extract_references(
            self.gateway.fetch_pdf(pdf_url), f"{publication_id}.pdf"
        )
        gr_refs = extraction.references
        comparison = compare_references(tr_refs, gr_refs)
        matched = len(comparison["matches"])
        return {
            "publication_id": publication_id,
            "article": article.to_dict(),
            "processing": {
                "source": "trdizin_api",
                "extractor": "grobid",
                "duration_ms": round((time.monotonic() - started) * 1000),
                "trdizin_reference_count": len(tr_refs),
                "grobid_reference_count": len(gr_refs),
                "matched_count": matched,
                "unmatched_trdizin_count": len(comparison["unmatched_trdizin"]),
                "unmatched_grobid_count": len(comparison["unmatched_grobid"]),
            },
            "trdizin_references": tr_refs,
            "grobid_references": gr_refs,
            "comparison": comparison,
            "tei_xml": extraction.tei_xml,
        }

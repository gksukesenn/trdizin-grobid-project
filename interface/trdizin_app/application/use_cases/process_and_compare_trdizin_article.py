import logging
import time
from typing import Any

from trdizin_app.application.ports.persistence import (
    ProcessingResultRepository,
    RepositoryUnavailableError,
)
from trdizin_app.application.ports.reference_extractor import ReferenceExtractor
from trdizin_app.application.ports.trdizin_gateway import TrDizinGateway
from trdizin_app.application.services.reference_mapper import map_trdizin_references
from trdizin_app.application.services.reference_matcher import compare_references


LOGGER = logging.getLogger(__name__)


class ProcessAndCompareTrDizinArticleUseCase:
    def __init__(
        self,
        gateway: TrDizinGateway,
        extractor: ReferenceExtractor,
        repository: ProcessingResultRepository | None = None,
        grobid_version: str = "unknown",
        algorithm_version: str = "1",
        grobid_parameters: dict[str, Any] | None = None,
    ):
        self.gateway = gateway
        self.extractor = extractor
        self.repository = repository
        self.grobid_version = grobid_version
        self.algorithm_version = algorithm_version
        self.grobid_parameters = grobid_parameters or {
            "consolidateCitations": "0",
            "includeRawCitations": "1",
        }

    def execute(self, publication_id: int, force: bool = False) -> dict[str, Any]:
        if self.repository and not force:
            try:
                cached = self.repository.find_compatible_success(
                    publication_id,
                    self.grobid_version,
                    self.algorithm_version,
                    self.grobid_parameters,
                )
                if cached:
                    return cached
            except RepositoryUnavailableError:
                LOGGER.warning("Cache sorgusu kullanılamadı", exc_info=True)
                pass

        started = time.monotonic()
        article = self.gateway.get_article(publication_id)
        try:
            if not article.pdf_uuid:
                raise ValueError("Makalenin TR Dizin PDF kimliği bulunmuyor.")
            tr_refs = [ref.to_dict() for ref in map_trdizin_references(article)]
            pdf_url = self.gateway.resolve_pdf_url(article.pdf_uuid)
            extraction = self.extractor.extract_references(
                self.gateway.fetch_pdf(pdf_url), f"{publication_id}.pdf"
            )
            gr_refs = extraction.references
            comparison = compare_references(tr_refs, gr_refs)
            result = {
                "publication_id": publication_id,
                "article": article.to_dict(),
                "processing": {
                    "source": "trdizin_api", "extractor": "grobid",
                    "duration_ms": round((time.monotonic() - started) * 1000),
                    "trdizin_reference_count": len(tr_refs),
                    "grobid_reference_count": len(gr_refs),
                    "matched_count": len(comparison["matches"]),
                    "unmatched_trdizin_count": len(comparison["unmatched_trdizin"]),
                    "unmatched_grobid_count": len(comparison["unmatched_grobid"]),
                    "cache_hit": False, "processing_run_id": None,
                    "grobid_version": self.grobid_version,
                    "algorithm_version": self.algorithm_version,
                    "persisted": False,
                },
                "trdizin_references": tr_refs,
                "grobid_references": gr_refs,
                "comparison": comparison,
                "tei_xml": extraction.tei_xml,
            }
            if self.repository:
                try:
                    run_id = self.repository.save_success(
                        article, result, self.grobid_version,
                        self.algorithm_version, self.grobid_parameters,
                    )
                    result["processing"]["processing_run_id"] = run_id
                    result["processing"]["persisted"] = True
                except RepositoryUnavailableError:
                    LOGGER.warning("İşlem sonucu kalıcılaştırılamadı", exc_info=True)
                    pass
            return result
        except Exception as error:
            if self.repository:
                try:
                    self.repository.save_failure(
                        article, self.grobid_version, self.algorithm_version,
                        self.grobid_parameters,
                        round((time.monotonic() - started) * 1000),
                        type(error).__name__, str(error),
                    )
                except RepositoryUnavailableError:
                    LOGGER.warning("Başarısız işlem run kaydı yazılamadı", exc_info=True)
                    pass
            raise

from fastapi import APIRouter, HTTPException, Query, Request
from fastapi.responses import StreamingResponse
from starlette.background import BackgroundTask

from trdizin_app.application.use_cases.get_trdizin_article import GetTrDizinArticleUseCase
from trdizin_app.application.use_cases.get_trdizin_references import GetTrDizinReferencesUseCase
from trdizin_app.application.use_cases.process_and_compare_trdizin_article import ProcessAndCompareTrDizinArticleUseCase
from trdizin_app.application.use_cases.process_trdizin_article import ProcessTrDizinArticleUseCase
from trdizin_app.application.use_cases.search_trdizin_articles import SearchTrDizinArticlesUseCase
from trdizin_app.application.use_cases.stream_trdizin_pdf import StreamTrDizinPdfUseCase
from trdizin_app.infrastructure.config.settings import Settings
from trdizin_app.application.ports.reference_extractor import ReferenceExtractor
from trdizin_app.application.ports.trdizin_gateway import TrDizinGateway
from trdizin_app.infrastructure.external.grobid_http_client import GrobidHttpClient
from trdizin_app.infrastructure.external.trdizin_http_client import (
    ArticleNotFoundError,
    ExternalServiceError,
    TrDizinHttpClient,
)
from trdizin_app.presentation.api.schemas import (
    ArticleResponse,
    ProcessAndCompareResponse,
    ProcessResponse,
    ReferencesResponse,
    SearchResponse,
)


def create_trdizin_router(
    settings: Settings,
    gateway: TrDizinGateway | None = None,
    extractor: ReferenceExtractor | None = None,
) -> APIRouter:
    gateway = gateway or TrDizinHttpClient(
        settings.trdizin_base_url,
        settings.external_connect_timeout,
        settings.external_read_timeout,
        settings.max_pdf_bytes,
    )
    extractor = extractor or GrobidHttpClient(
        settings.grobid_base_url,
        settings.external_connect_timeout,
        settings.external_read_timeout,
    )
    search_use_case = SearchTrDizinArticlesUseCase(gateway)
    get_use_case = GetTrDizinArticleUseCase(gateway)
    process_use_case = ProcessTrDizinArticleUseCase(gateway, extractor)
    references_use_case = GetTrDizinReferencesUseCase(gateway)
    stream_pdf_use_case = StreamTrDizinPdfUseCase(gateway)
    compare_use_case = ProcessAndCompareTrDizinArticleUseCase(gateway, extractor)
    router = APIRouter(prefix="/api/trdizin/articles", tags=["TR Dizin"])

    @router.get("/search", response_model=SearchResponse)
    def search_articles(
        q: str = Query(default="", max_length=200),
        page: int = Query(default=1, ge=1),
        limit: int = Query(default=10, ge=1, le=100),
    ) -> dict:
        try:
            if limit not in {10, 20, 50, 100}:
                raise HTTPException(
                    status_code=422,
                    detail="limit yalnızca 10, 20, 50 veya 100 olabilir.",
                )
            if q.strip().isdigit():
                article = get_use_case.execute(int(q.strip()))
                return {"items": [article.to_dict()], "page": 1, "total": 1}
            result = search_use_case.execute(q.strip(), page, limit)
            return {
                "items": [article.to_dict() for article in result.items],
                "page": result.page,
                "total": result.total,
            }
        except ArticleNotFoundError as error:
            raise HTTPException(status_code=404, detail=str(error)) from error
        except ExternalServiceError as error:
            raise HTTPException(status_code=502, detail=str(error)) from error

    @router.get("/{publication_id}", response_model=ArticleResponse)
    def get_article(publication_id: int) -> dict:
        try:
            return get_use_case.execute(publication_id).to_dict()
        except ArticleNotFoundError as error:
            raise HTTPException(status_code=404, detail=str(error)) from error
        except ExternalServiceError as error:
            raise HTTPException(status_code=502, detail=str(error)) from error

    @router.post("/{publication_id}/process", response_model=ProcessResponse)
    def process_article(publication_id: int) -> dict:
        try:
            return process_use_case.execute(publication_id)
        except ArticleNotFoundError as error:
            raise HTTPException(status_code=404, detail=str(error)) from error
        except ValueError as error:
            raise HTTPException(status_code=422, detail=str(error)) from error
        except ExternalServiceError as error:
            raise HTTPException(status_code=502, detail=str(error)) from error

    @router.get("/{publication_id}/references", response_model=ReferencesResponse)
    def get_references(publication_id: int) -> dict:
        try:
            references = references_use_case.execute(publication_id)
            return {
                "publication_id": publication_id,
                "reference_count": len(references),
                "references": references,
            }
        except ArticleNotFoundError as error:
            raise HTTPException(status_code=404, detail=str(error)) from error
        except ExternalServiceError as error:
            raise HTTPException(status_code=502, detail=str(error)) from error

    @router.get("/{publication_id}/pdf")
    def stream_pdf(publication_id: int, request: Request) -> StreamingResponse:
        try:
            stream = stream_pdf_use_case.execute(publication_id, request.headers.get("range"))
            headers = {**stream.headers, "Content-Disposition": f'inline; filename="{publication_id}.pdf"'}
            return StreamingResponse(
                stream.chunks,
                status_code=stream.status_code,
                media_type="application/pdf",
                headers=headers,
                background=BackgroundTask(stream.close),
            )
        except ArticleNotFoundError as error:
            raise HTTPException(status_code=404, detail=str(error)) from error
        except ValueError as error:
            raise HTTPException(status_code=404, detail=str(error)) from error
        except ExternalServiceError as error:
            raise HTTPException(status_code=502, detail=str(error)) from error

    @router.post("/{publication_id}/process-and-compare", response_model=ProcessAndCompareResponse)
    def process_and_compare(publication_id: int) -> dict:
        try:
            return compare_use_case.execute(publication_id)
        except ArticleNotFoundError as error:
            raise HTTPException(status_code=404, detail=str(error)) from error
        except ValueError as error:
            raise HTTPException(status_code=422, detail=str(error)) from error
        except ExternalServiceError as error:
            raise HTTPException(status_code=502, detail=str(error)) from error

    return router

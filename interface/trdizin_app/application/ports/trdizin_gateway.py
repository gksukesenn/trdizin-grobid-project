from __future__ import annotations

from typing import Protocol

from trdizin_app.domain.models import Article, PdfStream, SearchResult


class TrDizinGateway(Protocol):
    def search_articles(self, query: str, page: int, limit: int) -> SearchResult: ...

    def get_article(self, publication_id: int) -> Article: ...

    def resolve_pdf_url(self, pdf_uuid: str) -> str: ...

    def fetch_pdf(self, pdf_url: str) -> bytes: ...

    def open_pdf_stream(self, pdf_url: str, range_header: str | None = None) -> PdfStream: ...

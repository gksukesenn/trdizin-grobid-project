from __future__ import annotations

from trdizin_app.application.ports.trdizin_gateway import TrDizinGateway
from trdizin_app.domain.models import SearchResult


class SearchTrDizinArticlesUseCase:
    def __init__(self, gateway: TrDizinGateway) -> None:
        self.gateway = gateway

    def execute(self, query: str, page: int, limit: int) -> SearchResult:
        return self.gateway.search_articles(query, page, limit)

from __future__ import annotations

from trdizin_app.application.ports.trdizin_gateway import TrDizinGateway
from trdizin_app.domain.models import Article


class GetTrDizinArticleUseCase:
    def __init__(self, gateway: TrDizinGateway) -> None:
        self.gateway = gateway

    def execute(self, publication_id: int) -> Article:
        return self.gateway.get_article(publication_id)

from __future__ import annotations

from trdizin_app.application.ports.trdizin_gateway import TrDizinGateway
from trdizin_app.application.services.reference_mapper import map_trdizin_references


class GetTrDizinReferencesUseCase:
    def __init__(self, gateway: TrDizinGateway) -> None:
        self.gateway = gateway

    def execute(self, publication_id: int) -> list[dict]:
        article = self.gateway.get_article(publication_id)
        return [reference.to_dict() for reference in map_trdizin_references(article)]

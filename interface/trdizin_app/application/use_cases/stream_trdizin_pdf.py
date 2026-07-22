from __future__ import annotations

from trdizin_app.application.ports.trdizin_gateway import TrDizinGateway
from trdizin_app.domain.models import PdfStream


class StreamTrDizinPdfUseCase:
    def __init__(self, gateway: TrDizinGateway) -> None:
        self.gateway = gateway

    def execute(self, publication_id: int, range_header: str | None = None) -> PdfStream:
        article = self.gateway.get_article(publication_id)
        if not article.pdf_uuid:
            raise ValueError("Makalenin TR Dizin PDF kimliği bulunmuyor.")
        url = self.gateway.resolve_pdf_url(article.pdf_uuid)
        return self.gateway.open_pdf_stream(url, range_header)

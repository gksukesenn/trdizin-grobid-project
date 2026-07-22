from __future__ import annotations

from typing import Protocol

from trdizin_app.domain.models import ExtractionResult


class ReferenceExtractor(Protocol):
    def extract_references(
        self,
        pdf_content: bytes,
        filename: str,
    ) -> ExtractionResult: ...

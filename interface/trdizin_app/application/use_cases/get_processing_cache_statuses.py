from __future__ import annotations

from typing import Any

from trdizin_app.application.ports.persistence import (
    ProcessingResultRepository,
    RepositoryUnavailableError,
)


class GetProcessingCacheStatusesUseCase:
    def __init__(
        self,
        repository: ProcessingResultRepository | None,
        grobid_version: str,
        algorithm_version: str,
        grobid_parameters: dict[str, Any] | None = None,
    ) -> None:
        self.repository = repository
        self.grobid_version = grobid_version
        self.algorithm_version = algorithm_version
        self.grobid_parameters = grobid_parameters or {
            "consolidateCitations": "0",
            "includeRawCitations": "1",
        }

    def execute(self, publication_ids: list[int]) -> dict[str, Any]:
        unique_ids = list(dict.fromkeys(publication_ids))
        empty = {str(publication_id): {"processed": False} for publication_id in unique_ids}
        if self.repository is None:
            return {"items": empty, "database_available": False}
        try:
            found = self.repository.find_compatible_success_statuses(
                unique_ids,
                self.grobid_version,
                self.algorithm_version,
                self.grobid_parameters,
            )
        except RepositoryUnavailableError:
            return {"items": empty, "database_available": False}
        return {"items": {**empty, **found}, "database_available": True}

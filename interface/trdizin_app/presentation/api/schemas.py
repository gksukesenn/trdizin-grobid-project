from typing import Any

from pydantic import BaseModel


class ArticleResponse(BaseModel):
    publication_id: int
    title: str
    doi: str | None
    year: int | None
    journal: str
    has_pdf: bool


class SearchResponse(BaseModel):
    items: list[ArticleResponse]
    page: int
    total: int


class ProcessingResponse(BaseModel):
    source: str
    extractor: str
    reference_count: int
    duration_ms: int


class ProcessResponse(BaseModel):
    publication_id: int
    article: ArticleResponse
    processing: ProcessingResponse
    references: list[dict[str, Any]]
    tei_xml: str


class ReferencesResponse(BaseModel):
    publication_id: int
    reference_count: int
    references: list[dict[str, Any]]


class CompareProcessingResponse(BaseModel):
    source: str
    extractor: str
    duration_ms: int
    trdizin_reference_count: int
    grobid_reference_count: int
    matched_count: int
    unmatched_trdizin_count: int
    unmatched_grobid_count: int
    cache_hit: bool = False
    processing_run_id: int | None = None
    grobid_version: str = "unknown"
    algorithm_version: str = "unknown"
    persisted: bool = False


class ProcessAndCompareResponse(BaseModel):
    publication_id: int
    article: ArticleResponse
    processing: CompareProcessingResponse
    trdizin_references: list[dict[str, Any]]
    grobid_references: list[dict[str, Any]]
    comparison: dict[str, Any]
    tei_xml: str

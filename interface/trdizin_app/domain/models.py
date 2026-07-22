from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Callable, Iterator


@dataclass(frozen=True)
class Article:
    publication_id: int
    title: str
    doi: str | None
    year: int | None
    journal: str
    pdf_uuid: str | None
    raw: dict[str, Any] = field(repr=False)

    def to_dict(self) -> dict[str, Any]:
        return {
            "publication_id": self.publication_id,
            "title": self.title,
            "doi": self.doi,
            "year": self.year,
            "journal": self.journal,
            "has_pdf": bool(self.pdf_uuid),
        }


@dataclass(frozen=True)
class SearchResult:
    items: list[Article]
    page: int
    total: int


@dataclass(frozen=True)
class ExtractionResult:
    references: list[dict[str, Any]]
    tei_xml: str


@dataclass(frozen=True)
class Reference:
    reference_index: int
    raw_reference: str
    title: str | None = None
    authors: list[Any] = field(default_factory=list)
    year: str | None = None
    journal: str | None = None
    volume: str | None = None
    issue: str | None = None
    pages: str | None = None
    doi: str | None = None

    def to_dict(self) -> dict[str, Any]:
        return {
            "reference_index": self.reference_index,
            "raw_reference": self.raw_reference,
            "title": self.title,
            "authors": self.authors,
            "year": self.year,
            "journal": self.journal,
            "volume": self.volume,
            "issue": self.issue,
            "pages": self.pages,
            "doi": self.doi,
        }


@dataclass
class PdfStream:
    chunks: Iterator[bytes]
    status_code: int
    headers: dict[str, str]
    close: Callable[[], None]

from __future__ import annotations

import re
from typing import Any

from trdizin_app.domain.models import Article, Reference


DOI_PATTERN = re.compile(r"\b10\.\d{4,9}/[-._;()/:A-Z0-9]+", re.IGNORECASE)
YEAR_PATTERN = re.compile(r"(?<!\d)(1[0-9]{3}|20[0-9]{2}|2100)(?!\d)")


def _text(value: Any) -> str | None:
    if value is None:
        return None
    result = re.sub(r"\s+", " ", str(value)).strip()
    return result or None


def _doi(context: str, explicit: Any = None) -> str | None:
    if explicit:
        return _text(explicit)
    normalized = re.sub(r"(?<=[-._;()/:])\s+(?=[A-Z0-9])", "", context, flags=re.I)
    normalized = re.sub(r"(?<=[A-Z0-9])\s+(?=[-._;()/:])", "", normalized, flags=re.I)
    match = DOI_PATTERN.search(normalized)
    return match.group(0).rstrip(".,;:)]}") if match else None


def map_trdizin_references(article: Article) -> list[Reference]:
    source = article.raw.get("_source", article.raw)
    raw_references = source.get("references", []) if isinstance(source, dict) else []
    if not isinstance(raw_references, list):
        return []
    result: list[Reference] = []
    used: set[int] = set()
    for fallback, value in enumerate(raw_references, 1):
        reference = value if isinstance(value, dict) else {"context": str(value)}
        try:
            index = int(reference.get("order"))
        except (TypeError, ValueError):
            index = fallback
        if index <= 0 or index in used:
            index = fallback
            while index in used:
                index += 1
        used.add(index)
        raw = _text(reference.get("context")) or ""
        raw_year = _text(reference.get("year"))
        year_match = YEAR_PATTERN.search(raw_year or raw)
        authors = reference.get("authors")
        result.append(Reference(
            reference_index=index,
            raw_reference=raw,
            title=_text(reference.get("title")),
            authors=authors if isinstance(authors, list) else ([] if authors is None else [authors]),
            year=year_match.group(1) if year_match else None,
            journal=_text(reference.get("journal") or reference.get("source") or reference.get("journalName")),
            volume=_text(reference.get("volume")),
            issue=_text(reference.get("issue")),
            pages=_text(reference.get("pages")),
            doi=_doi(raw, reference.get("doi")),
        ))
    return result

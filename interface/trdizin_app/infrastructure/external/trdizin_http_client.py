from __future__ import annotations

from typing import Any

import requests
from requests.adapters import HTTPAdapter
from urllib3.util.retry import Retry

from trdizin_app.domain.models import Article, PdfStream, SearchResult


class ExternalServiceError(RuntimeError):
    pass


class ArticleNotFoundError(LookupError):
    pass


class TrDizinHttpClient:
    def __init__(
        self,
        base_url: str,
        connect_timeout: float = 10,
        read_timeout: float = 120,
        max_pdf_bytes: int = 50 * 1024 * 1024,
        session: requests.Session | None = None,
    ) -> None:
        self.base_url = base_url.rstrip("/")
        self.timeout = (connect_timeout, read_timeout)
        self.max_pdf_bytes = max_pdf_bytes
        self.session = session or self._create_session()

    @staticmethod
    def _create_session() -> requests.Session:
        retry = Retry(
            total=2,
            connect=2,
            read=2,
            backoff_factor=0.5,
            status_forcelist=(429, 500, 502, 503, 504),
            allowed_methods=("GET",),
        )
        session = requests.Session()
        session.headers.update({
            "User-Agent": "TRDizin-Grobid-Presentation/1.0",
            "Accept": "application/json",
        })
        session.mount("https://", HTTPAdapter(max_retries=retry))
        return session

    @staticmethod
    def _article_from_record(record: dict[str, Any]) -> Article | None:
        source = record.get("_source", record)
        if not isinstance(source, dict):
            return None
        raw_id = source.get("id") or record.get("_id")
        try:
            publication_id = int(raw_id)
        except (TypeError, ValueError):
            return None
        journal = source.get("journal") or {}
        journal_name = journal.get("name", "") if isinstance(journal, dict) else ""
        raw_year = source.get("publicationYear")
        try:
            year = int(raw_year) if raw_year is not None else None
        except (TypeError, ValueError):
            year = None
        pdf_uuid = source.get("pdf")
        return Article(
            publication_id=publication_id,
            title=str(source.get("orderTitle") or source.get("title") or "").strip(),
            doi=str(source.get("doi")).strip() if source.get("doi") else None,
            year=year,
            journal=str(journal_name or "").strip(),
            pdf_uuid=str(pdf_uuid).strip() if pdf_uuid else None,
            raw=record,
        )

    def _get_json(self, path: str, **kwargs: Any) -> Any:
        try:
            response = self.session.get(
                f"{self.base_url}/{path.lstrip('/')}",
                timeout=self.timeout,
                **kwargs,
            )
            response.raise_for_status()
            return response.json()
        except (requests.RequestException, ValueError) as error:
            raise ExternalServiceError(f"TR Dizin isteği başarısız: {error}") from error

    def search_articles(self, query: str, page: int, limit: int) -> SearchResult:
        data = self._get_json(
            "api/defaultSearch/publication/",
            params={
                "q": query,
                "order": "publicationYear-DESC",
                "page": page,
                "limit": limit,
                "facet-documentType": "PAPER",
                "facet-accessType": "OPEN",
            },
        )
        hits = data.get("hits", {}) if isinstance(data, dict) else {}
        records = hits.get("hits", []) if isinstance(hits, dict) else []
        total_value = hits.get("total", 0) if isinstance(hits, dict) else 0
        if not isinstance(records, list):
            raise ExternalServiceError("TR Dizin kayıt listesi beklenen biçimde değil.")
        if isinstance(total_value, dict):
            total_value = total_value.get("value", 0)
        articles = [self._article_from_record(record) for record in records if isinstance(record, dict)]
        return SearchResult(
            items=[article for article in articles if article is not None],
            page=page,
            total=int(total_value or 0),
        )

    def get_article(self, publication_id: int) -> Article:
        data = self._get_json(f"api/publicationById/{publication_id}")
        hits = data.get("hits", {}) if isinstance(data, dict) else {}
        records = hits.get("hits", []) if isinstance(hits, dict) else []
        for record in records if isinstance(records, list) else []:
            article = self._article_from_record(record) if isinstance(record, dict) else None
            if article is not None and article.publication_id == publication_id:
                return article
        raise ArticleNotFoundError(f"TR Dizin makalesi bulunamadı: {publication_id}")

    def resolve_pdf_url(self, pdf_uuid: str) -> str:
        value = self._get_json(f"api/getFile/{pdf_uuid}", params={"showViewer": "false"})
        if not isinstance(value, str) or not value.startswith(("http://", "https://")):
            raise ExternalServiceError("TR Dizin geçerli bir PDF URL'si döndürmedi.")
        return value

    def fetch_pdf(self, pdf_url: str) -> bytes:
        try:
            with self.session.get(
                pdf_url,
                headers={"Accept": "application/pdf"},
                stream=True,
                allow_redirects=True,
                timeout=self.timeout,
            ) as response:
                response.raise_for_status()
                content = bytearray()
                for chunk in response.iter_content(64 * 1024):
                    content.extend(chunk)
                    if len(content) > self.max_pdf_bytes:
                        raise ExternalServiceError("PDF izin verilen boyut sınırını aşıyor.")
        except requests.RequestException as error:
            raise ExternalServiceError(f"TR Dizin PDF isteği başarısız: {error}") from error
        pdf = bytes(content)
        if not pdf.startswith(b"%PDF-"):
            raise ExternalServiceError("TR Dizin geçerli PDF içeriği döndürmedi.")
        return pdf

    def open_pdf_stream(self, pdf_url: str, range_header: str | None = None) -> PdfStream:
        headers = {"Accept": "application/pdf"}
        if range_header:
            headers["Range"] = range_header
        try:
            response = self.session.get(
                pdf_url,
                headers=headers,
                stream=True,
                allow_redirects=True,
                timeout=self.timeout,
            )
            if response.status_code not in {200, 206}:
                response.close()
                raise ExternalServiceError(
                    f"TR Dizin PDF isteği başarısız: HTTP {response.status_code}"
                )
            content_type = response.headers.get("Content-Type", "").lower()
            if "application/pdf" not in content_type:
                response.close()
                raise ExternalServiceError("TR Dizin geçerli PDF içeriği döndürmedi.")
            content_length = response.headers.get("Content-Length")
            if content_length and int(content_length) > self.max_pdf_bytes:
                response.close()
                raise ExternalServiceError("PDF izin verilen boyut sınırını aşıyor.")
        except (requests.RequestException, ValueError) as error:
            raise ExternalServiceError(f"TR Dizin PDF isteği başarısız: {error}") from error

        forwarded = {}
        for name in ("Content-Length", "Content-Range", "Accept-Ranges", "ETag", "Last-Modified"):
            value = response.headers.get(name)
            if value:
                forwarded[name] = value

        def chunks():
            received = 0
            try:
                for chunk in response.iter_content(64 * 1024):
                    if not chunk:
                        continue
                    received += len(chunk)
                    if received > self.max_pdf_bytes:
                        raise ExternalServiceError("PDF izin verilen boyut sınırını aşıyor.")
                    yield chunk
            finally:
                response.close()

        return PdfStream(chunks(), response.status_code, forwarded, response.close)

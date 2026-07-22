import sys
import tempfile
import unittest
from pathlib import Path


sys.path.insert(0, str(Path(__file__).parents[1] / "interface"))

from trdizin_app.application.use_cases.process_trdizin_article import (  # noqa: E402
    ProcessTrDizinArticleUseCase,
)
from fastapi import FastAPI  # noqa: E402
from fastapi.testclient import TestClient  # noqa: E402
from trdizin_app.application.services.reference_mapper import map_trdizin_references  # noqa: E402
from trdizin_app.application.services.reference_matcher import compare_references, calculate_score, normalize_reference  # noqa: E402
from trdizin_app.domain.models import Article, ExtractionResult, PdfStream  # noqa: E402
from trdizin_app.infrastructure.external.grobid_http_client import (  # noqa: E402
    GrobidHttpClient,
)
from trdizin_app.infrastructure.external.trdizin_http_client import (  # noqa: E402
    TrDizinHttpClient,
)
from trdizin_app.infrastructure.config.settings import load_settings  # noqa: E402
from trdizin_app.presentation.api.routes.trdizin import create_trdizin_router  # noqa: E402
from app import app as live_app  # noqa: E402


class FakeGateway:
    def __init__(self) -> None:
        self.pdf = b"%PDF-test"

    def get_article(self, publication_id: int) -> Article:
        return Article(publication_id, "Başlık", None, 2026, "Dergi", "uuid", {
            "_source": {"references": [
                {"order": 1, "context": "Yılmaz, A. (2024). Örnek çalışma. Dergi. doi:10.1234/example", "year": "2024"}
            ]}
        })

    def resolve_pdf_url(self, pdf_uuid: str) -> str:
        return "https://files.example/article.pdf"

    def fetch_pdf(self, pdf_url: str) -> bytes:
        return self.pdf

    def open_pdf_stream(self, pdf_url: str, range_header=None) -> PdfStream:
        self.range_header = range_header
        return PdfStream(iter([self.pdf]), 206 if range_header else 200, {
            "Content-Length": str(len(self.pdf)),
            "Content-Range": "bytes 0-8/9" if range_header else "",
            "Accept-Ranges": "bytes",
        }, lambda: None)

    def search_articles(self, query: str, page: int, limit: int):
        raise AssertionError("Numeric search must use detail, not text search")


class FakeExtractor:
    def extract_references(self, pdf_content: bytes, filename: str) -> ExtractionResult:
        self.received = (pdf_content, filename)
        return ExtractionResult([{
            "reference_index": 1,
            "raw_reference": "Yılmaz, A. (2024). Örnek çalışma. Dergi. doi:10.1234/example",
            "title": "Örnek çalışma", "authors": ["A Yılmaz"], "year": "2024",
            "journal": "Dergi", "doi": "10.1234/example",
        }], "<TEI/>")


class TrDizinFlowTests(unittest.TestCase):
    def test_live_app_health_has_no_archive_or_database_counts(self) -> None:
        response = TestClient(live_app).get("/api/health")
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json(), {"status": "ok"})

        app_source = (Path(__file__).parents[1] / "interface/app.py").read_text(
            encoding="utf-8"
        ).lower()
        settings_source = (
            Path(__file__).parents[1]
            / "interface/trdizin_app/infrastructure/config/settings.py"
        ).read_text(encoding="utf-8").lower()
        for forbidden in ("mysql", "sqlite", "data/pdfs", "grobid-output"):
            self.assertNotIn(forbidden, app_source)
            self.assertNotIn(forbidden, settings_source)

    def test_maps_real_search_fields(self) -> None:
        article = TrDizinHttpClient._article_from_record({
            "_id": "1448395",
            "_source": {
                "id": 1448395,
                "orderTitle": "Makale",
                "doi": "10.1/example",
                "publicationYear": 2026,
                "journal": {"name": "Dergi"},
                "pdf": "e83942c7-0ed6-4371-938f-dc42feb01e6b",
            },
        })
        self.assertIsNotNone(article)
        self.assertEqual(article.publication_id, 1448395)
        self.assertEqual(article.journal, "Dergi")
        self.assertTrue(article.to_dict()["has_pdf"])

    def test_process_stays_in_memory(self) -> None:
        gateway = FakeGateway()
        extractor = FakeExtractor()
        result = ProcessTrDizinArticleUseCase(gateway, extractor).execute(1448395)
        self.assertEqual(extractor.received, (gateway.pdf, "1448395.pdf"))
        self.assertEqual(result["processing"]["reference_count"], 1)
        self.assertEqual(result["tei_xml"], "<TEI/>")

    def test_parses_grobid_tei(self) -> None:
        tei = """<TEI xmlns="http://www.tei-c.org/ns/1.0"><text><back><listBibl>
        <biblStruct><analytic><title level="a">Bir kaynak</title><author><persName>
        <forename>Ayşe</forename><surname>Yılmaz</surname></persName></author></analytic>
        <monogr><title level="j">Dergi</title><imprint><date when="2024"/></imprint></monogr>
        <idno type="DOI">10.1/test</idno><note type="raw_reference">Ham kaynak</note>
        </biblStruct></listBibl></back></text></TEI>"""
        references = GrobidHttpClient._parse_references(tei)
        self.assertEqual(len(references), 1)
        self.assertEqual(references[0]["title"], "Bir kaynak")
        self.assertEqual(references[0]["year"], "2024")
        self.assertEqual(references[0]["doi"], "10.1/test")

    def test_maps_real_trdizin_references_and_empty_article(self) -> None:
        article = FakeGateway().get_article(1)
        refs = map_trdizin_references(article)
        self.assertEqual(refs[0].reference_index, 1)
        self.assertEqual(refs[0].year, "2024")
        self.assertEqual(refs[0].doi, "10.1234/example")
        empty = Article(2, "Boş", None, 2024, "D", None, {"_source": {}})
        self.assertEqual(map_trdizin_references(empty), [])

    def test_in_memory_matching_and_legacy_golden_master(self) -> None:
        raw = "Yılmaz, A. (2024). Örnek çalışma. Dergi. doi:10.1234/example"
        tr = {"reference_index": 1, "raw_reference": raw, "year": "2024", "doi": "10.1234/example"}
        gr = {"reference_index": 1, "raw_reference": raw, "year": "2024", "doi": "https://doi.org/10.1234/example"}
        result = compare_references([tr], [gr])
        self.assertEqual(result["matches"][0]["status"], "exact_match")
        prepared = {"normalized": normalize_reference(raw), "year": "2024"}
        self.assertEqual(calculate_score(prepared, prepared), 100.0)

    def test_pdf_stream_range_and_no_disk_write(self) -> None:
        gateway = FakeGateway()
        before = set(Path(tempfile.gettempdir()).glob("*.pdf"))
        stream = gateway.open_pdf_stream("https://example/pdf", "bytes=0-8")
        self.assertEqual(stream.status_code, 206)
        self.assertEqual(gateway.range_header, "bytes=0-8")
        self.assertEqual(b"".join(stream.chunks), gateway.pdf)
        self.assertEqual(before, set(Path(tempfile.gettempdir()).glob("*.pdf")))

    def test_endpoints_numeric_search_range_and_process_compare_without_mysql(self) -> None:
        gateway = FakeGateway()
        app = FastAPI()
        app.include_router(create_trdizin_router(load_settings(), gateway, FakeExtractor()))
        client = TestClient(app)
        search = client.get("/api/trdizin/articles/search?q=1448395&page=7&limit=10")
        self.assertEqual(search.status_code, 200)
        self.assertEqual(search.json()["items"][0]["publication_id"], 1448395)
        refs = client.get("/api/trdizin/articles/1448395/references")
        self.assertEqual(refs.json()["reference_count"], 1)
        pdf = client.get("/api/trdizin/articles/1448395/pdf", headers={"Range": "bytes=0-8"})
        self.assertEqual(pdf.status_code, 206)
        self.assertEqual(gateway.range_header, "bytes=0-8")
        self.assertEqual(pdf.headers["content-type"], "application/pdf")
        response = client.post("/api/trdizin/articles/1448395/process-and-compare")
        self.assertEqual(response.status_code, 200)
        body = response.json()
        self.assertEqual(body["processing"]["matched_count"], 1)
        self.assertEqual(body["comparison"]["matches"][0]["status"], "exact_match")


if __name__ == "__main__":
    unittest.main()

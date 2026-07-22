import os
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parents[1] / "interface"))

from trdizin_app.domain.models import Article  # noqa: E402
from trdizin_app.infrastructure.persistence.mysql.connection import MySqlConnectionFactory  # noqa: E402
from trdizin_app.infrastructure.persistence.mysql.repositories import MySqlRepositories  # noqa: E402


@unittest.skipUnless(os.getenv("RUN_MYSQL_INTEGRATION") == "1", "temporary MySQL required")
class MySqlRepositoryIntegrationTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.repository = MySqlRepositories(MySqlConnectionFactory(
            os.environ["MYSQL_HOST"], int(os.getenv("MYSQL_PORT", "3306")),
            os.environ["MYSQL_DATABASE"], os.environ["MYSQL_USER"], os.environ["MYSQL_PASSWORD"],
        ))

    def test_article_run_references_matches_annotation_and_experiment(self):
        publication_id = 990000001
        article = Article(publication_id, "Integration", "10.test/integration", 2026,
                          "Test Journal", "test-pdf", {"_source": {"id": publication_id}})
        reference = {"reference_index": 1, "raw_reference": "Test (2026). Reference.",
                     "title": "Reference", "authors": ["Test"], "year": "2026",
                     "journal": "Test Journal", "volume": None, "issue": None,
                     "pages": None, "doi": None}
        result = {"processing": {"duration_ms": 1, "trdizin_reference_count": 1,
                  "grobid_reference_count": 1, "matched_count": 1,
                  "unmatched_trdizin_count": 0, "unmatched_grobid_count": 0},
                  "trdizin_references": [reference], "grobid_references": [reference],
                  "comparison": {"matches": [{"trdizin_index": 0, "grobid_index": 0,
                  "status": "text_match_clean", "score": 100.0}],
                  "unmatched_trdizin": [], "unmatched_grobid": []}, "tei_xml": "<TEI/>"}
        run_id = self.repository.save_success(article, result, "integration", "integration", {})
        cached = self.repository.find_compatible_success(publication_id, "integration", "integration", {})
        self.assertEqual(cached["processing"]["processing_run_id"], run_id)
        self.assertEqual(len(cached["comparison"]["matches"]), 1)
        annotation = self.repository.create_annotation(publication_id, {
            "processing_run_id": run_id, "reference_index": 1,
            "annotation_type": "raw_reference", "corrected_value": "Corrected",
            "annotator": "integration", "is_confirmed": False,
        })
        self.assertTrue(self.repository.update_annotation(annotation["id"], {"is_confirmed": True})["is_confirmed"])
        experiment = self.repository.create_experiment({
            "name": "integration", "grobid_version": "integration",
            "matcher_version": "integration", "status": "completed",
        })
        measured = self.repository.add_metric(experiment["id"], {
            "metric_name": "f1", "metric_value": 1.0, "sample_count": 1,
        })
        self.assertEqual(measured["metrics"][0]["metric_name"], "f1")


if __name__ == "__main__":
    unittest.main()

import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parents[1] / "interface"))

from fastapi import FastAPI  # noqa: E402
from fastapi.testclient import TestClient  # noqa: E402
from trdizin_app.presentation.api.routes.persistence import create_persistence_router  # noqa: E402
from trdizin_app.application.ports.persistence import RepositoryUnavailableError  # noqa: E402


class FakePersistence:
    def __init__(self):
        self.annotations = []
        self.experiments = []
        self.cache_status_calls = []

    def find_compatible_success_statuses(self, publication_ids, grobid, algorithm, parameters):
        self.cache_status_calls.append((publication_ids, grobid, algorithm, parameters))
        return {
            "1448414": {
                "processed": True, "processing_run_id": 3, "cache_hit": True,
                "grobid_version": grobid, "algorithm_version": algorithm,
                "trdizin_reference_count": 84, "grobid_reference_count": 86,
                "matched_count": 76, "unmatched_trdizin_count": 8,
                "unmatched_grobid_count": 10, "duration_ms": 3308,
            }
        }

    def list_articles(self): return []
    def list_runs(self, publication_id): return []
    def get_run(self, run_id): return None
    def get_comparison(self, run_id): return None
    def list_annotations(self, publication_id): return self.annotations
    def create_annotation(self, publication_id, data):
        value = {"id": len(self.annotations) + 1, "publication_id": publication_id, **data}
        self.annotations.append(value); return value
    def update_annotation(self, annotation_id, data):
        if not self.annotations: return None
        self.annotations[annotation_id - 1].update(data); return self.annotations[annotation_id - 1]
    def create_experiment(self, data):
        value = {"id": len(self.experiments) + 1, **data, "metrics": []}
        self.experiments.append(value); return value
    def list_experiments(self): return self.experiments
    def get_experiment(self, experiment_id):
        return self.experiments[experiment_id - 1] if 0 < experiment_id <= len(self.experiments) else None
    def add_metric(self, experiment_id, data):
        experiment = self.get_experiment(experiment_id)
        if experiment: experiment["metrics"].append(data)
        return experiment


class PersistenceApiTests(unittest.TestCase):
    def setUp(self):
        self.repository = FakePersistence()
        app = FastAPI()
        app.include_router(create_persistence_router(self.repository))
        self.client = TestClient(app)

    def test_annotation_create_and_update(self):
        created = self.client.post("/api/ground-truth/articles/1448395/annotations", json={
            "reference_index": 1, "annotation_type": "raw_reference",
            "original_value": "old", "corrected_value": "new", "annotator": "tester",
        })
        self.assertEqual(created.status_code, 201)
        updated = self.client.put("/api/ground-truth/annotations/1", json={
            "is_confirmed": True, "note": "checked",
        })
        self.assertTrue(updated.json()["is_confirmed"])
        self.assertEqual(len(self.client.get("/api/ground-truth/articles/1448395").json()["items"]), 1)

    def test_experiment_and_metric(self):
        created = self.client.post("/api/experiments", json={
            "name": "baseline", "grobid_version": "0.8.0",
            "matcher_version": "v1", "status": "running",
        })
        self.assertEqual(created.status_code, 201)
        metric = self.client.post("/api/experiments/1/metrics", json={
            "metric_name": "f1", "metric_value": 0.91, "sample_count": 100,
        })
        self.assertEqual(metric.status_code, 201)
        self.assertEqual(metric.json()["metrics"][0]["metric_name"], "f1")

    def test_disabled_persistence_returns_clear_503(self):
        app = FastAPI()
        app.include_router(create_persistence_router(None))
        response = TestClient(app).get("/api/history/articles")
        self.assertEqual(response.status_code, 503)
        self.assertEqual(response.json()["detail"], "Kalıcılık servisi kullanılamıyor.")

    def test_cache_status_uses_one_repository_call_for_all_articles(self):
        response = self.client.post("/api/history/cache-status", json={
            "publication_ids": [1448414, 1448413, 1448412],
        })
        self.assertEqual(response.status_code, 200)
        body = response.json()
        self.assertTrue(body["database_available"])
        self.assertTrue(body["items"]["1448414"]["processed"])
        self.assertFalse(body["items"]["1448413"]["processed"])
        self.assertFalse(body["items"]["1448412"]["processed"])
        self.assertEqual(len(self.repository.cache_status_calls), 1)
        self.assertEqual(
            self.repository.cache_status_calls[0][0],
            [1448414, 1448413, 1448412],
        )

    def test_cache_status_degrades_without_database(self):
        class UnavailablePersistence(FakePersistence):
            def find_compatible_success_statuses(self, *args):
                raise RepositoryUnavailableError("offline")

        app = FastAPI()
        app.include_router(create_persistence_router(UnavailablePersistence()))
        response = TestClient(app).post("/api/history/cache-status", json={
            "publication_ids": [1448414],
        })
        self.assertEqual(response.status_code, 200)
        self.assertFalse(response.json()["database_available"])
        self.assertFalse(response.json()["items"]["1448414"]["processed"])


if __name__ == "__main__":
    unittest.main()

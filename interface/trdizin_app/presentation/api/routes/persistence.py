from typing import Any, Literal

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, Field

from trdizin_app.application.ports.persistence import RepositoryUnavailableError
from trdizin_app.application.use_cases.get_processing_cache_statuses import GetProcessingCacheStatusesUseCase


class AnnotationCreate(BaseModel):
    processing_run_id: int | None = None
    reference_index: int | None = None
    extracted_reference_id: int | None = None
    annotation_type: str = Field(min_length=1, max_length=64)
    original_value: str | None = None
    corrected_value: str | None = None
    is_confirmed: bool = False
    note: str | None = None
    annotator: str = Field(min_length=1, max_length=255)


class AnnotationUpdate(BaseModel):
    corrected_value: str | None = None
    is_confirmed: bool | None = None
    note: str | None = None
    annotator: str | None = Field(default=None, min_length=1, max_length=255)


class ExperimentCreate(BaseModel):
    name: str = Field(min_length=1, max_length=255)
    description: str | None = None
    grobid_version: str = Field(min_length=1, max_length=64)
    grobid_parameters: dict[str, Any] = {}
    matcher_version: str = Field(min_length=1, max_length=64)
    dataset_name: str | None = None
    status: Literal["created", "running", "completed", "failed"] = "created"
    started_at: str | None = None
    completed_at: str | None = None


class MetricCreate(BaseModel):
    metric_name: Literal["precision", "recall", "f1"] | str
    metric_value: float
    sample_count: int | None = Field(default=None, ge=0)
    metadata: dict[str, Any] = {}


class CacheStatusRequest(BaseModel):
    publication_ids: list[int] = Field(min_length=1, max_length=100)


def create_persistence_router(repository, settings=None) -> APIRouter:
    router = APIRouter(tags=["Persistence"])
    cache_status_use_case = GetProcessingCacheStatusesUseCase(
        repository,
        settings.grobid_version if settings else "unknown",
        settings.algorithm_version if settings else "unknown",
    )

    def call(method: str, *args):
        if repository is None:
            raise HTTPException(503, "Kalıcılık servisi kullanılamıyor.")
        try:
            return getattr(repository, method)(*args)
        except RepositoryUnavailableError as error:
            raise HTTPException(503, "Kalıcılık servisi geçici olarak kullanılamıyor.") from error

    @router.get("/api/history/articles")
    def history_articles():
        return {"items": call("list_articles")}

    @router.post("/api/history/cache-status")
    def cache_status(body: CacheStatusRequest):
        return cache_status_use_case.execute(body.publication_ids)

    @router.get("/api/history/articles/{publication_id}/runs")
    def history_runs(publication_id: int):
        return {"items": call("list_runs", publication_id)}

    @router.get("/api/history/runs/{run_id}")
    def history_run(run_id: int):
        value = call("get_run", run_id)
        if value is None: raise HTTPException(404, "İşlem kaydı bulunamadı.")
        return value

    @router.get("/api/history/runs/{run_id}/comparison")
    def history_comparison(run_id: int):
        value = call("get_comparison", run_id)
        if value is None: raise HTTPException(404, "İşlem kaydı bulunamadı.")
        return value

    @router.get("/api/ground-truth/articles/{publication_id}")
    def annotations(publication_id: int):
        return {"items": call("list_annotations", publication_id)}

    @router.post("/api/ground-truth/articles/{publication_id}/annotations", status_code=201)
    def create_annotation(publication_id: int, body: AnnotationCreate):
        return call("create_annotation", publication_id, body.model_dump())

    @router.put("/api/ground-truth/annotations/{annotation_id}")
    def update_annotation(annotation_id: int, body: AnnotationUpdate):
        value = call("update_annotation", annotation_id,
                     body.model_dump(exclude_unset=True))
        if value is None: raise HTTPException(404, "Annotation bulunamadı.")
        return value

    @router.post("/api/experiments", status_code=201)
    def create_experiment(body: ExperimentCreate):
        return call("create_experiment", body.model_dump())

    @router.get("/api/experiments")
    def experiments():
        return {"items": call("list_experiments")}

    @router.get("/api/experiments/{experiment_id}")
    def experiment(experiment_id: int):
        value = call("get_experiment", experiment_id)
        if value is None: raise HTTPException(404, "Deney bulunamadı.")
        return value

    @router.post("/api/experiments/{experiment_id}/metrics", status_code=201)
    def metric(experiment_id: int, body: MetricCreate):
        value = call("add_metric", experiment_id, body.model_dump())
        if value is None: raise HTTPException(404, "Deney bulunamadı.")
        return value

    return router

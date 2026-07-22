import logging
from pathlib import Path
from typing import Any

import requests
from fastapi import FastAPI, HTTPException
from fastapi.responses import HTMLResponse

from trdizin_app.application.ports.persistence import RepositoryUnavailableError
from trdizin_app.infrastructure.config.settings import load_settings
from trdizin_app.infrastructure.persistence.mysql.connection import MySqlConnectionFactory
from trdizin_app.infrastructure.persistence.mysql.repositories import MySqlRepositories
from trdizin_app.presentation.api.routes.persistence import create_persistence_router
from trdizin_app.presentation.api.routes.trdizin import create_trdizin_router


LOGGER = logging.getLogger(__name__)
SETTINGS = load_settings()
INDEX_HTML = Path(__file__).parent / "templates" / "index.html"

repository = None
if SETTINGS.persistence_enabled:
    repository = MySqlRepositories(MySqlConnectionFactory(
        SETTINGS.mysql_host, SETTINGS.mysql_port, SETTINGS.mysql_database,
        SETTINGS.mysql_user, SETTINGS.mysql_password,
    ))

app = FastAPI(title="TR Dizin – GROBID Karşılaştırma Arayüzü", version="1.1.0")
app.include_router(create_trdizin_router(SETTINGS, repository=repository))
app.include_router(create_persistence_router(repository, SETTINGS))


@app.get("/", response_class=HTMLResponse)
def home() -> HTMLResponse:
    if not INDEX_HTML.exists():
        raise HTTPException(status_code=500, detail="Arayüz şablonu bulunamadı.")
    return HTMLResponse(INDEX_HTML.read_text(encoding="utf-8"))


@app.get("/api/health")
def health() -> dict[str, Any]:
    database = "disabled"
    if repository:
        try:
            database = "healthy" if repository.ping() else "unavailable"
        except RepositoryUnavailableError:
            LOGGER.exception("MySQL healthcheck başarısız")
            database = "unavailable"
    grobid = "unavailable"
    try:
        response = requests.get(f"{SETTINGS.grobid_base_url}/api/isalive", timeout=(2, 3))
        if response.ok and response.text.strip().lower() == "true":
            grobid = "healthy"
    except requests.RequestException:
        LOGGER.warning("GROBID healthcheck başarısız", exc_info=True)
    return {
        "status": "ok" if database in {"healthy", "disabled"} and grobid == "healthy" else "degraded",
        "grobid": grobid,
        "database": database,
        "persistence_enabled": SETTINGS.persistence_enabled,
    }

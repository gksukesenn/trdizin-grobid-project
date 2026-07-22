from pathlib import Path
from typing import Any

from fastapi import FastAPI, HTTPException
from fastapi.responses import HTMLResponse

from trdizin_app.infrastructure.config.settings import load_settings
from trdizin_app.presentation.api.routes.trdizin import create_trdizin_router


SETTINGS = load_settings()
INDEX_HTML = Path(__file__).parent / "templates" / "index.html"

app = FastAPI(
    title="TR Dizin – GROBID Karşılaştırma Arayüzü",
    version="1.0.0",
)
app.include_router(create_trdizin_router(SETTINGS))


@app.get("/", response_class=HTMLResponse)
def home() -> HTMLResponse:
    if not INDEX_HTML.exists():
        raise HTTPException(status_code=500, detail="Arayüz şablonu bulunamadı.")
    return HTMLResponse(INDEX_HTML.read_text(encoding="utf-8"))


@app.get("/api/health")
def health() -> dict[str, Any]:
    return {"status": "ok"}

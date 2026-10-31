"""FastAPI application entry point."""

from pathlib import Path

from fastapi import FastAPI
from fastapi.staticfiles import StaticFiles

from api.routes_api import router as api_router
from api.routes_web import router as web_router
from config import APP_VERSION

app = FastAPI(
    title="Metziah API",
    description="A platform for exploring Israeli supermarket data",
    version=APP_VERSION,
)

app.mount(
    "/static",
    StaticFiles(directory=str(Path(__file__).resolve().parent / "static")),
    name="static",
)

app.include_router(web_router)
app.include_router(api_router)


@app.get("/api/v1/health", tags=["Health"])
def health_check() -> dict[str, str]:
    """Return the API health status."""
    return {"status": "ok"}
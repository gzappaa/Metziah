"""FastAPI application entry point."""

import json
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from pathlib import Path
from typing import Any

from fastapi import FastAPI
from fastapi.staticfiles import StaticFiles

from api.routes_web import router as web_router

REFERENCE_DIR = Path(__file__).resolve().parents[1] / "data" / "reference"

_reference_data: dict[str, Any] | None = None


def load_json(path: Path) -> Any:
    """Load a JSON file from disk."""
    with path.open(encoding="utf-8") as file:
        return json.load(file)


def load_reference_data() -> dict[str, Any]:
    """Load and cache shopper reference data."""
    global _reference_data

    if _reference_data is None:
        _reference_data = {
            "categories": load_json(REFERENCE_DIR / "categories.json"),
            "store_products": load_json(REFERENCE_DIR / "store_products.json"),
        }

    return _reference_data


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncIterator[None]:
    """Load reference data once when the application starts."""
    app.state.reference_data = load_reference_data()
    yield


app = FastAPI(
    title="Metziah API",
    description="A platform for exploring Israeli supermarket data",
    version="0.1.0",
    lifespan=lifespan,
)

app.mount(
    "/static",
    StaticFiles(directory=str(Path(__file__).resolve().parent / "static")),
    name="static",
)

app.include_router(web_router)


@app.get("/api/v1/health", tags=["Health"])
def health_check() -> dict[str, str]:
    """Return the API health status."""
    return {"status": "ok"}
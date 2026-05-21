"""FastAPI app entrypoint for the document comparison framework."""

from __future__ import annotations

from fastapi import FastAPI

from backend.api import assets, comparisons, documents, jobs
from backend.services.registry import ensure_storage


def create_app() -> FastAPI:
    ensure_storage()
    app = FastAPI(title="Document Comparison Framework")
    app.include_router(documents.router)
    app.include_router(jobs.router)
    app.include_router(comparisons.router)
    app.include_router(assets.router)

    @app.get("/health")
    def health() -> dict[str, str]:
        return {"status": "ok"}

    return app


app = create_app()

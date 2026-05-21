"""Background regulatory indexing service."""

from __future__ import annotations

from pathlib import Path

from fastapi import BackgroundTasks, HTTPException

from backend.schemas import JobResponse
from backend.services import document_service, job_service, registry
from document_indexing.main import run_indexing_pipeline


def start_indexing_job(document_id: str, background_tasks: BackgroundTasks) -> JobResponse:
    document = document_service.get_document_or_404(document_id)
    if document["document_type"] != "regulatory":
        raise HTTPException(status_code=400, detail="Only regulatory documents can be indexed")
    if document["processing_status"] != "completed":
        raise HTTPException(status_code=400, detail="Regulatory document must be processed first")
    job = job_service.create_job("index_regulatory", document_id=document_id)
    registry.upsert_document(
        {
            **document,
            "indexing_status": "queued",
            "ready_for_comparison": "false",
            "error_message": "",
        }
    )
    background_tasks.add_task(index_regulatory_job, job.job_id, document_id)
    return job


def index_regulatory_job(job_id: str, document_id: str) -> None:
    try:
        job_service.mark_job_running(job_id)
        document = document_service.get_document_or_404(document_id)
        registry.upsert_document({**document, "indexing_status": "running", "error_message": ""})
        asset_root = Path(document["asset_root"])
        output = run_indexing_pipeline(
            pages_folder_path=asset_root / "enriched_doc" / "pages_md",
            output_folder_path=asset_root / "indexing_output",
            document_id=document_id,
        )
        document_service.update_manifest_topic_index(
            document,
            "indexing_output/topic_index.json",
        )
        registry.upsert_document(
            {
                **document,
                "indexing_status": "completed",
                "ready_for_comparison": "true",
                "error_message": "",
            }
        )
        if not Path(output.topic_index_path).exists():
            raise FileNotFoundError(f"Topic index not found after indexing: {output.topic_index_path}")
        job_service.mark_job_completed(job_id)
    except Exception as exc:
        document = registry.get_document(document_id)
        if document is not None:
            registry.upsert_document(
                {
                    **document,
                    "indexing_status": "failed",
                    "ready_for_comparison": "false",
                    "error_message": str(exc),
                }
            )
        job_service.mark_job_failed(job_id, exc)

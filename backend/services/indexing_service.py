"""Background document indexing service."""

from __future__ import annotations

from pathlib import Path
from typing import Callable

from fastapi import BackgroundTasks, HTTPException

from backend.schemas import JobResponse
from backend.services import document_service, job_event_service, job_service, registry
from document_indexing.main import run_indexing_pipeline


def start_indexing_job(document_id: str, background_tasks: BackgroundTasks) -> JobResponse:
    document = document_service.get_document_or_404(document_id)
    if document["processing_status"] != "completed":
        raise HTTPException(status_code=400, detail="Document must be processed first")
    if document["indexing_status"] in {"queued", "running"}:
        raise HTTPException(status_code=400, detail="Document indexing is already running")
    job = job_service.create_job("index_document", document_id=document_id)
    job_event_service.append_event(
        job.job_id,
        stage="document_indexing",
        step="queued",
        message=f"Queued indexing for {document_id}.",
    )
    registry.upsert_document(
        {
            **document,
            "indexing_status": "queued",
            "ready_for_comparison": "false",
            "active_job_id": job.job_id,
            "error_message": "",
        }
    )
    background_tasks.add_task(index_document_job, job.job_id, document_id)
    return job


def index_document_job(job_id: str, document_id: str) -> None:
    try:
        job_service.mark_job_running(job_id)
        run_indexing_for_document(job_id, document_id)
        job_service.mark_job_completed(job_id)
    except Exception as exc:
        document = registry.get_document(document_id)
        if document is not None:
            registry.upsert_document(
                {
                    **document,
                    "indexing_status": "failed",
                    "ready_for_comparison": "false",
                    "active_job_id": job_id,
                    "error_message": str(exc),
                }
            )
        job_event_service.append_event(
            job_id,
            stage="document_indexing",
            step="failed",
            message=str(exc),
        )
        job_service.mark_job_failed(job_id, exc)


def _event_callback(job_id: str) -> Callable[[str, str, str, int | None, int | None], None]:
    def callback(
        stage: str,
        step: str,
        message: str,
        progress_current: int | None = None,
        progress_total: int | None = None,
    ) -> None:
        job_event_service.append_event(
            job_id,
            stage=stage,
            step=step,
            message=message,
            progress_current=progress_current,
            progress_total=progress_total,
        )

    return callback


def run_indexing_for_document(job_id: str, document_id: str) -> None:
    document = document_service.get_document_or_404(document_id)
    if document["processing_status"] != "completed":
        raise HTTPException(status_code=400, detail="Document must be processed first")
    registry.upsert_document(
        {
            **document,
            "indexing_status": "running",
            "ready_for_comparison": "false",
            "active_job_id": job_id,
            "error_message": "",
        }
    )
    asset_root = Path(document["asset_root"])
    total_pages = len(list((asset_root / "enriched_doc" / "pages_md").glob("page_*.md")))
    job_event_service.append_event(
        job_id,
        stage="document_indexing",
        step="read_manifest",
        message="Preparing enriched pages for topic indexing.",
    )
    job_event_service.append_event(
        job_id,
        stage="document_indexing",
        step="indexing_page",
        message=f"Indexing page 0 of {total_pages}",
        progress_current=0,
        progress_total=total_pages,
    )
    output = run_indexing_pipeline(
        pages_folder_path=asset_root / "enriched_doc" / "pages_md",
        output_folder_path=asset_root / "indexing_output",
        document_id=document_id,
        event_callback=_event_callback(job_id),
    )
    job_event_service.append_event(
        job_id,
        stage="document_indexing",
        step="write_outputs",
        message="Topic indexing completed; validating output paths.",
    )
    if not Path(output.topic_index_path).exists():
        raise FileNotFoundError(f"Topic index not found after indexing: {output.topic_index_path}")
    current = document_service.get_document_or_404(document_id)
    document_service.update_manifest_topic_index(
        current,
        "indexing_output/topic_index.json",
    )
    registry.upsert_document(
        {
            **current,
            "indexing_status": "completed",
            "ready_for_comparison": "true",
            "active_job_id": job_id,
            "error_message": "",
        }
    )
    job_event_service.append_event(
        job_id,
        stage="document_indexing",
        step="completed",
        message=f"Indexed {document_id}; document is ready for comparison and co-pilot.",
    )


# Backward-compatible name for older tests or callers.
index_regulatory_job = index_document_job

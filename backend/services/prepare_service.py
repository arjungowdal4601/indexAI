"""Combined document prepare job: processing followed by indexing."""

from __future__ import annotations

from fastapi import BackgroundTasks, HTTPException

from backend.schemas import JobResponse
from backend.services import (
    document_service,
    indexing_service,
    job_event_service,
    job_service,
    processing_service,
    registry,
)


def _is_running_job(job_id: str | None) -> bool:
    if not job_id:
        return False
    row = registry.get_job(job_id)
    return bool(row and row.get("status") in {"queued", "running"})


def start_prepare_job(document_id: str, background_tasks: BackgroundTasks) -> JobResponse:
    document = document_service.get_document_or_404(document_id)
    if document.get("processing_status") in {"queued", "running"}:
        raise HTTPException(status_code=400, detail="Document processing is already running")
    if document.get("indexing_status") in {"queued", "running"}:
        raise HTTPException(status_code=400, detail="Document indexing is already running")
    if _is_running_job(document.get("active_job_id")):
        raise HTTPException(status_code=400, detail="Document prepare job is already running")
    if (
        document.get("processing_status") == "completed"
        and document.get("indexing_status") == "completed"
        and document.get("ready_for_comparison", "").lower() == "true"
    ):
        raise HTTPException(status_code=400, detail="Document is already indexed.")

    job = job_service.create_job("prepare_document", document_id=document_id)
    job_event_service.append_event(
        job.job_id,
        stage="prepare_document",
        step="queued",
        message=f"Queued prepare workflow for {document_id}.",
    )
    registry.upsert_document(
        {
            **document,
            "processing_status": (
                document["processing_status"]
                if document["processing_status"] == "completed"
                else "queued"
            ),
            "indexing_status": (
                document["indexing_status"]
                if document["indexing_status"] == "completed"
                else "not_started"
            ),
            "ready_for_comparison": "false",
            "active_job_id": job.job_id,
            "error_message": "",
        }
    )
    background_tasks.add_task(prepare_document_job, job.job_id, document_id)
    return job


def prepare_document_job(job_id: str, document_id: str) -> None:
    try:
        job_service.mark_job_running(job_id)
        job_event_service.append_event(
            job_id,
            stage="prepare_document",
            step="running",
            message=f"Started prepare workflow for {document_id}.",
        )

        document = document_service.get_document_or_404(document_id)
        if document.get("processing_status") != "completed":
            processing_service.run_processing_for_document(job_id, document_id)

        document = document_service.get_document_or_404(document_id)
        if document.get("indexing_status") != "completed":
            indexing_service.run_indexing_for_document(job_id, document_id)

        document = document_service.get_document_or_404(document_id)
        registry.upsert_document(
            {
                **document,
                "ready_for_comparison": "true",
                "active_job_id": job_id,
                "error_message": "",
            }
        )
        job_event_service.append_event(
            job_id,
            stage="prepare_document",
            step="completed",
            message=f"Prepared {document_id}; document is indexed and ready.",
        )
        job_service.mark_job_completed(job_id)
    except Exception as exc:
        document = registry.get_document(document_id)
        if document is not None:
            phase_updates = {}
            if document.get("processing_status") != "completed":
                phase_updates["processing_status"] = "failed"
            elif document.get("indexing_status") != "completed":
                phase_updates["indexing_status"] = "failed"
            registry.upsert_document(
                {
                    **document,
                    **phase_updates,
                    "ready_for_comparison": "false",
                    "active_job_id": job_id,
                    "error_message": str(exc),
                }
            )
        job_event_service.append_event(
            job_id,
            stage="prepare_document",
            step="failed",
            message=str(exc),
        )
        job_service.mark_job_failed(job_id, exc)

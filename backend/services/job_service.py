"""Backend job registry service."""

from __future__ import annotations

from fastapi import HTTPException

from backend.schemas import JobResponse
from backend.services import job_event_service, registry


def _job_response(row: dict[str, str]) -> JobResponse:
    return JobResponse(
        job_id=row["job_id"],
        job_type=row["job_type"],
        status=row["status"],
        document_id=row.get("document_id") or None,
        started_at=row.get("started_at") or None,
        finished_at=row.get("finished_at") or None,
        error_message=row.get("error_message") or None,
    )


def create_job(
    job_type: str,
    document_id: str = "",
    log_path: str = "",
) -> JobResponse:
    job_id = registry.next_job_id()
    row = {
        "job_id": job_id,
        "job_type": job_type,
        "document_id": document_id,
        "status": "queued",
        "started_at": "",
        "finished_at": "",
        "error_message": "",
        "log_path": log_path,
    }
    registry.upsert_job(row)
    job_event_service.append_event(
        job_id,
        stage=job_type,
        step="queued",
        message=f"Queued {job_type} job.",
    )
    return _job_response(row)


def get_job(job_id: str) -> JobResponse:
    row = registry.get_job(job_id)
    if row is None:
        raise HTTPException(status_code=404, detail=f"Job not found: {job_id}")
    return _job_response(row)


def update_job(job_id: str, **updates: object) -> None:
    row = registry.get_job(job_id)
    if row is None:
        raise HTTPException(status_code=404, detail=f"Job not found: {job_id}")
    registry.upsert_job({**row, **updates})


def mark_job_running(job_id: str) -> None:
    row = registry.get_job(job_id)
    job_type = row["job_type"] if row else "job"
    update_job(job_id, status="running", started_at=registry.utc_now(), error_message="")
    job_event_service.append_event(
        job_id,
        stage=job_type,
        step="running",
        message=f"Started {job_type} job.",
    )


def mark_job_completed(job_id: str) -> None:
    row = registry.get_job(job_id)
    job_type = row["job_type"] if row else "job"
    update_job(job_id, status="completed", finished_at=registry.utc_now(), error_message="")
    job_event_service.append_event(
        job_id,
        stage=job_type,
        step="completed",
        message=f"Completed {job_type} job.",
    )


def mark_job_failed(job_id: str, error: Exception) -> None:
    row = registry.get_job(job_id)
    job_type = row["job_type"] if row else "job"
    update_job(job_id, status="failed", finished_at=registry.utc_now(), error_message=str(error))
    job_event_service.append_event(
        job_id,
        stage=job_type,
        step="failed",
        message=str(error),
    )

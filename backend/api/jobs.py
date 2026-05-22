"""Job API routes."""

from __future__ import annotations

from fastapi import APIRouter

from backend.schemas import JobEventsResponse, JobResponse
from backend.services import job_event_service, job_service

router = APIRouter(prefix="/jobs", tags=["jobs"])


@router.get("/{job_id}", response_model=JobResponse)
def get_job(job_id: str) -> JobResponse:
    return job_service.get_job(job_id)


@router.get("/{job_id}/events", response_model=JobEventsResponse)
def get_job_events(job_id: str) -> JobEventsResponse:
    job_service.get_job(job_id)
    return job_event_service.read_events(job_id)

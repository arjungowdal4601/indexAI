"""Job API routes."""

from __future__ import annotations

from fastapi import APIRouter

from backend.schemas import JobResponse
from backend.services import job_service

router = APIRouter(prefix="/jobs", tags=["jobs"])


@router.get("/{job_id}", response_model=JobResponse)
def get_job(job_id: str) -> JobResponse:
    return job_service.get_job(job_id)

"""Comparison API routes."""

from __future__ import annotations

from fastapi import APIRouter, BackgroundTasks

from backend.schemas import (
    ComparisonStatusResponse,
    CreateComparisonRequest,
    CreateComparisonResponse,
)
from backend.services import comparison_service, report_service

router = APIRouter(prefix="/comparisons", tags=["comparisons"])


@router.post("", response_model=CreateComparisonResponse)
def create_comparison(
    request: CreateComparisonRequest,
    background_tasks: BackgroundTasks,
) -> CreateComparisonResponse:
    return comparison_service.create_comparison(
        regulatory_document_id=request.regulatory_document_id,
        sop_document_id=request.sop_document_id,
        background_tasks=background_tasks,
    )


@router.get("/{comparison_id}", response_model=ComparisonStatusResponse)
def get_comparison(comparison_id: str) -> ComparisonStatusResponse:
    return comparison_service.get_comparison_status(comparison_id)


@router.get("/{comparison_id}/report")
def get_report(comparison_id: str) -> dict:
    return report_service.read_comparison_report(comparison_id)


@router.get("/{comparison_id}/pages/{sop_page_number}")
def get_page_report(comparison_id: str, sop_page_number: int) -> dict:
    return report_service.read_page_report(comparison_id, sop_page_number)

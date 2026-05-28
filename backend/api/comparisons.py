"""Comparison API routes."""

from __future__ import annotations

from fastapi import APIRouter, BackgroundTasks
from fastapi.responses import FileResponse

from backend.schemas import (
    ActiveComparisonResponse,
    ComparisonListResponse,
    ComparisonProgressResponse,
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


@router.get("", response_model=ComparisonListResponse)
def list_comparisons() -> ComparisonListResponse:
    return comparison_service.list_comparisons()


@router.get("/by-pair/active", response_model=ActiveComparisonResponse)
def get_active_comparison(
    regulatory_document_id: str,
    sop_document_id: str,
) -> ActiveComparisonResponse:
    return comparison_service.get_active_comparison_for_pair(
        regulatory_document_id=regulatory_document_id,
        sop_document_id=sop_document_id,
    )


@router.get("/{comparison_id}/downloads/csv")
def download_csv_report(comparison_id: str) -> FileResponse:
    path = report_service.ensure_final_report_csv(comparison_id)
    return FileResponse(
        path,
        media_type="text/csv",
        filename=f"{comparison_id}_final_report.csv",
    )


@router.get("/{comparison_id}/downloads/thought-analysis-bundle")
def download_thought_analysis_bundle(comparison_id: str) -> FileResponse:
    path = report_service.ensure_thought_analysis_bundle(comparison_id)
    return FileResponse(
        path,
        media_type="application/json",
        filename=f"{comparison_id}_thought_analysis_bundle.json",
    )


@router.get("/{comparison_id}", response_model=ComparisonStatusResponse)
def get_comparison(comparison_id: str) -> ComparisonStatusResponse:
    return comparison_service.get_comparison_status(comparison_id)


@router.get("/{comparison_id}/progress", response_model=ComparisonProgressResponse)
def get_comparison_progress(comparison_id: str) -> ComparisonProgressResponse:
    return comparison_service.get_comparison_progress(comparison_id)


@router.get("/{comparison_id}/report")
def get_report(comparison_id: str) -> dict:
    return report_service.read_comparison_report(comparison_id)


@router.get("/{comparison_id}/pages/{sop_page_number}")
def get_page_report(comparison_id: str, sop_page_number: int) -> dict:
    return report_service.read_page_report(comparison_id, sop_page_number)

"""Document API routes."""

from __future__ import annotations

from typing import Literal

from fastapi import APIRouter, BackgroundTasks, File, Form, UploadFile

from backend.schemas import (
    CopilotQueryRequest,
    CopilotQueryResponse,
    DocumentListResponse,
    DocumentResponse,
    JobResponse,
)
from backend.services import (
    copilot_service,
    document_service,
    indexing_service,
    prepare_service,
    processing_service,
)

router = APIRouter(prefix="/documents", tags=["documents"])


@router.post("/upload", response_model=DocumentResponse)
async def upload_document(
    document_type: Literal["regulatory", "sop"] = Form(...),
    file: UploadFile = File(...),
) -> DocumentResponse:
    content = await file.read()
    return document_service.upload_document(
        document_type=document_type,
        original_filename=file.filename or "source.pdf",
        content=content,
    )


@router.get("", response_model=DocumentListResponse)
def list_documents(
    document_type: Literal["regulatory", "sop"] | None = None,
) -> DocumentListResponse:
    return DocumentListResponse(documents=document_service.list_documents(document_type))


@router.post("/{document_id}/process", response_model=JobResponse)
def process_document(
    document_id: str,
    background_tasks: BackgroundTasks,
) -> JobResponse:
    return processing_service.start_processing_job(document_id, background_tasks)


@router.post("/{document_id}/prepare", response_model=JobResponse)
def prepare_document(
    document_id: str,
    background_tasks: BackgroundTasks,
) -> JobResponse:
    return prepare_service.start_prepare_job(document_id, background_tasks)


@router.post("/{document_id}/index", response_model=JobResponse)
def index_document(
    document_id: str,
    background_tasks: BackgroundTasks,
) -> JobResponse:
    return indexing_service.start_indexing_job(document_id, background_tasks)


@router.post("/{document_id}/copilot/query", response_model=CopilotQueryResponse)
def query_document_copilot(
    document_id: str,
    request: CopilotQueryRequest,
) -> CopilotQueryResponse:
    return copilot_service.query_document_copilot(document_id, request)

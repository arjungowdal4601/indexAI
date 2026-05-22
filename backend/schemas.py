"""FastAPI request and response schemas."""

from __future__ import annotations

from typing import Any, Literal

from pydantic import BaseModel

DocumentType = Literal["regulatory", "sop"]
JobType = Literal[
    "process_document",
    "index_regulatory",
    "index_document",
    "compare_documents",
]
RegistryStatus = Literal[
    "not_started",
    "queued",
    "running",
    "completed",
    "failed",
]


class DocumentResponse(BaseModel):
    document_id: str
    document_type: DocumentType
    filename: str
    processing_status: str
    indexing_status: str
    ready_for_comparison: bool
    page_count: int | None = None
    error_message: str | None = None


class DocumentListResponse(BaseModel):
    documents: list[DocumentResponse]


class JobResponse(BaseModel):
    job_id: str
    job_type: JobType
    status: str
    document_id: str | None = None
    comparison_id: str | None = None
    started_at: str | None = None
    finished_at: str | None = None
    error_message: str | None = None


class JobEvent(BaseModel):
    timestamp: str
    job_id: str
    stage: str
    step: str
    message: str
    progress_current: int | None = None
    progress_total: int | None = None


class JobEventsResponse(BaseModel):
    job_id: str
    events: list[JobEvent]


class CreateComparisonRequest(BaseModel):
    regulatory_document_id: str
    sop_document_id: str


class CreateComparisonResponse(BaseModel):
    comparison_id: str
    job_id: str
    status: str


class ComparisonStatusResponse(BaseModel):
    comparison_id: str
    regulatory_document_id: str
    sop_document_id: str
    status: str
    report_json_path: str | None = None
    report_md_path: str | None = None
    error_message: str | None = None


class CopilotQueryRequest(BaseModel):
    query: str
    max_direct_pages: int = 10
    max_direct_estimated_tokens: int = 70000


class CopilotQueryResponse(BaseModel):
    document_id: str
    answer: dict[str, Any]
    retrieval_trace: dict[str, Any]
    routing_decision: dict[str, Any] | None = None
    selected_pages: list[int]
    estimated_context_tokens: int | None = None
    memory_mode: str | None = None
    compressed_evidence: list[dict[str, Any]] = []
    debug_steps: list[dict[str, Any]] = []

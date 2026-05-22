"""Background document processing service."""

from __future__ import annotations

from pathlib import Path

from fastapi import BackgroundTasks, HTTPException

from backend.schemas import JobResponse
from backend.services import document_service, job_event_service, job_service, registry
from doc_processing.pipeline import run_document_processing


def _count_pages(asset_root: Path) -> int:
    pages = sorted((asset_root / "enriched_doc" / "pages_md").glob("page_*.md"))
    if not pages:
        raise RuntimeError(f"No enriched page Markdown files found under {asset_root}")
    return len(pages)


def start_processing_job(document_id: str, background_tasks: BackgroundTasks) -> JobResponse:
    document = document_service.get_document_or_404(document_id)
    if document["processing_status"] == "running":
        raise HTTPException(status_code=400, detail="Document processing is already running")
    job = job_service.create_job("process_document", document_id=document_id)
    job_event_service.append_event(
        job.job_id,
        stage="document_processing",
        step="queued",
        message=f"Queued processing for {document_id}.",
    )
    registry.upsert_document(
        {
            **document,
            "processing_status": "queued",
            "ready_for_comparison": "false",
            "error_message": "",
        }
    )
    background_tasks.add_task(process_document_job, job.job_id, document_id)
    return job


def process_document_job(job_id: str, document_id: str) -> None:
    try:
        job_service.mark_job_running(job_id)
        document = document_service.get_document_or_404(document_id)
        registry.upsert_document({**document, "processing_status": "running", "error_message": ""})
        asset_root = Path(document["asset_root"])
        job_event_service.append_event(
            job_id,
            stage="document_processing",
            step="docling_conversion_started",
            message="Running document processing and enrichment.",
        )
        run_document_processing(Path(document["stored_pdf_path"]), output_root=asset_root)
        job_event_service.append_event(
            job_id,
            stage="document_processing",
            step="enrichment_started",
            message="Counting enriched page Markdown outputs.",
        )
        total_pages = _count_pages(asset_root)
        document_service.write_manifest(document, total_pages=total_pages)

        indexing_status = document.get("indexing_status") or "not_started"
        if indexing_status == "not_required":
            indexing_status = "not_started"
        ready = "true" if indexing_status == "completed" else "false"
        registry.upsert_document(
            {
                **document,
                "processing_status": "completed",
                "indexing_status": indexing_status,
                "ready_for_comparison": ready,
                "page_count": str(total_pages),
                "error_message": "",
            }
        )
        job_event_service.append_event(
            job_id,
            stage="document_processing",
            step="completed",
            message=f"Processed {total_pages} page(s). Indexing is required before comparison.",
            progress_current=total_pages,
            progress_total=total_pages,
        )
        job_service.mark_job_completed(job_id)
    except Exception as exc:
        document = registry.get_document(document_id)
        if document is not None:
            registry.upsert_document(
                {
                    **document,
                    "processing_status": "failed",
                    "ready_for_comparison": "false",
                    "error_message": str(exc),
                }
            )
        job_event_service.append_event(
            job_id,
            stage="document_processing",
            step="failed",
            message=str(exc),
        )
        job_service.mark_job_failed(job_id, exc)

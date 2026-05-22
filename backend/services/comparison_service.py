"""Comparison orchestration service."""

from __future__ import annotations

import json
from pathlib import Path

from fastapi import BackgroundTasks, HTTPException

from backend.schemas import (
    ComparisonStatusResponse,
    CreateComparisonResponse,
)
from backend.services import document_service, job_event_service, job_service, registry
from document_comparison.graph import run_document_comparison


def _ready(document: dict[str, str]) -> bool:
    return (
        document.get("processing_status") == "completed"
        and document.get("indexing_status") == "completed"
        and document.get("ready_for_comparison", "").lower() == "true"
    )


def create_comparison(
    regulatory_document_id: str,
    sop_document_id: str,
    background_tasks: BackgroundTasks,
) -> CreateComparisonResponse:
    regulatory = document_service.get_document_or_404(regulatory_document_id)
    sop = document_service.get_document_or_404(sop_document_id)
    if regulatory["document_type"] != "regulatory":
        raise HTTPException(status_code=400, detail="regulatory_document_id must reference a regulatory document")
    if sop["document_type"] != "sop":
        raise HTTPException(status_code=400, detail="sop_document_id must reference an SOP document")
    if not _ready(regulatory):
        raise HTTPException(status_code=400, detail="Regulatory document is not ready for comparison")
    if not _ready(sop):
        raise HTTPException(status_code=400, detail="SOP document is not ready for comparison")

    comparison_id = registry.next_comparison_id()
    run_dir = registry.comparison_root(comparison_id)
    (run_dir / "logs").mkdir(parents=True, exist_ok=True)
    request_path = run_dir / "comparison_request.json"
    request_path.write_text(
        json.dumps(
            {
                "comparison_id": comparison_id,
                "regulatory_document_id": regulatory_document_id,
                "sop_document_id": sop_document_id,
                "created_at": registry.utc_now(),
            },
            indent=2,
        )
        + "\n",
        encoding="utf-8",
    )

    registry.upsert_comparison(
        {
            "comparison_id": comparison_id,
            "regulatory_document_id": regulatory_document_id,
            "sop_document_id": sop_document_id,
            "status": "queued",
            "created_at": registry.utc_now(),
            "started_at": "",
            "finished_at": "",
            "report_json_path": "",
            "report_md_path": "",
            "error_message": "",
        }
    )
    job = job_service.create_job(
        "compare_documents",
        comparison_id=comparison_id,
        log_path=str(run_dir / "logs" / "run_log.csv"),
    )
    job_event_service.append_event(
        job.job_id,
        stage="comparison",
        step="queued",
        message=f"Queued comparison {comparison_id}.",
    )
    background_tasks.add_task(compare_documents_job, job.job_id, comparison_id)
    return CreateComparisonResponse(comparison_id=comparison_id, job_id=job.job_id, status="queued")


def compare_documents_job(job_id: str, comparison_id: str) -> None:
    try:
        job_service.mark_job_running(job_id)
        comparison = get_comparison_row_or_404(comparison_id)
        registry.upsert_comparison(
            {**comparison, "status": "running", "started_at": registry.utc_now(), "error_message": ""}
        )
        regulatory = document_service.get_document_or_404(comparison["regulatory_document_id"])
        sop = document_service.get_document_or_404(comparison["sop_document_id"])
        run_dir = registry.comparison_root(comparison_id)
        job_event_service.append_event(
            job_id,
            stage="comparison",
            step="load_manifests",
            message="Loading comparison manifests.",
        )
        # SOP documents are indexed for lifecycle uniformity and co-pilot support.
        # The comparison planner intentionally uses only the regulatory topic index.
        output = run_document_comparison(
            regulatory_root=Path(regulatory["asset_root"]),
            sop_root=Path(sop["asset_root"]),
            comparison_run_dir=run_dir,
            comparison_run_id=comparison_id,
            event_callback=lambda stage, step, message, progress_current=None, progress_total=None: (
                job_event_service.append_event(
                    job_id,
                    stage=stage,
                    step=step,
                    message=message,
                    progress_current=progress_current,
                    progress_total=progress_total,
                )
            ),
        )
        registry.upsert_comparison(
            {
                **comparison,
                "status": "completed",
                "finished_at": registry.utc_now(),
                "report_json_path": str(output.gap_report_path),
                "report_md_path": str(output.markdown_report_path),
                "error_message": "",
            }
        )
        job_event_service.append_event(
            job_id,
            stage="comparison",
            step="completed",
            message=f"Comparison report generated for {comparison_id}.",
        )
        job_service.mark_job_completed(job_id)
    except Exception as exc:
        comparison = registry.get_comparison(comparison_id)
        if comparison is not None:
            registry.upsert_comparison(
                {
                    **comparison,
                    "status": "failed",
                    "finished_at": registry.utc_now(),
                    "error_message": str(exc),
                }
            )
        job_event_service.append_event(
            job_id,
            stage="comparison",
            step="failed",
            message=str(exc),
        )
        job_service.mark_job_failed(job_id, exc)


def get_comparison_row_or_404(comparison_id: str) -> dict[str, str]:
    row = registry.get_comparison(comparison_id)
    if row is None:
        raise HTTPException(status_code=404, detail=f"Comparison not found: {comparison_id}")
    return row


def _latest_comparison_job(comparison_id: str) -> dict[str, str] | None:
    jobs = [
        job
        for job in registry.read_jobs()
        if job.get("comparison_id") == comparison_id
        and job.get("job_type") == "compare_documents"
    ]
    if not jobs:
        return None
    return jobs[-1]


def _comparison_progress_message(
    step: str,
    current: int | None,
    total: int | None,
    status: str,
    fallback: str,
) -> str:
    if status == "completed":
        return "Comparison complete."
    if current is None or total is None:
        return fallback
    if step == "read_sop_page_window":
        return f"Reading SOP page {current} of {total}."
    if step == "plan_sop_page":
        return f"Planning SOP page {current} of {total}."
    if step == "read_regulatory_evidence":
        return f"Reading regulatory evidence for SOP page {current} of {total}."
    if step == "analyze_gap_item":
        return f"Analyzing SOP page {current} of {total}."
    if step == "write_page_report":
        return f"Completed SOP page {current} of {total}."
    return fallback


def _comparison_progress(comparison_id: str, status: str) -> dict[str, int | str | None]:
    job = _latest_comparison_job(comparison_id)
    if job is None:
        return {}

    events = [
        event
        for event in job_event_service.read_events(job["job_id"]).events
        if event.stage == "comparison"
    ]
    if not events:
        return {}

    latest_event = events[-1]
    page_events = [
        event
        for event in events
        if event.progress_current is not None and event.progress_total is not None
    ]
    latest_page_event = page_events[-1] if page_events else None
    current = latest_event.progress_current
    total = latest_event.progress_total
    if current is None and latest_page_event is not None:
        current = latest_page_event.progress_current
        total = latest_page_event.progress_total

    message = _comparison_progress_message(
        latest_event.step,
        current,
        total,
        status,
        latest_event.message,
    )
    return {
        "progress_message": message,
        "progress_current": current,
        "progress_total": total,
    }


def get_comparison_status(comparison_id: str) -> ComparisonStatusResponse:
    row = get_comparison_row_or_404(comparison_id)
    progress = _comparison_progress(comparison_id, row["status"])
    progress_message = progress.get("progress_message")
    progress_current = progress.get("progress_current")
    progress_total = progress.get("progress_total")
    return ComparisonStatusResponse(
        comparison_id=row["comparison_id"],
        regulatory_document_id=row["regulatory_document_id"],
        sop_document_id=row["sop_document_id"],
        status=row["status"],
        report_json_path=row.get("report_json_path") or None,
        report_md_path=row.get("report_md_path") or None,
        error_message=row.get("error_message") or None,
        progress_message=str(progress_message) if progress_message is not None else None,
        progress_current=int(progress_current) if progress_current is not None else None,
        progress_total=int(progress_total) if progress_total is not None else None,
    )

"""Comparison orchestration service."""

from __future__ import annotations

import json
from pathlib import Path
import traceback

from fastapi import BackgroundTasks, HTTPException

from backend.schemas import (
    ActiveComparisonResponse,
    ComparisonProgressEvent,
    ComparisonProgressResponse,
    ComparisonStatusResponse,
    CreateComparisonResponse,
)
from backend.services import (
    artifact_retention_service,
    document_service,
    job_event_service,
    job_service,
    registry,
)
from document_comparison.graph import run_document_comparison

ACTIVE_COMPARISON_STATUSES = {"queued", "running"}
TERMINAL_COMPARISON_STATUSES = {"completed", "failed"}


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

    existing_active = active_comparison_for_pair(regulatory_document_id, sop_document_id)
    if existing_active is not None:
        latest_job = _latest_comparison_job(existing_active["comparison_id"])
        return CreateComparisonResponse(
            comparison_id=existing_active["comparison_id"],
            job_id=latest_job["job_id"] if latest_job else "",
            status=existing_active["status"],
        )

    latest = latest_comparison_for_pair(regulatory_document_id, sop_document_id)
    if latest is not None and latest.get("status") == "failed":
        comparison_id = latest["comparison_id"]
        run_dir = registry.comparison_root(comparison_id)
        (run_dir / "logs").mkdir(parents=True, exist_ok=True)
        registry.upsert_comparison(
            {
                **latest,
                "status": "queued",
                "started_at": "",
                "finished_at": "",
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
            message=f"Queued retry for comparison {comparison_id}.",
        )
        background_tasks.add_task(compare_documents_job, job.job_id, comparison_id)
        return CreateComparisonResponse(comparison_id=comparison_id, job_id=job.job_id, status="queued")

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


def _format_exception(exc: Exception) -> str:
    return f"{type(exc).__name__}: {exc}"


def _write_error_trace(run_dir: Path, comparison_id: str, exc: Exception) -> Path:
    logs_dir = run_dir / "logs"
    logs_dir.mkdir(parents=True, exist_ok=True)
    path = logs_dir / "error_trace.txt"
    path.write_text(
        (
            f"comparison_id: {comparison_id}\n"
            f"error: {_format_exception(exc)}\n\n"
            f"{traceback.format_exc()}"
        ),
        encoding="utf-8",
    )
    return path


def _mark_comparison_state_failed(run_dir: Path, comparison_id: str) -> None:
    state_dir = run_dir / "state"
    state_dir.mkdir(parents=True, exist_ok=True)
    state_path = state_dir / "comparison_state.json"
    if state_path.exists():
        state = json.loads(state_path.read_text(encoding="utf-8"))
    else:
        state = {
            "comparison_run_id": comparison_id,
            "last_completed_sop_page": 0,
            "current_sop_page": 1,
            "completed_item_result_paths": [],
            "completed_page_result_paths": [],
        }
    state["status"] = "failed"
    state_path.write_text(json.dumps(state, indent=2) + "\n", encoding="utf-8")


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
        artifact_retention_service.cleanup_comparison_artifacts(comparison_id)
        job_event_service.append_event(
            job_id,
            stage="comparison",
            step="completed",
            message=f"Comparison report generated for {comparison_id}.",
        )
        job_service.mark_job_completed(job_id)
    except Exception as exc:
        run_dir = registry.comparison_root(comparison_id)
        error_text = _format_exception(exc)
        _mark_comparison_state_failed(run_dir, comparison_id)
        _write_error_trace(run_dir, comparison_id, exc)
        comparison = registry.get_comparison(comparison_id)
        if comparison is not None:
            registry.upsert_comparison(
                {
                    **comparison,
                    "status": "failed",
                    "finished_at": registry.utc_now(),
                    "error_message": error_text,
                }
            )
        job_event_service.append_event(
            job_id,
            stage="comparison",
            step="failed",
            message=error_text,
        )
        job_service.mark_job_failed(job_id, RuntimeError(error_text))


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


def _comparison_sort_key(row: dict[str, str]) -> tuple[int, str]:
    comparison_id = row.get("comparison_id", "")
    try:
        numeric = int(comparison_id.split("_")[-1])
    except (IndexError, ValueError):
        numeric = -1
    return (numeric, row.get("created_at", ""))


def comparisons_for_pair(
    regulatory_document_id: str,
    sop_document_id: str,
) -> list[dict[str, str]]:
    rows = [
        row
        for row in registry.read_comparisons()
        if row.get("regulatory_document_id") == regulatory_document_id
        and row.get("sop_document_id") == sop_document_id
    ]
    return sorted(rows, key=_comparison_sort_key)


def active_comparison_for_pair(
    regulatory_document_id: str,
    sop_document_id: str,
) -> dict[str, str] | None:
    active = [
        row
        for row in comparisons_for_pair(regulatory_document_id, sop_document_id)
        if row.get("status") in ACTIVE_COMPARISON_STATUSES
    ]
    return active[-1] if active else None


def latest_comparison_for_pair(
    regulatory_document_id: str,
    sop_document_id: str,
) -> dict[str, str] | None:
    rows = comparisons_for_pair(regulatory_document_id, sop_document_id)
    return rows[-1] if rows else None


def get_active_comparison_for_pair(
    regulatory_document_id: str,
    sop_document_id: str,
) -> ActiveComparisonResponse:
    active = active_comparison_for_pair(regulatory_document_id, sop_document_id)
    latest = latest_comparison_for_pair(regulatory_document_id, sop_document_id)

    if active is not None:
        return ActiveComparisonResponse(
            regulatory_document_id=regulatory_document_id,
            sop_document_id=sop_document_id,
            active_comparison_id=active["comparison_id"],
            latest_comparison_id=latest["comparison_id"] if latest else active["comparison_id"],
            status=active["status"],
            message="Active comparison is running.",
        )
    if latest is not None:
        return ActiveComparisonResponse(
            regulatory_document_id=regulatory_document_id,
            sop_document_id=sop_document_id,
            active_comparison_id=None,
            latest_comparison_id=latest["comparison_id"],
            status=latest["status"],
            message="No active comparison. Latest comparison returned.",
        )
    return ActiveComparisonResponse(
        regulatory_document_id=regulatory_document_id,
        sop_document_id=sop_document_id,
        active_comparison_id=None,
        latest_comparison_id=None,
        status=None,
        message="No comparison has been run for this document pair.",
    )


def _comparison_events_for_job(comparison_id: str) -> list:
    job = _latest_comparison_job(comparison_id)
    if job is None:
        return []
    return [
        event
        for event in job_event_service.read_events(job["job_id"]).events
        if event.stage == "comparison"
    ]


def get_comparison_progress(comparison_id: str) -> ComparisonProgressResponse:
    row = get_comparison_row_or_404(comparison_id)
    events = _comparison_events_for_job(comparison_id)
    latest_event = events[-1] if events else None
    page_events = [
        event
        for event in events
        if event.progress_current is not None and event.progress_total is not None
    ]
    latest_page_event = page_events[-1] if page_events else None

    current = latest_page_event.progress_current if latest_page_event is not None else None
    total = latest_page_event.progress_total if latest_page_event is not None else None
    message = latest_event.message if latest_event is not None else None
    current_stage = latest_event.stage if latest_event is not None else None
    current_step = latest_event.step if latest_event is not None else None

    if row["status"] == "completed":
        message = "Comparison complete."
        if total is not None:
            current = total

    progress_percent = None
    if current is not None and total:
        progress_percent = max(0.0, min(1.0, float(current) / float(total)))

    return ComparisonProgressResponse(
        comparison_id=row["comparison_id"],
        regulatory_document_id=row["regulatory_document_id"],
        sop_document_id=row["sop_document_id"],
        status=row["status"],
        current_stage=current_stage,
        current_step=current_step,
        message=message,
        progress_current=current,
        progress_total=total,
        progress_percent=progress_percent,
        report_ready=bool(row.get("report_json_path")) and row["status"] == "completed",
        report_json_path=row.get("report_json_path") or None,
        report_md_path=row.get("report_md_path") or None,
        error_message=row.get("error_message") or None,
        events=[
            ComparisonProgressEvent(
                timestamp=event.timestamp,
                stage=event.stage,
                step=event.step,
                message=event.message,
                progress_current=event.progress_current,
                progress_total=event.progress_total,
            )
            for event in events
        ],
    )


def get_comparison_status(comparison_id: str) -> ComparisonStatusResponse:
    row = get_comparison_row_or_404(comparison_id)
    progress = get_comparison_progress(comparison_id)
    return ComparisonStatusResponse(
        comparison_id=row["comparison_id"],
        regulatory_document_id=row["regulatory_document_id"],
        sop_document_id=row["sop_document_id"],
        status=row["status"],
        report_json_path=row.get("report_json_path") or None,
        report_md_path=row.get("report_md_path") or None,
        error_message=row.get("error_message") or None,
        progress_message=progress.message,
        progress_current=progress.progress_current,
        progress_total=progress.progress_total,
    )

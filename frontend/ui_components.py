"""Reusable Streamlit UI helpers."""

from __future__ import annotations

import json
from typing import Any, Callable

import streamlit as st

from frontend import api_client

STATUS_COLORS = {
    "completed": "#1b7f3a",
    "running": "#9a6700",
    "queued": "#8a5a00",
    "failed": "#b42318",
    "not_started": "#667085",
}
PROCESSING_BLUE = "#2f80ed"
INDEXING_GREEN = "#27ae60"


def _fragment(run_every: str):
    fragment = getattr(st, "fragment", None)
    if fragment is None:
        return lambda func: func
    return fragment(run_every=run_every)


def configure_page(title: str) -> None:
    st.set_page_config(page_title=title, layout="wide")
    st.title(title)


def api_base_url_input() -> str:
    default = api_client.get_api_base_url()
    value = st.sidebar.text_input("Backend API URL", value=default)
    st.sidebar.caption("Start backend with: uvicorn backend.app:app --reload")
    return value.rstrip("/")


def run_api_call(label: str, call: Callable[[], Any]) -> Any | None:
    try:
        return call()
    except api_client.ApiError as exc:
        st.error(f"{label} failed: {exc}")
        return None


def status_badge(status: str) -> str:
    color = STATUS_COLORS.get(status, "#667085")
    label = status.replace("_", " ").title()
    return (
        f"<span style='display:inline-block;padding:0.16rem 0.45rem;"
        f"border-radius:999px;background:{color};color:white;font-size:0.78rem;'>"
        f"{label}</span>"
    )


def render_status(status: str) -> None:
    st.markdown(status_badge(status), unsafe_allow_html=True)


def document_table(documents: list[dict[str, Any]]) -> list[dict[str, Any]]:
    return [
        {
            "Document ID": item["document_id"],
            "Filename": item["filename"],
            "Processing": item["processing_status"],
            "Indexing": item["indexing_status"],
            "Indexed": item["indexed"],
            "Pages": item.get("page_count") or "",
            "Active Job": item.get("active_job_id") or "",
            "Error": item.get("error_message") or "",
        }
        for item in documents
    ]


def indexed_documents(documents: list[dict[str, Any]]) -> list[dict[str, Any]]:
    return [
        item
        for item in documents
        if item.get("processing_status") == "completed" and item.get("indexed")
    ]


def document_option(document: dict[str, Any]) -> str:
    page_count = document.get("page_count")
    pages = f", {page_count} pages" if page_count else ""
    return f"{document['document_id']} - {document['filename']}{pages}"


def format_json(value: Any) -> str:
    return json.dumps(value, indent=2, ensure_ascii=False)


def latest_progress(
    events: list[dict[str, Any]],
    stage: str,
    fallback_total: int = 0,
    phase_completed: bool = False,
) -> tuple[int, int]:
    candidates = [
        event
        for event in events
        if event.get("stage") == stage
        and event.get("progress_current") is not None
        and event.get("progress_total")
    ]
    if candidates:
        last = candidates[-1]
        current = int(last["progress_current"])
        total = int(last["progress_total"])
    else:
        current = 0
        total = int(fallback_total or 0)
    if phase_completed and total:
        current = total
    return current, total


def colored_progress(label: str, current: int, total: int, color: str) -> None:
    ratio = 0 if not total else max(0, min(1, current / total))
    pct = int(ratio * 100)
    st.markdown(
        f"""
        <div style="margin: 0.35rem 0 0.8rem 0;">
          <div style="font-size: 0.85rem; font-weight: 600; margin-bottom: 0.2rem;">
            {label}: {current} / {total} pages
          </div>
          <div style="width: 100%; height: 10px; background: #2d333b; border-radius: 999px; overflow: hidden;">
            <div style="width: {pct}%; height: 10px; background: {color}; border-radius: 999px;"></div>
          </div>
        </div>
        """,
        unsafe_allow_html=True,
    )


def _event_kind(event: dict[str, Any]) -> str:
    text = f"{event.get('step', '')} {event.get('message', '')}".lower()
    if "failed" in text:
        return "failed"
    if "retry" in text:
        return "retry"
    if "waiting_for_llm" in text or "waiting for llm" in text:
        return "waiting_for_llm"
    return "normal"


def _friendly_event_message(event: dict[str, Any]) -> str:
    message = event.get("message", "")
    kind = _event_kind(event)
    if kind == "waiting_for_llm":
        return message or "Waiting for LLM response..."
    if kind == "retry":
        return message or "Retrying LLM call..."
    if kind == "failed":
        return message or "Failed."
    return message


@_fragment(run_every="2s")
def render_prepare_progress(base_url: str, document: dict[str, Any], job_id: str | None) -> None:
    if not job_id and not document.get("indexed"):
        return
    job = None
    events: list[dict[str, Any]] = []
    if job_id:
        job = run_api_call("Load prepare job", lambda: api_client.get_job(job_id, base_url))
        events_payload = run_api_call(
            "Load prepare job events",
            lambda: api_client.get_job_events(job_id, base_url),
        )
        events = events_payload.get("events", []) if events_payload else []

    fallback_total = int(document.get("page_count") or 0)
    processing_done = document.get("processing_status") == "completed"
    indexing_done = document.get("indexing_status") == "completed" or document.get("indexed")
    processing_current, processing_total = latest_progress(
        events,
        "document_processing",
        fallback_total=fallback_total,
        phase_completed=processing_done,
    )
    indexing_current, indexing_total = latest_progress(
        events,
        "document_indexing",
        fallback_total=fallback_total or processing_total,
        phase_completed=indexing_done,
    )

    if indexing_done or (job and job.get("status") == "completed"):
        st.success("Indexed")
    elif processing_done:
        st.caption("Indexing")
    else:
        st.caption("Processing")

    colored_progress("Processing", processing_current, processing_total, PROCESSING_BLUE)
    colored_progress("Indexing", indexing_current, indexing_total, INDEXING_GREEN)

    if events:
        latest = events[-1]
        latest_message = _friendly_event_message(latest)
        latest_kind = _event_kind(latest)
        if latest_kind == "retry":
            st.warning(latest_message)
        elif latest_kind == "failed":
            st.error(latest_message)
        elif latest_kind == "waiting_for_llm":
            st.info(latest_message)
        else:
            st.caption(latest_message)
    if job and job.get("status") == "failed":
        st.error(job.get("error_message") or "Prepare job failed.")


@_fragment(run_every="2s")
def render_job_monitor(base_url: str, job_id: str) -> None:
    if not job_id:
        return
    job = run_api_call("Load job", lambda: api_client.get_job(job_id, base_url))
    events_payload = run_api_call("Load job events", lambda: api_client.get_job_events(job_id, base_url))
    if not job:
        return

    events = events_payload.get("events", []) if events_payload else []
    state = "complete" if job["status"] == "completed" else "error" if job["status"] == "failed" else "running"
    label = f"Job {job_id}: {job['status'].replace('_', ' ')}"
    with st.status(label, state=state, expanded=job["status"] in {"queued", "running"}) as status:
        if events:
            last_event = events[-1]
            st.write(last_event.get("message", ""))
            current = last_event.get("progress_current")
            total = last_event.get("progress_total")
            if current is not None and total:
                st.progress(min(1.0, float(current) / float(total)))
            with st.expander("Event log", expanded=False):
                for event in events:
                    st.write(f"{event['timestamp']} - {event['step']}: {event['message']}")
        else:
            st.write("Waiting for job events.")

        if job["status"] == "completed":
            status.update(label=f"Job {job_id}: completed", state="complete")
        elif job["status"] == "failed":
            status.update(label=f"Job {job_id}: failed", state="error")
            if job.get("error_message"):
                st.error(job["error_message"])
        else:
            status.update(label=label, state="running")

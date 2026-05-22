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
    "compliant": "#1b7f3a",
    "partial": "#9a6700",
    "partially_compliant": "#9a6700",
    "major_gaps": "#b42318",
    "missing": "#b42318",
    "conflicting": "#b42318",
    "needs_human_review": "#6941c6",
    "not_applicable": "#667085",
}


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
            "Type": item["document_type"],
            "Filename": item["filename"],
            "Processing": item["processing_status"],
            "Indexing": item["indexing_status"],
            "Ready": item["ready_for_comparison"],
            "Pages": item.get("page_count") or "",
            "Error": item.get("error_message") or "",
        }
        for item in documents
    ]


def ready_documents(documents: list[dict[str, Any]]) -> list[dict[str, Any]]:
    return [item for item in documents if item.get("ready_for_comparison")]


def indexed_documents(documents: list[dict[str, Any]]) -> list[dict[str, Any]]:
    return [
        item
        for item in documents
        if item.get("processing_status") == "completed"
        and item.get("indexing_status") == "completed"
    ]


def document_option(document: dict[str, Any]) -> str:
    page_count = document.get("page_count")
    pages = f", {page_count} pages" if page_count else ""
    return f"{document['document_id']} - {document['filename']}{pages}"


def page_numbers_from_report(report: dict[str, Any]) -> list[int]:
    page_results = report.get("page_results") or report.get("page_reports") or []
    pages = []
    for item in page_results:
        page = item.get("sop_page")
        if page is not None:
            pages.append(int(page))
    return sorted(set(pages))


def report_summary(report: dict[str, Any]) -> dict[str, Any]:
    return report.get("summary") or report.get("counts") or {}


def format_json(value: Any) -> str:
    return json.dumps(value, indent=2, ensure_ascii=False)


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

"""Upload, process, and index one document at a time."""

from __future__ import annotations

import streamlit as st

from frontend import api_client
from frontend.ui_components import (
    api_base_url_input,
    configure_page,
    document_table,
    render_prepare_progress,
    run_api_call,
)


def upload_panel(base_url: str) -> None:
    st.subheader("Document Upload")
    uploaded = st.file_uploader(
        "Upload PDF",
        type=["pdf"],
        key="upload-document",
    )
    if st.button("Upload Document", key="upload-button-document", disabled=uploaded is None):
        result = run_api_call(
            "Upload document",
            lambda: api_client.upload_document(
                filename=uploaded.name,
                content=uploaded.getvalue(),
                base_url=base_url,
            ),
        )
        if result:
            st.success(f"Uploaded {result['document_id']}")
            st.rerun()


def render_document_actions(document: dict, base_url: str) -> None:
    st.session_state.setdefault("document_jobs", {})
    cols = st.columns([2, 2, 2, 2, 3])
    cols[0].write(document["document_id"])
    cols[1].write(document["processing_status"])
    cols[2].write(document["indexing_status"])
    cols[3].write("Indexed" if document.get("indexed") else "Not indexed")
    with cols[4]:
        running = (
            document["processing_status"] in {"queued", "running"}
            or document["indexing_status"] in {"queued", "running"}
        )
        ready = bool(document.get("indexed"))
        failed = (
            document["processing_status"] == "failed"
            or document["indexing_status"] == "failed"
        )
        if ready:
            st.write("Indexed")
        else:
            label = "Retry Index" if failed else "Index"
            if st.button(label, key=f"prepare-{document['document_id']}", disabled=running):
                job = run_api_call(
                    "Start indexing",
                    lambda: api_client.start_prepare(document["document_id"], base_url),
                )
                if job:
                    st.session_state["document_jobs"][document["document_id"]] = job["job_id"]
                    st.success(f"Index job queued: {job['job_id']}")
                    st.rerun()
    job_id = (
        st.session_state["document_jobs"].get(document["document_id"])
        or document.get("active_job_id")
    )
    render_prepare_progress(base_url, document, job_id)


def document_list(base_url: str) -> None:
    result = run_api_call(
        "Load documents",
        lambda: api_client.list_documents(base_url),
    )
    documents = result.get("documents", []) if result else []
    if documents:
        st.dataframe(document_table(documents), width="stretch", hide_index=True)
        st.caption("Actions")
        for document in documents:
            render_document_actions(document, base_url)
    else:
        st.info("No documents uploaded yet.")


def main() -> None:
    configure_page("Upload and Index")
    base_url = api_base_url_input()

    upload_panel(base_url)
    document_list(base_url)


if __name__ == "__main__":
    main()

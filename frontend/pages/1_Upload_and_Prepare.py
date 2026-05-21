"""Upload, process, and index documents."""

from __future__ import annotations

import streamlit as st

from frontend import api_client
from frontend.ui_components import (
    api_base_url_input,
    configure_page,
    document_table,
    run_api_call,
)


def upload_panel(document_type: str, base_url: str) -> None:
    title = "Regulatory Documents" if document_type == "regulatory" else "SOP Documents"
    st.subheader(title)
    uploaded = st.file_uploader(
        f"Upload {document_type} PDF",
        type=["pdf"],
        key=f"upload-{document_type}",
    )
    if st.button(f"Upload {title[:-1]}", key=f"upload-button-{document_type}", disabled=uploaded is None):
        result = run_api_call(
            "Upload document",
            lambda: api_client.upload_document(
                document_type=document_type,
                filename=uploaded.name,
                content=uploaded.getvalue(),
                base_url=base_url,
            ),
        )
        if result:
            st.success(f"Uploaded {result['document_id']}")
            st.rerun()


def render_document_actions(document: dict, base_url: str) -> None:
    cols = st.columns([2, 2, 2, 3])
    cols[0].write(document["document_id"])
    cols[1].write(document["processing_status"])
    cols[2].write(document["indexing_status"])
    with cols[3]:
        process_disabled = document["processing_status"] in {"queued", "running"}
        if st.button("Process", key=f"process-{document['document_id']}", disabled=process_disabled):
            job = run_api_call(
                "Start processing",
                lambda: api_client.start_processing(document["document_id"], base_url),
            )
            if job:
                st.session_state["last_job_id"] = job["job_id"]
                st.success(f"Processing job queued: {job['job_id']}")
                st.rerun()
        if document["document_type"] == "regulatory":
            index_disabled = (
                document["processing_status"] != "completed"
                or document["indexing_status"] in {"queued", "running", "completed"}
            )
            if st.button("Index", key=f"index-{document['document_id']}", disabled=index_disabled):
                job = run_api_call(
                    "Start indexing",
                    lambda: api_client.start_indexing(document["document_id"], base_url),
                )
                if job:
                    st.session_state["last_job_id"] = job["job_id"]
                    st.success(f"Indexing job queued: {job['job_id']}")
                    st.rerun()


def document_list(document_type: str, base_url: str) -> None:
    result = run_api_call(
        "Load documents",
        lambda: api_client.list_documents(document_type, base_url),
    )
    documents = result.get("documents", []) if result else []
    if documents:
        st.dataframe(document_table(documents), width="stretch", hide_index=True)
        st.caption("Actions")
        for document in documents:
            render_document_actions(document, base_url)
    else:
        st.info(f"No {document_type} documents uploaded yet.")


def main() -> None:
    configure_page("Upload and Prepare")
    base_url = api_base_url_input()

    left, right = st.columns(2)
    with left:
        upload_panel("regulatory", base_url)
        document_list("regulatory", base_url)
    with right:
        upload_panel("sop", base_url)
        document_list("sop", base_url)

    st.divider()
    st.subheader("Job Status")
    last_job = st.session_state.get("last_job_id", "")
    job_id = st.text_input("Job ID", value=last_job)
    if st.button("Refresh job", disabled=not job_id):
        job = run_api_call("Load job", lambda: api_client.get_job(job_id, base_url))
        if job:
            st.json(job)


if __name__ == "__main__":
    main()

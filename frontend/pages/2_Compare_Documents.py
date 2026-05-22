"""Run SOP-vs-regulatory comparisons."""

from __future__ import annotations

import streamlit as st

from frontend import api_client
from frontend.ui_components import (
    api_base_url_input,
    configure_page,
    document_option,
    render_job_monitor,
    ready_documents,
    run_api_call,
)


def main() -> None:
    configure_page("Compare Documents")
    base_url = api_base_url_input()

    regulatory_response = run_api_call(
        "Load regulatory documents",
        lambda: api_client.list_documents("regulatory", base_url),
    )
    sop_response = run_api_call(
        "Load SOP documents",
        lambda: api_client.list_documents("sop", base_url),
    )
    regulatory_docs = ready_documents(regulatory_response.get("documents", []) if regulatory_response else [])
    sop_docs = ready_documents(sop_response.get("documents", []) if sop_response else [])

    left, right = st.columns(2)
    with left:
        st.subheader("Regulatory")
        selected_reg = st.selectbox(
            "Ready regulatory document",
            regulatory_docs,
            format_func=document_option,
            placeholder="Select indexed regulatory document",
        )
    with right:
        st.subheader("SOP")
        selected_sop = st.selectbox(
            "Ready SOP document",
            sop_docs,
            format_func=document_option,
            placeholder="Select indexed SOP document",
        )

    disabled = not selected_reg or not selected_sop
    active_job = st.session_state.get("last_job_id", "")
    if active_job:
        job = run_api_call("Load active job", lambda: api_client.get_job(active_job, base_url))
        if job and job.get("status") in {"queued", "running"}:
            disabled = True
    if st.button("Run Comparison", type="primary", disabled=disabled):
        result = run_api_call(
            "Create comparison",
            lambda: api_client.create_comparison(
                selected_reg["document_id"],
                selected_sop["document_id"],
                base_url,
            ),
        )
        if result:
            st.session_state["active_comparison_id"] = result["comparison_id"]
            st.session_state["last_job_id"] = result["job_id"]
            st.success(f"Comparison queued: {result['comparison_id']}")
            st.rerun()

    st.divider()
    st.subheader("Comparison Status")
    comparison_id = st.text_input(
        "Comparison ID",
        value=st.session_state.get("active_comparison_id", ""),
    )
    comparison = None
    if comparison_id:
        comparison = run_api_call(
            "Load comparison",
            lambda: api_client.get_comparison(comparison_id, base_url),
        )
    if comparison:
        st.json(comparison)
        if comparison.get("status") == "completed":
            st.success("Comparison complete. Open Review Report to inspect the page-wise findings.")

    job_id = st.text_input("Job ID", value=st.session_state.get("last_job_id", ""))
    render_job_monitor(base_url, job_id)


if __name__ == "__main__":
    main()

"""Main Streamlit entrypoint for the document comparison framework."""

from __future__ import annotations

import streamlit as st

from frontend import api_client
from frontend.ui_components import api_base_url_input, configure_page, run_api_call


def main() -> None:
    configure_page("Document Comparison Framework")
    base_url = api_base_url_input()

    st.caption("Upload, prepare, compare, and review SOP-vs-regulatory gap analysis reports.")

    health = run_api_call("Backend health check", lambda: api_client.health(base_url))
    if health:
        st.success(f"Backend connected: {health.get('status', 'ok')}")
    else:
        st.info("Start the backend before using the workflow pages.")

    documents = run_api_call("Load documents", lambda: api_client.list_documents(base_url=base_url))
    docs = documents.get("documents", []) if documents else []
    regulatory_ready = [
        item for item in docs if item["document_type"] == "regulatory" and item["ready_for_comparison"]
    ]
    sop_ready = [
        item for item in docs if item["document_type"] == "sop" and item["ready_for_comparison"]
    ]

    col1, col2, col3 = st.columns(3)
    col1.metric("Documents", len(docs))
    col2.metric("Ready Regulatory", len(regulatory_ready))
    col3.metric("Ready SOPs", len(sop_ready))

    st.subheader("Workflow")
    st.markdown(
        """
1. Upload regulatory and SOP PDFs in **Upload and Prepare**.
2. Process both documents, then index the regulatory document.
3. Run a comparison in **Compare Documents**.
4. Review SOP page images and gap findings in **Review Report**.
"""
    )


if __name__ == "__main__":
    main()

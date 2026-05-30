"""Main Streamlit entrypoint for IndexAI."""

from __future__ import annotations

import streamlit as st

from frontend import api_client
from frontend.ui_components import api_base_url_input, configure_page, run_api_call


def main() -> None:
    configure_page("IndexAI")
    base_url = api_base_url_input()

    st.caption("Upload one PDF, process and index it, then use it as document memory.")

    health = run_api_call("Backend health check", lambda: api_client.health(base_url))
    if health:
        st.success(f"Backend connected: {health.get('status', 'ok')}")
    else:
        st.info("Start the backend before using the workflow pages.")

    documents = run_api_call("Load documents", lambda: api_client.list_documents(base_url=base_url))
    docs = documents.get("documents", []) if documents else []
    processed = [item for item in docs if item["processing_status"] == "completed"]
    indexed = [item for item in docs if item["indexed"]]

    col1, col2, col3 = st.columns(3)
    col1.metric("Documents", len(docs))
    col2.metric("Processed", len(processed))
    col3.metric("Memory Ready", len(indexed))

    st.subheader("Workflow")
    st.markdown(
        """
1. Upload one PDF in **Upload and Prepare**.
2. Process the PDF into page text and page images.
3. Index the processed pages into `topic_index.json` and document memory.
4. Ask indexed-document questions in **Document Co-pilot**.
"""
    )


if __name__ == "__main__":
    main()

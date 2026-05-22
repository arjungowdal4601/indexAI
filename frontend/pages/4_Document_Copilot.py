"""Document co-pilot for vectorless retrieval against any indexed document."""

from __future__ import annotations

import streamlit as st

from frontend import api_client
from frontend.ui_components import (
    api_base_url_input,
    configure_page,
    document_option,
    format_json,
    indexed_documents,
    run_api_call,
)


def _render_answer(result: dict) -> None:
    answer = result.get("answer", {})
    st.subheader("Answer")
    st.write(answer.get("answer", ""))
    pages_used = answer.get("pages_used") or []
    st.caption(f"Pages used: {', '.join(str(page) for page in pages_used) or 'None'}")
    missing = answer.get("missing_information") or []
    if missing:
        st.markdown("**Missing information**")
        for item in missing:
            st.write(f"- {item}")


def main() -> None:
    configure_page("Document Co-pilot")
    base_url = api_base_url_input()

    documents_response = run_api_call(
        "Load indexed documents",
        lambda: api_client.list_documents(base_url=base_url),
    )
    documents = indexed_documents(documents_response.get("documents", []) if documents_response else [])
    selected = st.selectbox(
        "Indexed document",
        documents,
        format_func=document_option,
        placeholder="Select a processed and indexed document",
    )
    query = st.text_area("Question", height=120)
    cols = st.columns(2)
    with cols[0]:
        max_pages = st.number_input("Max direct pages", min_value=1, max_value=100, value=10)
    with cols[1]:
        max_tokens = st.number_input("Max direct estimated tokens", min_value=1000, value=70000, step=1000)

    if st.button("Ask Co-pilot", type="primary", disabled=not selected or not query.strip()):
        result = run_api_call(
            "Run co-pilot query",
            lambda: api_client.copilot_query(
                selected["document_id"],
                query.strip(),
                base_url=base_url,
                max_direct_pages=int(max_pages),
                max_direct_estimated_tokens=int(max_tokens),
            ),
        )
        if result:
            st.session_state["last_copilot_result"] = result

    result = st.session_state.get("last_copilot_result")
    if not result:
        st.info("Select any indexed regulatory or SOP document and ask a question.")
        return

    route_tab, pages_tab, memory_tab, answer_tab, bundle_tab = st.tabs(
        ["Route", "Pages", "Memory", "Answer", "Thought Analysis Bundle"]
    )
    with route_tab:
        st.json(result.get("routing_decision") or {})
        st.caption("Retrieval trace")
        st.json(result.get("retrieval_trace") or {})
    with pages_tab:
        st.write(result.get("selected_pages") or [])
        selected_doc = result.get("document_id")
        if selected_doc:
            for page in result.get("selected_pages") or []:
                st.caption(f"Page {page}")
                st.image(api_client.absolute_url(api_client.page_image_path(selected_doc, page), base_url), width="stretch")
    with memory_tab:
        st.metric("Estimated context tokens", result.get("estimated_context_tokens") or 0)
        st.write(f"Memory mode: {result.get('memory_mode') or 'unknown'}")
        if result.get("compressed_evidence"):
            st.json(result["compressed_evidence"])
    with answer_tab:
        _render_answer(result)
    with bundle_tab:
        st.caption("Copy this bundle for retrieval thought analysis and answer review.")
        st.code(format_json(result), language="json")


if __name__ == "__main__":
    main()

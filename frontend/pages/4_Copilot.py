"""Chat-style document co-pilot for indexed document memory."""

from __future__ import annotations

from typing import Any

import streamlit as st

from frontend import api_client
from frontend.ui_components import (
    api_base_url_input,
    configure_page,
    document_option,
    indexed_documents,
    run_api_call,
)


def _normalize_pages(pages: list[Any]) -> list[int]:
    normalized: list[int] = []
    seen = set()
    for page in pages:
        try:
            page_no = int(page)
        except (TypeError, ValueError):
            continue
        if page_no <= 0 or page_no in seen:
            continue
        seen.add(page_no)
        normalized.append(page_no)
    return sorted(normalized)


def _answer_text(result: dict[str, Any]) -> str:
    answer_payload = result.get("answer") or {}
    return (
        answer_payload.get("answer")
        or "I could not find a grounded answer in the selected document."
    )


def _source_pages(result: dict[str, Any]) -> list[int]:
    answer_payload = result.get("answer") or {}
    pages = answer_payload.get("pages_used") or result.get("selected_pages") or []
    return _normalize_pages(pages)


def render_sources(document_id: str, pages: list[int], base_url: str) -> None:
    source_pages = _normalize_pages(pages)
    if not source_pages:
        st.caption("Sources: None")
        return

    st.caption("Sources: " + " | ".join(f"p.{page}" for page in source_pages))
    with st.expander("Show source page images", expanded=False):
        for page in source_pages:
            st.caption(f"Page {page}")
            st.image(
                api_client.absolute_url(
                    api_client.page_image_path(document_id, page),
                    base_url,
                ),
                width="stretch",
            )


def _render_message(message: dict[str, Any], document_id: str, base_url: str) -> None:
    role = message.get("role") or "assistant"
    with st.chat_message(role):
        st.markdown(message.get("content") or "")
        if role == "assistant":
            render_sources(document_id, message.get("sources") or [], base_url)


def _reset_chat_if_document_changed(document_id: str) -> None:
    previous_document_id = st.session_state.get("selected_copilot_document_id")
    if previous_document_id == document_id:
        return
    st.session_state["selected_copilot_document_id"] = document_id
    st.session_state["copilot_messages"] = []


def main() -> None:
    configure_page("IndexAI Co-pilot")
    base_url = api_base_url_input()

    documents_response = run_api_call(
        "Load indexed documents",
        lambda: api_client.list_documents(base_url=base_url),
    )
    documents = indexed_documents(documents_response.get("documents", []) if documents_response else [])
    if not documents:
        st.info("No indexed documents found. Upload and index a PDF first.")
        return

    selected = st.selectbox(
        "Indexed document",
        documents,
        format_func=document_option,
        placeholder="Select any indexed document",
    )
    if not selected:
        st.info("Select any indexed document and ask a question.")
        return

    selected_document_id = selected["document_id"]
    _reset_chat_if_document_changed(selected_document_id)
    st.session_state.setdefault("copilot_messages", [])

    for message in st.session_state["copilot_messages"]:
        _render_message(message, selected_document_id, base_url)

    user_query = st.chat_input("Ask anything about this document...")
    if not user_query:
        return

    user_message = {
        "role": "user",
        "content": user_query,
        "sources": [],
    }
    st.session_state["copilot_messages"].append(user_message)
    _render_message(user_message, selected_document_id, base_url)

    result = run_api_call(
        "Run co-pilot query",
        lambda: api_client.copilot_query(
            document_id=selected_document_id,
            query=user_query.strip(),
            base_url=base_url,
            max_direct_pages=5,
            max_direct_estimated_tokens=70000,
        ),
    )
    if not result:
        return

    assistant_message = {
        "role": "assistant",
        "content": _answer_text(result),
        "sources": _source_pages(result),
        "raw_result": result,
    }
    st.session_state["copilot_messages"].append(assistant_message)
    _render_message(assistant_message, selected_document_id, base_url)


if __name__ == "__main__":
    main()

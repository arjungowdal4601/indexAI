"""Run SOP-vs-regulatory comparisons."""

from __future__ import annotations

import streamlit as st

from frontend import api_client
from frontend.ui_components import (
    api_base_url_input,
    configure_page,
    render_comparison_progress,
    ready_documents,
    run_api_call,
)


def _document_rows(documents: list[dict]) -> list[dict[str, str]]:
    return [
        {
            "Document ID": document["document_id"],
            "Filename": document["filename"],
        }
        for document in documents
    ]


def _selected_document(
    title: str,
    documents: list[dict],
    state_key: str,
    table_key: str,
) -> dict | None:
    st.subheader(title)
    rows = _document_rows(documents)
    valid_ids = {row["Document ID"] for row in rows}
    if st.session_state.get(state_key) not in valid_ids:
        st.session_state[state_key] = None

    if not rows:
        st.info("No ready documents.")
        return None

    try:
        selection = st.dataframe(
            rows,
            hide_index=True,
            width="stretch",
            on_select="rerun",
            selection_mode="single-row",
            key=table_key,
        )
        selected_rows = []
        selection_payload = getattr(selection, "selection", None)
        if selection_payload is not None:
            selected_rows = getattr(selection_payload, "rows", [])
            if not selected_rows and isinstance(selection_payload, dict):
                selected_rows = selection_payload.get("rows", [])
        if selected_rows:
            st.session_state[state_key] = rows[int(selected_rows[0])]["Document ID"]
    except TypeError:
        st.dataframe(rows, hide_index=True, width="stretch")
        options = [row["Document ID"] for row in rows]
        selected = st.radio(
            f"{title} selection",
            options,
            format_func=lambda document_id: next(
                row["Filename"] for row in rows if row["Document ID"] == document_id
            ),
            key=f"{table_key}-fallback",
        )
        st.session_state[state_key] = selected

    selected_id = st.session_state.get(state_key)
    if selected_id:
        return next((document for document in documents if document["document_id"] == selected_id), None)
    return None


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
        selected_reg = _selected_document(
            "Regulatory Documents",
            regulatory_docs,
            "selected_regulatory_document_id",
            "regulatory-select-table",
        )
    with right:
        selected_sop = _selected_document(
            "SOP Documents",
            sop_docs,
            "selected_sop_document_id",
            "sop-select-table",
        )

    pair_state = None
    if selected_reg and selected_sop:
        pair_state = run_api_call(
            "Load comparison state for selected pair",
            lambda: api_client.get_active_comparison_for_pair(
                selected_reg["document_id"],
                selected_sop["document_id"],
                base_url,
            ),
        )
    active_comparison_id = pair_state.get("active_comparison_id") if pair_state else None
    latest_comparison_id = pair_state.get("latest_comparison_id") if pair_state else None
    comparison_to_show = (
        active_comparison_id
        or latest_comparison_id
        or st.session_state.get("active_comparison_id")
    )

    disabled = not selected_reg or not selected_sop or bool(active_comparison_id)
    if active_comparison_id:
        st.info(f"A comparison is already running for this document pair: {active_comparison_id}")
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
            st.success(f"Comparison queued: {result['comparison_id']}")
            st.rerun()

    st.divider()
    if latest_comparison_id and not active_comparison_id:
        st.caption(f"Latest comparison: {latest_comparison_id}")
    render_comparison_progress(base_url, comparison_to_show)


if __name__ == "__main__":
    main()

"""Run SOP-vs-regulatory comparisons."""

from __future__ import annotations

import streamlit as st

from frontend import api_client
from frontend.ui_components import (
    api_base_url_input,
    configure_page,
    document_option,
    render_comparison_progress,
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

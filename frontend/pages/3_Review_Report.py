"""Review page-wise gap analysis reports."""

from __future__ import annotations

import streamlit as st

from frontend import api_client
from frontend.ui_components import (
    api_base_url_input,
    configure_page,
    format_json,
    page_numbers_from_report,
    report_summary,
    render_status,
    run_api_call,
)


def render_gap_item(item: dict, index: int) -> None:
    title = item.get("sop_topic") or f"Finding {index}"
    status = item.get("status", "not_applicable")
    severity = item.get("severity", "informational")
    with st.expander(f"{index}. {title} - {status} / {severity}", expanded=index == 1):
        cols = st.columns(2)
        with cols[0]:
            st.caption("SOP evidence")
            st.write(item.get("sop_evidence", ""))
        with cols[1]:
            st.caption("Regulatory evidence")
            st.write(item.get("regulatory_evidence", ""))
        st.caption("Gap explanation")
        st.write(item.get("gap_explanation", ""))
        st.caption("Recommendation")
        st.write(item.get("recommendation") or item.get("recommended_action", ""))
        pages = item.get("regulatory_pages") or item.get("regulatory_pages_used") or []
        st.caption(f"Regulatory pages checked: {', '.join(str(page) for page in pages) or 'None'}")


def render_page_analysis(page: dict) -> None:
    status = page.get("overall_status") or page.get("page_status") or "not_applicable"
    st.subheader(f"SOP Page {page.get('sop_page')}")
    render_status(status)

    summary = page.get("sop_page_summary")
    if summary:
        st.write(summary)

    if page.get("what_went_right"):
        st.markdown("**What went right**")
        for item in page["what_went_right"]:
            st.write(f"- {item}")

    if page.get("what_went_wrong"):
        st.markdown("**What went wrong**")
        for item in page["what_went_wrong"]:
            st.write(f"- {item}")

    if page.get("human_review_items"):
        st.markdown("**Needs human review**")
        for item in page["human_review_items"]:
            st.write(f"- {item}")

    findings = page.get("gap_items") or page.get("findings") or []
    st.markdown("**Gap items**")
    if not findings:
        st.info("No gap items for this page.")
    for index, item in enumerate(findings, start=1):
        render_gap_item(item, index)


def main() -> None:
    configure_page("Review Report")
    base_url = api_base_url_input()

    comparison_id = st.text_input(
        "Comparison ID",
        value=st.session_state.get("active_comparison_id", ""),
    )
    if not comparison_id:
        st.info("Enter a comparison ID after running a comparison.")
        return

    report = run_api_call(
        "Load comparison report",
        lambda: api_client.get_comparison_report(comparison_id, base_url),
    )
    if not report:
        return

    summary = report_summary(report)
    st.subheader("Summary")
    st.json(summary)
    st.download_button(
        "Download report JSON",
        data=format_json(report),
        file_name=f"{comparison_id}_final_report.json",
        mime="application/json",
    )

    pages = page_numbers_from_report(report)
    if not pages:
        st.warning("No page reports found in the comparison report.")
        return

    selected_page = st.selectbox("SOP page", pages)
    page = run_api_call(
        "Load page report",
        lambda: api_client.get_page_report(comparison_id, selected_page, base_url),
    )
    if not page:
        return

    left, right = st.columns([1, 1.2])
    with left:
        st.subheader("SOP Page Image")
        image_url = page.get("sop_page_image_url")
        if page.get("image_warning"):
            st.warning(page["image_warning"])
        elif image_url:
            st.image(api_client.absolute_url(image_url, base_url), width="stretch")
        else:
            st.warning("No SOP page image URL returned.")

    with right:
        render_page_analysis(page)


if __name__ == "__main__":
    main()

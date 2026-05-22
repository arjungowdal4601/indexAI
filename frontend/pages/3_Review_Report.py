"""Review page-wise gap analysis reports."""

from __future__ import annotations

import csv
import io

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


def _all_findings(report: dict) -> list[dict]:
    findings = []
    for page in report.get("page_results") or report.get("page_reports") or []:
        for item in page.get("gap_items") or page.get("findings") or []:
            findings.append({**item, "sop_page": page.get("sop_page")})
    return findings


def _report_csv(report: dict) -> str:
    output = io.StringIO()
    fieldnames = [
        "sop_page",
        "sop_topic",
        "regulatory_topic",
        "status",
        "severity",
        "regulatory_pages",
        "gap_explanation",
        "recommendation",
    ]
    writer = csv.DictWriter(output, fieldnames=fieldnames)
    writer.writeheader()
    for item in _all_findings(report):
        writer.writerow(
            {
                "sop_page": item.get("sop_page", ""),
                "sop_topic": item.get("sop_topic", ""),
                "regulatory_topic": item.get("regulatory_topic") or ", ".join(item.get("regulatory_topics", [])),
                "status": item.get("status", ""),
                "severity": item.get("severity", ""),
                "regulatory_pages": ", ".join(str(page) for page in item.get("regulatory_pages") or item.get("regulatory_pages_used") or []),
                "gap_explanation": item.get("gap_explanation", ""),
                "recommendation": item.get("recommendation") or item.get("recommended_action", ""),
            }
        )
    return output.getvalue()


def _report_markdown(report: dict) -> str:
    lines = ["# SOP vs Regulatory Gap Analysis Report", ""]
    summary = report_summary(report)
    if summary:
        lines.append("## Summary")
        for key, value in summary.items():
            lines.append(f"- {key}: {value}")
        lines.append("")
    for page in report.get("page_results") or report.get("page_reports") or []:
        lines.append(f"## SOP Page {page.get('sop_page')}")
        lines.append(f"- Status: {page.get('overall_status') or page.get('page_status', 'not_applicable')}")
        for item in page.get("gap_items") or page.get("findings") or []:
            lines.append(f"### {item.get('sop_topic', 'Finding')}")
            lines.append(f"- Status: {item.get('status', '')}")
            lines.append(f"- Severity: {item.get('severity', '')}")
            lines.append(f"- Gap: {item.get('gap_explanation', '')}")
            lines.append(f"- Recommendation: {item.get('recommendation') or item.get('recommended_action', '')}")
        lines.append("")
    return "\n".join(lines)


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
    c1, c2 = st.columns(2)
    with c1:
        st.download_button(
            "Download report CSV",
            data=_report_csv(report),
            file_name=f"{comparison_id}_final_report.csv",
            mime="text/csv",
        )
    with c2:
        st.download_button(
            "Download report Markdown",
            data=_report_markdown(report),
            file_name=f"{comparison_id}_final_report.md",
            mime="text/markdown",
        )

    pages = page_numbers_from_report(report)
    if not pages:
        st.warning("No page reports found in the comparison report.")
        return

    findings = _all_findings(report)
    status_options = sorted({item.get("status", "not_applicable") for item in findings})
    severity_options = sorted({item.get("severity", "informational") for item in findings})
    filter_cols = st.columns(3)
    with filter_cols[0]:
        selected_status = st.multiselect("Status filter", status_options, default=status_options)
    with filter_cols[1]:
        selected_severity = st.multiselect("Severity filter", severity_options, default=severity_options)
    with filter_cols[2]:
        human_only = st.checkbox("Human-review only")

    filtered_pages = []
    for page in report.get("page_results") or report.get("page_reports") or []:
        page_findings = page.get("gap_items") or page.get("findings") or []
        if not page_findings:
            filtered_pages.append(int(page["sop_page"]))
            continue
        visible = [
            item
            for item in page_findings
            if item.get("status", "not_applicable") in selected_status
            and item.get("severity", "informational") in selected_severity
            and (not human_only or item.get("status") == "needs_human_review")
        ]
        if visible:
            filtered_pages.append(int(page["sop_page"]))
    selected_page = st.selectbox("SOP page", sorted(set(filtered_pages)) or pages)
    page = run_api_call(
        "Load page report",
        lambda: api_client.get_page_report(comparison_id, selected_page, base_url),
    )
    if not page:
        return
    page_items_key = "gap_items" if "gap_items" in page else "findings"
    page_items = page.get(page_items_key) or []
    if page_items:
        page[page_items_key] = [
            item
            for item in page_items
            if item.get("status", "not_applicable") in selected_status
            and item.get("severity", "informational") in selected_severity
            and (not human_only or item.get("status") == "needs_human_review")
        ]

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

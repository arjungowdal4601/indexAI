"""Review page-wise gap analysis reports."""

from __future__ import annotations

from html import escape

import streamlit as st

from frontend import api_client
from frontend.ui_components import (
    api_base_url_input,
    configure_page,
    page_numbers_from_report,
    report_summary,
    run_api_call,
)

STATUS_LABELS = {
    "compliant": "Compliant",
    "partially_compliant": "Partial",
    "missing": "Missing",
    "conflicting": "Conflicting",
    "needs_human_review": "Needs review",
    "not_applicable": "Not applicable",
}

STATUS_ORDER = [
    "compliant",
    "partially_compliant",
    "missing",
    "conflicting",
    "needs_human_review",
    "not_applicable",
]

STATUS_GUIDE = [
    "Compliant — SOP covers the requirement.",
    "Partial — SOP covers it, but some controls/evidence are missing.",
    "Missing — SOP does not cover the requirement.",
    "Conflicting — SOP says something that conflicts with the regulatory expectation.",
    "Needs review — evidence is unclear; human reviewer should decide.",
    "Not applicable — page/content is not relevant to GMP comparison.",
]

PAGE_STATUS_ALIASES = {
    "partial": "partially_compliant",
    "major_gaps": "missing",
}

STATUS_BADGE_STYLES = {
    "compliant": ("rgba(34, 197, 94, 0.18)", "rgba(34, 197, 94, 0.55)", "#86efac"),
    "partially_compliant": ("rgba(245, 158, 11, 0.18)", "rgba(245, 158, 11, 0.55)", "#fcd34d"),
    "missing": ("rgba(239, 68, 68, 0.18)", "rgba(239, 68, 68, 0.55)", "#fca5a5"),
    "conflicting": ("rgba(249, 115, 22, 0.18)", "rgba(249, 115, 22, 0.55)", "#fdba74"),
    "needs_human_review": ("rgba(129, 140, 248, 0.18)", "rgba(129, 140, 248, 0.55)", "#c4b5fd"),
    "not_applicable": ("rgba(148, 163, 184, 0.14)", "rgba(148, 163, 184, 0.45)", "#cbd5e1"),
}


def inject_review_report_styles() -> None:
    st.markdown(
        """
        <style>
        .review-muted {
            color: rgba(250, 250, 250, 0.72);
            font-size: 0.92rem;
        }
        .review-section-label {
            color: rgba(250, 250, 250, 0.74);
            font-size: 0.78rem;
            font-weight: 700;
            letter-spacing: 0.02em;
            margin: 0.85rem 0 0.2rem;
            text-transform: uppercase;
        }
        .status-pill {
            align-items: center;
            border: 1px solid;
            border-radius: 999px;
            display: inline-flex;
            font-size: 0.78rem;
            font-weight: 700;
            line-height: 1;
            margin: 0.15rem 0 0.5rem;
            padding: 0.28rem 0.58rem;
            white-space: nowrap;
        }
        div[data-testid="stMetric"] {
            border: 1px solid rgba(148, 163, 184, 0.22);
            border-radius: 0.5rem;
            padding: 0.65rem 0.75rem;
        }
        div[data-testid="stNumberInput"] {
            max-width: 7rem;
            margin-left: auto;
            margin-right: auto;
        }
        </style>
        """,
        unsafe_allow_html=True,
    )


def _canonical_status(status: str | None) -> str:
    value = (status or "not_applicable").strip().lower()
    return PAGE_STATUS_ALIASES.get(value, value)


def _status_label(status: str | None) -> str:
    value = _canonical_status(status)
    return STATUS_LABELS.get(value, (status or "Not applicable").replace("_", " ").title())


def _status_badge_html(status: str | None) -> str:
    canonical = _canonical_status(status)
    background, border, color = STATUS_BADGE_STYLES.get(
        canonical,
        ("rgba(148, 163, 184, 0.14)", "rgba(148, 163, 184, 0.45)", "#e2e8f0"),
    )
    label = escape(_status_label(status))
    return (
        f'<span class="status-pill" '
        f'style="background:{background};border-color:{border};color:{color};">'
        f"{label}</span>"
    )


def _page_status(page: dict) -> str:
    return page.get("overall_status") or page.get("page_status") or "not_applicable"


def _page_items(page: dict) -> list[dict]:
    return list(page.get("gap_items") or page.get("findings") or [])


def _text_or_dash(value: object) -> object:
    if value in (None, "", [], {}):
        return "Not provided."
    return value


def _render_text_section(label: str, value: object) -> None:
    st.markdown(f'<div class="review-section-label">{escape(label)}</div>', unsafe_allow_html=True)
    if isinstance(value, list):
        if not value:
            st.write("Not provided.")
            return
        for item in value:
            st.write(f"- {item}")
        return
    st.write(_text_or_dash(value))


def _render_finding_card(item: dict, index: int) -> None:
    title = item.get("sop_topic") or item.get("title") or f"Finding {index}"
    status = _status_label(item.get("status"))
    with st.expander(f"{index}. {title} - {status}", expanded=index == 1):
        st.markdown(_status_badge_html(item.get("status")), unsafe_allow_html=True)
        _render_text_section("SOP evidence", item.get("sop_evidence"))
        _render_text_section("Regulatory evidence", item.get("regulatory_evidence"))
        _render_text_section("Gap", item.get("gap_explanation"))
        _render_text_section(
            "Recommended action",
            item.get("recommended_action") or item.get("recommendation"),
        )
        _render_text_section("Missing / weak elements", item.get("missing_or_weak_elements") or [])
        pages = item.get("regulatory_pages") or item.get("regulatory_pages_used") or []
        page_text = ", ".join(str(page) for page in pages) if pages else "None"
        _render_text_section("Regulatory pages used", page_text)


def _render_analysis_panel(page: dict) -> None:
    with st.container(border=True):
        status = _page_status(page)
        st.subheader(f"SOP Page {page.get('sop_page')}")
        st.markdown(_status_badge_html(status), unsafe_allow_html=True)

        summary = page.get("sop_page_summary") or page.get("summary")
        if summary:
            _render_text_section("Page summary", summary)

        if page.get("what_went_right"):
            _render_text_section("SOP evidence", page["what_went_right"])

        if page.get("what_went_wrong"):
            _render_text_section("Gap notes", page["what_went_wrong"])

        if page.get("human_review_items"):
            _render_text_section("Needs review", page["human_review_items"])

        findings = _page_items(page)
        st.markdown("**Findings**")
        if not findings:
            st.info("No findings match the selected status filter on this page.")
        for index, item in enumerate(findings, start=1):
            _render_finding_card(item, index)


def _render_image_panel(page: dict, base_url: str) -> None:
    with st.container(border=True):
        st.subheader("SOP Page Image")
        image_url = page.get("sop_page_image_url")
        if page.get("image_warning"):
            st.warning(page["image_warning"])
        elif image_url:
            st.image(api_client.absolute_url(image_url, base_url), width="stretch")
        else:
            st.warning("No SOP page image URL returned.")


def _all_findings(report: dict) -> list[dict]:
    findings = []
    for page in report.get("page_results") or report.get("page_reports") or []:
        for item in _page_items(page):
            findings.append({**item, "sop_page": item.get("sop_page") or page.get("sop_page")})
    return findings


def _summary_metrics(report: dict) -> dict[str, int]:
    summary = report_summary(report)
    pages = page_numbers_from_report(report)
    findings = _all_findings(report)
    counts = {status: 0 for status in STATUS_ORDER}
    for item in findings:
        status = _canonical_status(item.get("status"))
        if status in counts:
            counts[status] += 1
    for status in STATUS_ORDER:
        if summary.get(status) is not None:
            counts[status] = int(summary[status])
    return {
        "Pages reviewed": int(
            summary.get("total_sop_pages_reviewed")
            or summary.get("total_pages")
            or len(pages)
        ),
        "Total findings": int(summary.get("total_findings") or len(findings)),
        "Compliant": counts["compliant"],
        "Partial": counts["partially_compliant"],
        "Missing": counts["missing"],
        "Conflicting": counts["conflicting"],
        "Needs review": counts["needs_human_review"],
        "Not applicable": counts["not_applicable"],
    }


def _render_review_header(comparison_id: str, report: dict) -> None:
    request = report.get("comparison_request") or report.get("request") or {}
    regulatory = (
        report.get("regulatory_filename")
        or request.get("regulatory_filename")
        or request.get("regulatory_document_id")
        or report.get("regulatory_document_id")
    )
    sop = (
        report.get("sop_filename")
        or request.get("sop_filename")
        or request.get("sop_document_id")
        or report.get("sop_document_id")
    )
    with st.container(border=True):
        st.caption(f"Comparison: {comparison_id}")
        if regulatory or sop:
            st.markdown(
                f"**Regulatory:** {_text_or_dash(regulatory)}  \n"
                f"**SOP:** {_text_or_dash(sop)}"
            )


def _render_summary_cards(report: dict) -> None:
    metrics = _summary_metrics(report)
    st.subheader("Summary")
    with st.container(border=True):
        rows = [
            ["Pages reviewed", "Total findings", "Compliant", "Partial"],
            ["Missing", "Conflicting", "Needs review", "Not applicable"],
        ]
        for row in rows:
            cols = st.columns(len(row))
            for column, label in zip(cols, row):
                column.metric(label, metrics[label])


def _render_downloads(comparison_id: str, base_url: str) -> None:
    csv_payload = run_api_call(
        "Download CSV report",
        lambda: api_client.download_comparison_csv(comparison_id, base_url),
    )
    bundle_payload = run_api_call(
        "Download Thought Analysis Bundle",
        lambda: api_client.download_thought_analysis_bundle(comparison_id, base_url),
    )
    with st.container(border=True):
        st.markdown("**Downloads**")
        cols = st.columns([1, 1, 3], gap="small", vertical_alignment="center")
        with cols[0]:
            st.download_button(
                "Download CSV report",
                data=csv_payload or b"",
                file_name=f"{comparison_id}_final_report.csv",
                mime="text/csv",
                disabled=csv_payload is None,
                width="stretch",
            )
        with cols[1]:
            st.download_button(
                "Download Thought Analysis Bundle",
                data=bundle_payload or b"",
                file_name=f"{comparison_id}_thought_analysis_bundle.json",
                mime="application/json",
                disabled=bundle_payload is None,
                width="stretch",
            )


def _render_status_guide() -> None:
    with st.expander("Status guide", expanded=False):
        cols = st.columns(2, gap="large")
        for index, line in enumerate(STATUS_GUIDE):
            cols[index % 2].write(line)


def _render_status_filters(comparison_id: str) -> set[str]:
    selected = set()
    with st.container(border=True):
        st.markdown("**Filter by status**")
        cols = st.columns(len(STATUS_ORDER), gap="small")
        for index, status in enumerate(STATUS_ORDER):
            with cols[index]:
                if st.checkbox(
                    STATUS_LABELS[status],
                    value=True,
                    key=f"status-filter-{comparison_id}-{status}",
                ):
                    selected.add(status)
    return selected


def _render_page_navigation(comparison_id: str, pages: list[int]) -> int:
    available_pages = sorted(set(int(page) for page in pages))
    first_page = available_pages[0]
    last_page = available_pages[-1]
    state_key = f"selected_sop_page_{comparison_id}"
    current = st.session_state.get(state_key)
    try:
        current = int(current)
    except (TypeError, ValueError):
        current = first_page
    current = max(first_page, min(last_page, current))
    if current not in available_pages:
        current = first_page
        st.session_state[state_key] = current

    current_index = available_pages.index(current)
    with st.container(border=True):
        nav_cols = st.columns([1, 2, 1], gap="large", vertical_alignment="center")
        if nav_cols[0].button(
            "← Previous",
            disabled=current_index == 0,
            width="stretch",
            key=f"previous-page-{comparison_id}",
        ):
            st.session_state[state_key] = available_pages[current_index - 1]
            st.rerun()
        if nav_cols[2].button(
            "Next →",
            disabled=current_index >= len(available_pages) - 1,
            width="stretch",
            key=f"next-page-{comparison_id}",
        ):
            st.session_state[state_key] = available_pages[current_index + 1]
            st.rerun()
        with nav_cols[1]:
            page_cols = st.columns([1, 0.55, 1], gap="small", vertical_alignment="center")
            page_cols[0].markdown("**SOP Page**")
            with page_cols[1]:
                selected_page = st.number_input(
                    "SOP page number",
                    min_value=first_page,
                    max_value=last_page,
                    value=current,
                    step=1,
                    key=state_key,
                    label_visibility="collapsed",
                    width=110,
                )
            page_cols[2].markdown(f"**of {last_page}**")
    return int(selected_page)


def _filter_page_findings(page: dict, selected_statuses: set[str]) -> dict:
    filtered = dict(page)
    key = "gap_items" if "gap_items" in page else "findings"
    findings = _page_items(page)
    filtered[key] = [
        item
        for item in findings
        if _canonical_status(item.get("status")) in selected_statuses
    ]
    return filtered


def _comparison_rows(comparisons: list[dict]) -> list[dict[str, str]]:
    return [
        {
            "Comparison ID": item["comparison_id"],
            "Regulatory Document": item.get("regulatory_filename") or item["regulatory_document_id"],
            "SOP Document": item.get("sop_filename") or item["sop_document_id"],
            "Status": item.get("status", ""),
            "View": "View",
        }
        for item in comparisons
    ]


def _render_comparison_table(rows: list[dict[str, str]], key: str) -> None:
    if not rows:
        st.info("No comparison reports found.")
        return
    try:
        selection = st.dataframe(
            rows,
            hide_index=True,
            width="stretch",
            on_select="rerun",
            selection_mode="single-row",
            key=key,
        )
        selection_payload = getattr(selection, "selection", None)
        selected_rows = []
        if selection_payload is not None:
            selected_rows = getattr(selection_payload, "rows", [])
            if not selected_rows and isinstance(selection_payload, dict):
                selected_rows = selection_payload.get("rows", [])
        if selected_rows:
            st.session_state["selected_comparison_id"] = rows[int(selected_rows[0])]["Comparison ID"]
    except TypeError:
        header = st.columns([1.2, 2, 2, 1, 0.8])
        header[0].markdown("**Comparison ID**")
        header[1].markdown("**Regulatory Document**")
        header[2].markdown("**SOP Document**")
        header[3].markdown("**Status**")
        header[4].markdown("**View**")
        for row in rows:
            cols = st.columns([1.2, 2, 2, 1, 0.8])
            cols[0].write(row["Comparison ID"])
            cols[1].write(row["Regulatory Document"])
            cols[2].write(row["SOP Document"])
            cols[3].write(row["Status"])
            if cols[4].button("View", key=f"view-{row['Comparison ID']}"):
                st.session_state["selected_comparison_id"] = row["Comparison ID"]
                st.rerun()


def _comparison_browser(base_url: str) -> str | None:
    response = run_api_call(
        "Load comparison reports",
        lambda: api_client.list_comparisons(base_url),
    )
    comparisons = response.get("comparisons", []) if response else []
    rows = _comparison_rows(comparisons)
    selected_id = st.session_state.get("selected_comparison_id") or st.session_state.get(
        "active_comparison_id"
    )
    valid_ids = {row["Comparison ID"] for row in rows}
    if selected_id not in valid_ids:
        selected_id = None
        st.session_state["selected_comparison_id"] = None
    else:
        st.session_state["selected_comparison_id"] = selected_id

    st.subheader("Comparison Reports")
    if selected_id:
        with st.expander("Comparison reports", expanded=False):
            _render_comparison_table(rows, "comparison-report-browser-collapsed")
        selected_row = next(row for row in rows if row["Comparison ID"] == selected_id)
        st.caption(
            f"Viewing {selected_row['Comparison ID']} - "
            f"{selected_row['Regulatory Document']} vs {selected_row['SOP Document']}"
        )
    else:
        _render_comparison_table(rows, "comparison-report-browser")
        selected_id = st.session_state.get("selected_comparison_id")

    if not selected_id:
        st.info("Select a comparison report to view it.")
    return selected_id


def main() -> None:
    configure_page("Review Report")
    inject_review_report_styles()
    base_url = api_base_url_input()

    comparison_id = _comparison_browser(base_url)
    if not comparison_id:
        return

    report = run_api_call(
        "Load comparison report",
        lambda: api_client.get_comparison_report(comparison_id, base_url),
    )
    if not report:
        return

    _render_review_header(comparison_id, report)
    _render_summary_cards(report)
    _render_downloads(comparison_id, base_url)
    _render_status_guide()

    pages = page_numbers_from_report(report)
    if not pages:
        st.warning("No page reports found in the comparison report.")
        return

    selected_statuses = _render_status_filters(comparison_id)
    selected_page = _render_page_navigation(comparison_id, pages)
    page = run_api_call(
        "Load page report",
        lambda: api_client.get_page_report(comparison_id, selected_page, base_url),
    )
    if not page:
        return
    page = _filter_page_findings(page, selected_statuses)

    left, right = st.columns([5, 7], gap="large", vertical_alignment="top")
    with left:
        _render_image_panel(page, base_url)
    with right:
        _render_analysis_panel(page)


if __name__ == "__main__":
    main()

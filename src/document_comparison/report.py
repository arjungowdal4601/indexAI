"""Deterministic report generation for document comparison."""

from __future__ import annotations

import csv
from pathlib import Path

from .schemas import GapReport, PageComparisonResult, ReportCounts
from .storage import (
    executive_summary_path,
    final_report_csv_path,
    final_report_json_path,
    final_report_markdown_path,
    report_markdown_path,
    write_gap_report_json,
)


def build_report_counts(page_results: list[PageComparisonResult]) -> ReportCounts:
    counts = ReportCounts(total_sop_pages_reviewed=len(page_results))
    for page_result in page_results:
        for finding in page_result.findings:
            counts.total_findings += 1
            if finding.status == "compliant":
                counts.compliant += 1
            elif finding.status == "partially_compliant":
                counts.partially_compliant += 1
            elif finding.status == "missing":
                counts.missing += 1
            elif finding.status == "conflicting":
                counts.conflicting += 1
            elif finding.status == "not_applicable":
                counts.not_applicable += 1
            elif finding.status == "needs_human_review":
                counts.needs_human_review += 1

            if finding.severity == "critical":
                counts.critical += 1
            elif finding.severity == "major":
                counts.major += 1
            elif finding.severity == "minor":
                counts.minor += 1
            elif finding.severity == "informational":
                counts.informational += 1
    return counts


def build_gap_report(
    comparison_run_id: str,
    regulatory_doc_id: str,
    sop_doc_id: str,
    page_results: list[PageComparisonResult],
) -> GapReport:
    return GapReport(
        comparison_run_id=comparison_run_id,
        regulatory_doc_id=regulatory_doc_id,
        sop_doc_id=sop_doc_id,
        counts=build_report_counts(page_results),
        page_results=page_results,
    )


def format_gap_report_markdown(report: GapReport) -> str:
    counts = report.counts
    lines = [
        "# SOP vs Regulatory Gap Analysis Report",
        "",
        "## Documents",
        "",
        f"- Regulatory document: `{report.regulatory_doc_id}`",
        f"- SOP document: `{report.sop_doc_id}`",
        f"- Comparison run: `{report.comparison_run_id}`",
        "",
        "## Executive Summary",
        "",
        f"- Total SOP pages reviewed: {counts.total_sop_pages_reviewed}",
        f"- Total findings: {counts.total_findings}",
        f"- Compliant: {counts.compliant}",
        f"- Partially compliant: {counts.partially_compliant}",
        f"- Missing: {counts.missing}",
        f"- Conflicting: {counts.conflicting}",
        f"- Needs human review: {counts.needs_human_review}",
        "",
        "## Page-wise Findings",
        "",
    ]
    for page_result in report.page_results:
        lines.extend(
            [
                f"### SOP Page {page_result.sop_page}",
                "",
                f"Page status: `{page_result.page_status}`",
                "",
            ]
        )
        if not page_result.findings:
            lines.extend(["No comparable SOP items found on this page.", ""])
            continue
        for index, finding in enumerate(page_result.findings, start=1):
            missing = finding.missing_or_weak_elements or ["None"]
            lines.extend(
                [
                    f"#### Finding {index}: {finding.sop_topic}",
                    "",
                    f"- Status: `{finding.status}`",
                    f"- Severity: `{finding.severity}`",
                    f"- Confidence: `{finding.confidence}`",
                    f"- Regulatory topics: {', '.join(finding.regulatory_topics) or 'None'}",
                    f"- Regulatory pages: {', '.join(str(page) for page in finding.regulatory_pages_used) or 'None'}",
                    f"- SOP evidence: {finding.sop_evidence}",
                    f"- Regulatory evidence: {finding.regulatory_evidence}",
                    f"- Gap explanation: {finding.gap_explanation}",
                    f"- Recommended action: {finding.recommended_action}",
                    "- Missing or weak elements:",
                ]
            )
            lines.extend(f"  - {item}" for item in missing)
            lines.append("")
    return "\n".join(lines).rstrip() + "\n"


def format_executive_summary(report: GapReport) -> str:
    counts = report.counts
    return (
        "# Executive Summary\n\n"
        f"- SOP pages reviewed: {counts.total_sop_pages_reviewed}\n"
        f"- Total findings: {counts.total_findings}\n"
        f"- Compliant: {counts.compliant}\n"
        f"- Partially compliant: {counts.partially_compliant}\n"
        f"- Missing: {counts.missing}\n"
        f"- Conflicting: {counts.conflicting}\n"
        f"- Needs human review: {counts.needs_human_review}\n"
    )


def write_gap_report_csv(comparison_run_dir: str | Path, report: GapReport) -> Path:
    path = final_report_csv_path(comparison_run_dir)
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8", newline="") as file:
        writer = csv.DictWriter(
            file,
            fieldnames=[
                "comparison_id",
                "sop_page",
                "sop_topic",
                "regulatory_topics",
                "status",
                "severity",
                "regulatory_pages",
                "gap_explanation",
                "recommendation",
            ],
        )
        writer.writeheader()
        for page_result in report.page_results:
            for finding in page_result.findings:
                writer.writerow(
                    {
                        "comparison_id": report.comparison_run_id,
                        "sop_page": page_result.sop_page,
                        "sop_topic": finding.sop_topic,
                        "regulatory_topics": "; ".join(finding.regulatory_topics),
                        "status": finding.status,
                        "severity": finding.severity,
                        "regulatory_pages": "; ".join(
                            str(page) for page in finding.regulatory_pages_used
                        ),
                        "gap_explanation": finding.gap_explanation,
                        "recommendation": finding.recommended_action,
                    }
                )
    return path


def write_reports(comparison_run_dir: str | Path, report: GapReport) -> tuple[Path, Path, Path]:
    json_path = write_gap_report_json(comparison_run_dir, report)
    markdown_path = report_markdown_path(comparison_run_dir)
    summary_path = executive_summary_path(comparison_run_dir)
    final_json_path = final_report_json_path(comparison_run_dir)
    final_markdown_path = final_report_markdown_path(comparison_run_dir)
    markdown_path.parent.mkdir(parents=True, exist_ok=True)
    final_json_path.write_text(json_path.read_text(encoding="utf-8"), encoding="utf-8")
    markdown = format_gap_report_markdown(report)
    markdown_path.write_text(markdown, encoding="utf-8")
    final_markdown_path.write_text(markdown, encoding="utf-8")
    write_gap_report_csv(comparison_run_dir, report)
    summary_path.write_text(format_executive_summary(report), encoding="utf-8")
    return final_json_path, final_markdown_path, summary_path

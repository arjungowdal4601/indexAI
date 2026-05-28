"""Read and prepare comparison reports for API responses and downloads."""

from __future__ import annotations

import csv
import json
from pathlib import Path
from typing import Any

from fastapi import HTTPException

from backend.services import comparison_service, document_service, job_event_service, registry

THOUGHT_ANALYSIS_BUNDLE_FILE = "thought_analysis_bundle.json"

STATUS_TAXONOMY = {
    "compliant": "SOP covers the requirement.",
    "partially_compliant": "SOP covers it, but some controls/evidence are missing.",
    "missing": "SOP does not cover the requirement.",
    "conflicting": "SOP says something that conflicts with the regulatory expectation.",
    "needs_human_review": "Evidence is unclear; human reviewer should decide.",
    "not_applicable": "Page/content is not relevant to GMP comparison.",
}

CSV_COLUMNS = [
    "comparison_id",
    "sop_page",
    "page_status",
    "sop_topic",
    "status",
    "severity",
    "confidence",
    "sop_evidence",
    "regulatory_topics",
    "regulatory_pages_used",
    "regulatory_evidence",
    "gap_explanation",
    "recommended_action",
    "missing_or_weak_elements",
]


def read_comparison_report(comparison_id: str) -> dict:
    row = comparison_service.get_comparison_row_or_404(comparison_id)
    report_path = Path(row.get("report_json_path") or registry.comparison_root(comparison_id) / "final_report.json")
    if not report_path.exists():
        raise HTTPException(status_code=404, detail=f"Comparison report not found: {comparison_id}")
    return json.loads(report_path.read_text(encoding="utf-8"))


def read_page_report(comparison_id: str, sop_page_number: int) -> dict:
    comparison = comparison_service.get_comparison_row_or_404(comparison_id)
    run_dir = registry.comparison_root(comparison_id)
    path = run_dir / "page_reports" / f"sop_page_{int(sop_page_number):04d}.json"
    if not path.exists():
        raise HTTPException(status_code=404, detail=f"SOP page report not found: {sop_page_number}")
    payload = json.loads(path.read_text(encoding="utf-8"))
    sop = document_service.get_document_or_404(comparison["sop_document_id"])
    image_path = document_service.page_images_folder(sop) / f"page-{int(sop_page_number)}.png"
    payload["sop_page_image_url"] = (
        f"/assets/documents/{sop['document_id']}/page-image/{int(sop_page_number)}"
    )
    if not image_path.exists():
        payload["image_warning"] = f"SOP page image not found for page {int(sop_page_number)}"
    return payload


def ensure_final_report_csv(comparison_id: str) -> Path:
    row = _completed_comparison_or_400(comparison_id)
    run_dir = registry.comparison_root(comparison_id)
    path = run_dir / "final_report.csv"
    if path.exists():
        return path

    report = read_comparison_report(comparison_id)
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8", newline="") as file:
        writer = csv.DictWriter(file, fieldnames=CSV_COLUMNS)
        writer.writeheader()
        for page in _page_results(report):
            page_status = _page_status(page)
            page_findings = _page_findings(page)
            if not page_findings:
                writer.writerow(
                    {
                        "comparison_id": comparison_id,
                        "sop_page": page.get("sop_page", ""),
                        "page_status": page_status,
                    }
                )
                continue
            for finding in page_findings:
                writer.writerow(
                    {
                        "comparison_id": comparison_id,
                        "sop_page": finding.get("sop_page") or page.get("sop_page", ""),
                        "page_status": page_status,
                        "sop_topic": finding.get("sop_topic", ""),
                        "status": finding.get("status", ""),
                        "severity": finding.get("severity", ""),
                        "confidence": finding.get("confidence", ""),
                        "sop_evidence": finding.get("sop_evidence", ""),
                        "regulatory_topics": _join_value(
                            finding.get("regulatory_topics")
                            or finding.get("regulatory_topic")
                            or []
                        ),
                        "regulatory_pages_used": _join_value(
                            finding.get("regulatory_pages_used")
                            or finding.get("regulatory_pages")
                            or []
                        ),
                        "regulatory_evidence": finding.get("regulatory_evidence", ""),
                        "gap_explanation": finding.get("gap_explanation", ""),
                        "recommended_action": finding.get("recommended_action")
                        or finding.get("recommendation", ""),
                        "missing_or_weak_elements": _join_value(
                            finding.get("missing_or_weak_elements") or []
                        ),
                    }
                )
    return path


def ensure_thought_analysis_bundle(comparison_id: str) -> Path:
    row = _completed_comparison_or_400(comparison_id)
    run_dir = registry.comparison_root(comparison_id)
    path = run_dir / THOUGHT_ANALYSIS_BUNDLE_FILE
    if path.exists():
        return path

    report = read_comparison_report(comparison_id)
    regulatory = _document_or_none(row.get("regulatory_document_id", ""))
    sop = _document_or_none(row.get("sop_document_id", ""))
    missing_debug_artifacts: list[str] = []
    plans = _read_json_artifacts(run_dir, "plans", missing_debug_artifacts)
    evidence = _read_json_artifacts(run_dir, "evidence", missing_debug_artifacts)
    item_results = _read_json_artifacts(run_dir, "item_results", missing_debug_artifacts)
    traces = _read_json_artifacts(run_dir, "traces", missing_debug_artifacts)
    page_results = _read_json_artifacts(run_dir, "page_results", missing_debug_artifacts)

    run_config = _read_json_optional(run_dir, "run_config.json", missing_debug_artifacts)
    comparison_state = _read_json_optional(
        run_dir,
        "state/comparison_state.json",
        missing_debug_artifacts,
    )
    artifact_cleanup = _read_json_optional(
        run_dir,
        "artifact_cleanup.json",
        missing_debug_artifacts,
    )
    page_reports = _page_results(report)
    final_findings = _flatten_findings(page_reports)
    events = _comparison_job_events(comparison_id)
    retry_or_error_events = [
        event
        for event in events
        if _contains_any(event.get("step", ""), ("retry", "failed", "error"))
        or _contains_any(event.get("message", ""), ("retry", "failed", "error"))
    ]

    payload = {
        "comparison_id": comparison_id,
        "regulatory_document_id": row.get("regulatory_document_id"),
        "regulatory_filename": regulatory.get("original_filename") if regulatory else None,
        "sop_document_id": row.get("sop_document_id"),
        "sop_filename": sop.get("original_filename") if sop else None,
        "created_at": row.get("created_at") or None,
        "completed_at": row.get("finished_at") or None,
        "safety_note": (
            "This bundle contains observable decision traces and structured artifacts only; "
            "hidden chain-of-thought is not included."
        ),
        "status_taxonomy": STATUS_TAXONOMY,
        "model_configuration": run_config or {},
        "prompt_versions": {},
        "page_list_reviewed": [page.get("sop_page") for page in page_reports],
        "sop_page_summaries": [
            {
                "sop_page": page.get("sop_page"),
                "summary": page.get("sop_page_summary") or page.get("summary") or "",
                "page_status": _page_status(page),
            }
            for page in page_reports
        ],
        "sop_topics_extracted_per_page": _topics_from_plans(plans),
        "comparison_plans": plans,
        "matched_regulatory_topics": _matched_regulatory_topics(plans, final_findings),
        "selected_regulatory_pages": sorted(
            {
                int(page)
                for finding in final_findings
                for page in finding.get("regulatory_pages_used", [])
                if str(page).isdigit()
            }
        ),
        "primary_supporting_regulatory_evidence": evidence,
        "evidence_snippets_used": _evidence_snippets(final_findings, evidence),
        "structured_intermediate_outputs": {
            "item_results": item_results,
            "page_results": page_results,
            "traces": traces,
        },
        "page_reports": page_reports,
        "final_findings": final_findings,
        "status_decision_rationale": [
            {
                "sop_page": finding.get("sop_page"),
                "sop_topic": finding.get("sop_topic"),
                "status": finding.get("status"),
                "gap_explanation": finding.get("gap_explanation"),
            }
            for finding in final_findings
        ],
        "missing_or_weak_elements": [
            {
                "sop_page": finding.get("sop_page"),
                "sop_topic": finding.get("sop_topic"),
                "items": finding.get("missing_or_weak_elements", []),
            }
            for finding in final_findings
            if finding.get("missing_or_weak_elements")
        ],
        "recommended_actions": [
            {
                "sop_page": finding.get("sop_page"),
                "sop_topic": finding.get("sop_topic"),
                "recommended_action": finding.get("recommended_action")
                or finding.get("recommendation", ""),
            }
            for finding in final_findings
        ],
        "validation_post_processing_rules_applied": [],
        "comparison_state": comparison_state or {},
        "job_events": events,
        "retry_error_events": retry_or_error_events,
        "logs": _read_text_artifacts(run_dir / "logs"),
        "artifact_cleanup": artifact_cleanup or {},
        "missing_debug_artifacts": sorted(set(missing_debug_artifacts)),
    }
    _write_json(path, payload)
    return path


def _completed_comparison_or_400(comparison_id: str) -> dict[str, str]:
    row = comparison_service.get_comparison_row_or_404(comparison_id)
    if row.get("status") != "completed":
        raise HTTPException(
            status_code=400,
            detail=f"Comparison {comparison_id} is not completed.",
        )
    return row


def _write_json(path: Path, payload: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")


def _page_results(report: dict) -> list[dict]:
    return list(report.get("page_results") or report.get("page_reports") or [])


def _page_findings(page: dict) -> list[dict]:
    return list(page.get("gap_items") or page.get("findings") or [])


def _page_status(page: dict) -> str:
    return page.get("overall_status") or page.get("page_status") or "not_applicable"


def _join_value(value: Any) -> str:
    if isinstance(value, list):
        return "; ".join(str(item) for item in value)
    if isinstance(value, dict):
        return json.dumps(value, ensure_ascii=False, sort_keys=True)
    return str(value or "")


def _document_or_none(document_id: str) -> dict[str, str] | None:
    if not document_id:
        return None
    try:
        return document_service.get_document_or_404(document_id)
    except HTTPException:
        return None


def _read_json_file(path: Path) -> Any:
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError:
        return {"unparsed_text": path.read_text(encoding="utf-8", errors="replace")}


def _read_json_optional(root: Path, relative_path: str, missing: list[str]) -> Any | None:
    path = root / relative_path
    if not path.exists():
        missing.append(relative_path)
        return None
    return _read_json_file(path)


def _read_json_artifacts(root: Path, relative_dir: str, missing: list[str]) -> list[dict]:
    folder = root / relative_dir
    if not folder.exists():
        missing.append(relative_dir)
        return []
    artifacts = []
    for path in sorted(folder.rglob("*.json")):
        artifacts.append(
            {
                "path": path.relative_to(root).as_posix(),
                "data": _read_json_file(path),
            }
        )
    return artifacts


def _flatten_findings(page_reports: list[dict]) -> list[dict]:
    findings = []
    for page in page_reports:
        for finding in _page_findings(page):
            findings.append({**finding, "sop_page": finding.get("sop_page") or page.get("sop_page")})
    return findings


def _comparison_job_events(comparison_id: str) -> list[dict]:
    jobs = [
        job
        for job in registry.read_jobs()
        if job.get("comparison_id") == comparison_id
        and job.get("job_type") == "compare_documents"
    ]
    if not jobs:
        return []
    events = []
    for event in job_event_service.read_events(jobs[-1]["job_id"]).events:
        if hasattr(event, "model_dump"):
            events.append(event.model_dump(mode="json"))
        else:
            events.append(dict(event))
    return events


def _contains_any(value: str, needles: tuple[str, ...]) -> bool:
    value = str(value).lower()
    return any(needle in value for needle in needles)


def _topics_from_plans(plans: list[dict]) -> list[dict]:
    topics = []
    for artifact in plans:
        data = artifact.get("data") or {}
        topics.append(
            {
                "path": artifact.get("path"),
                "sop_page": data.get("sop_page"),
                "topics": [
                    item.get("sop_topic")
                    for item in data.get("plan_items", [])
                    if isinstance(item, dict)
                ],
            }
        )
    return topics


def _matched_regulatory_topics(plans: list[dict], findings: list[dict]) -> list[str]:
    topics = set()
    for finding in findings:
        for topic in finding.get("regulatory_topics", []):
            topics.add(str(topic))
    for artifact in plans:
        data = artifact.get("data") or {}
        for item in data.get("plan_items", []):
            if not isinstance(item, dict):
                continue
            for mapping in item.get("regulatory_mappings", []):
                if isinstance(mapping, dict) and mapping.get("regulatory_topic"):
                    topics.add(str(mapping["regulatory_topic"]))
    return sorted(topics)


def _evidence_snippets(findings: list[dict], evidence_artifacts: list[dict]) -> list[dict]:
    snippets = [
        {
            "sop_page": finding.get("sop_page"),
            "sop_topic": finding.get("sop_topic"),
            "sop_evidence": finding.get("sop_evidence"),
            "regulatory_evidence": finding.get("regulatory_evidence"),
        }
        for finding in findings
    ]
    for artifact in evidence_artifacts:
        snippets.append({"path": artifact.get("path"), "data": artifact.get("data")})
    return snippets


def _read_text_artifacts(folder: Path) -> list[dict[str, str]]:
    if not folder.exists():
        return []
    artifacts = []
    for path in sorted(folder.rglob("*")):
        if path.is_dir():
            continue
        artifacts.append(
            {
                "path": path.relative_to(folder.parent).as_posix(),
                "text": path.read_text(encoding="utf-8", errors="replace")[:20000],
            }
        )
    return artifacts

"""File-backed storage helpers for document comparison."""

from __future__ import annotations

import json
import os
from pathlib import Path
from typing import Iterable

from .schemas import (
    ComparisonPlan,
    ComparisonRunConfig,
    ComparisonStateFile,
    DocumentManifest,
    GapFinding,
    GapReport,
    PageComparisonResult,
    PageContext,
    RegulatoryEvidenceSummary,
    TopicEntry,
)

DOCUMENT_MANIFEST_FILE = "document_manifest.json"
CANONICAL_MANIFEST_FILE = "manifest.json"
RUN_CONFIG_FILE = "run_config.json"
COMPARISON_STATE_FILE = "comparison_state.json"
GAP_REPORT_JSON = "gap_report.json"
GAP_REPORT_MD = "gap_report.md"
EXECUTIVE_SUMMARY_MD = "executive_summary.md"
FINAL_REPORT_JSON = "final_report.json"
FINAL_REPORT_MD = "final_report.md"
FINAL_REPORT_CSV = "final_report.csv"

RUN_SUBDIRS = [
    "state",
    "plans",
    "evidence",
    "item_results",
    "page_results",
    "page_reports",
    "reports",
    "traces",
    "logs",
    "cache/regulatory_page_evidence",
    "cache/regulatory_topic_evidence",
]


def ensure_run_directories(comparison_run_dir: str | Path) -> None:
    root = Path(comparison_run_dir)
    for subdir in RUN_SUBDIRS:
        (root / subdir).mkdir(parents=True, exist_ok=True)


def _resolve_path(root: Path, value: str | Path | None) -> Path | None:
    if value is None:
        return None
    path = Path(value)
    return path if path.is_absolute() else root / path


def load_document_manifest(document_root: str | Path) -> DocumentManifest:
    root = Path(document_root)
    canonical_path = root / CANONICAL_MANIFEST_FILE
    legacy_path = root / DOCUMENT_MANIFEST_FILE
    path = canonical_path if canonical_path.exists() else legacy_path
    if not path.exists():
        raise FileNotFoundError(
            f"Document manifest not found: {canonical_path} or {legacy_path}"
        )
    data = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(data, dict):
        raise ValueError(f"Document manifest root must be an object: {path}")
    role = data.get("role") or data.get("document_type")
    return DocumentManifest(
        document_id=data["document_id"],
        role=role,
        root_path=root,
        source_file=_resolve_path(root, data["source_file"]),
        enriched_pages_folder=_resolve_path(root, data["enriched_pages_folder"]),
        page_images_folder=_resolve_path(
            root,
            data.get("page_images_folder") or "docling_assets/page_images",
        ),
        total_pages=int(data["total_pages"]),
        topic_index_path=_resolve_path(root, data.get("topic_index_path")),
    )


def _normalize_topic_payload(item: object) -> object:
    if not isinstance(item, dict):
        return item
    normalized = dict(item)
    normalized.pop("keywords", None)
    normalized.setdefault("assets", [])
    return normalized


def load_topic_index(topic_index_path: str | Path | None) -> list[TopicEntry]:
    if topic_index_path is None:
        raise FileNotFoundError("Regulatory topic_index_path is required.")
    path = Path(topic_index_path)
    if not path.exists():
        raise FileNotFoundError(f"Topic index not found: {path}")
    data = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(data, list):
        raise ValueError(f"Topic index root must be a list: {path}")
    return [TopicEntry.model_validate(_normalize_topic_payload(item)) for item in data]


def page_markdown_path(pages_folder: str | Path, page: int) -> Path:
    return Path(pages_folder) / f"page_{int(page):04d}.md"


def read_page_context(pages_folder: str | Path, page: int) -> PageContext:
    path = page_markdown_path(pages_folder, page)
    if not path.exists():
        raise FileNotFoundError(f"Page Markdown not found: {path}")
    return PageContext(
        page=int(page),
        path=path,
        markdown=path.read_text(encoding="utf-8", errors="replace"),
    )


def read_sop_page_window(
    sop_manifest: DocumentManifest,
    target_page: int,
) -> tuple[PageContext, PageContext | None]:
    target = read_page_context(sop_manifest.enriched_pages_folder, target_page)
    next_page_no = target_page + 1
    next_page = None
    if next_page_no <= sop_manifest.total_pages:
        next_page = read_page_context(sop_manifest.enriched_pages_folder, next_page_no)
    return target, next_page


def read_regulatory_pages(
    regulatory_manifest: DocumentManifest,
    pages: Iterable[int],
) -> list[PageContext]:
    seen = set()
    contexts = []
    for page in pages:
        page_no = int(page)
        if page_no in seen:
            continue
        seen.add(page_no)
        contexts.append(read_page_context(regulatory_manifest.enriched_pages_folder, page_no))
    return contexts


def _write_json_atomically(path: Path, payload: object) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp_path = path.with_name(f"{path.stem}.tmp{path.suffix}")
    tmp_path.write_text(
        json.dumps(payload, indent=2, ensure_ascii=False) + "\n",
        encoding="utf-8",
    )
    json.loads(tmp_path.read_text(encoding="utf-8"))
    os.replace(tmp_path, path)


def write_model_json(path: str | Path, model: object) -> Path:
    path = Path(path)
    if hasattr(model, "model_dump"):
        payload = model.model_dump(mode="json")
    else:
        payload = model
    _write_json_atomically(path, payload)
    return path


def write_run_config(
    comparison_run_dir: str | Path,
    config: ComparisonRunConfig,
) -> Path:
    return write_model_json(Path(comparison_run_dir) / RUN_CONFIG_FILE, config)


def state_file_path(comparison_run_dir: str | Path) -> Path:
    return Path(comparison_run_dir) / "state" / COMPARISON_STATE_FILE


def load_comparison_state(
    comparison_run_dir: str | Path,
    comparison_run_id: str,
    start_page: int,
    resume: bool,
) -> ComparisonStateFile:
    path = state_file_path(comparison_run_dir)
    if resume and path.exists():
        state = ComparisonStateFile.model_validate_json(path.read_text(encoding="utf-8"))
        if state.comparison_run_id != comparison_run_id:
            raise ValueError(
                "Comparison state run id mismatch: "
                f"{state.comparison_run_id} != {comparison_run_id}"
            )
        return state
    return ComparisonStateFile(
        comparison_run_id=comparison_run_id,
        last_completed_sop_page=max(0, start_page - 1),
        current_sop_page=start_page,
        status="in_progress",
    )


def write_comparison_state(
    comparison_run_dir: str | Path,
    state: ComparisonStateFile,
) -> Path:
    return write_model_json(state_file_path(comparison_run_dir), state)


def plan_path(comparison_run_dir: str | Path, sop_page: int) -> Path:
    return Path(comparison_run_dir) / "plans" / f"sop_page_{sop_page:04d}_plan.json"


def write_comparison_plan(
    comparison_run_dir: str | Path,
    plan: ComparisonPlan,
) -> Path:
    return write_model_json(plan_path(comparison_run_dir, plan.sop_page), plan)


def write_regulatory_pages_evidence(
    comparison_run_dir: str | Path,
    sop_page: int,
    item_number: int,
    contexts: list[PageContext],
) -> Path:
    payload = [
        {
            "page": context.page,
            "path": str(context.path),
            "markdown": context.markdown,
        }
        for context in contexts
    ]
    return write_model_json(
        Path(comparison_run_dir)
        / "evidence"
        / f"sop_page_{sop_page:04d}"
        / f"regulatory_pages_item_{item_number:03d}.json",
        payload,
    )


def write_compressed_evidence(
    comparison_run_dir: str | Path,
    sop_page: int,
    item_number: int,
    evidence: list[RegulatoryEvidenceSummary],
) -> Path:
    return write_model_json(
        Path(comparison_run_dir)
        / "evidence"
        / f"sop_page_{sop_page:04d}"
        / f"compressed_evidence_item_{item_number:03d}.json",
        [item.model_dump(mode="json") for item in evidence],
    )


def item_result_path(
    comparison_run_dir: str | Path,
    sop_page: int,
    item_number: int,
) -> Path:
    return (
        Path(comparison_run_dir)
        / "item_results"
        / f"sop_page_{sop_page:04d}_item_{item_number:03d}.json"
    )


def write_item_result(
    comparison_run_dir: str | Path,
    finding: GapFinding,
    item_number: int,
) -> Path:
    return write_model_json(
        item_result_path(comparison_run_dir, finding.sop_page, item_number),
        finding,
    )


def page_result_path(comparison_run_dir: str | Path, sop_page: int) -> Path:
    return Path(comparison_run_dir) / "page_reports" / f"sop_page_{sop_page:04d}.json"


def legacy_page_result_path(comparison_run_dir: str | Path, sop_page: int) -> Path:
    return Path(comparison_run_dir) / "page_results" / f"sop_page_{sop_page:04d}.json"


def write_page_result(
    comparison_run_dir: str | Path,
    page_result: PageComparisonResult,
) -> Path:
    path = write_model_json(page_result_path(comparison_run_dir, page_result.sop_page), page_result)
    write_model_json(legacy_page_result_path(comparison_run_dir, page_result.sop_page), page_result)
    return path


def read_page_results(comparison_run_dir: str | Path) -> list[PageComparisonResult]:
    results = []
    page_dir = Path(comparison_run_dir) / "page_reports"
    if not page_dir.exists():
        page_dir = Path(comparison_run_dir) / "page_results"
    for path in sorted(page_dir.glob("sop_page_*.json")):
        results.append(PageComparisonResult.model_validate_json(path.read_text(encoding="utf-8")))
    return results


def write_page_trace(
    comparison_run_dir: str | Path,
    sop_page: int,
    payload: object,
) -> Path:
    return write_model_json(
        Path(comparison_run_dir) / "traces" / f"sop_page_{sop_page:04d}_trace.json",
        payload,
    )


def write_gap_report_json(
    comparison_run_dir: str | Path,
    report: GapReport,
) -> Path:
    return write_model_json(Path(comparison_run_dir) / "reports" / GAP_REPORT_JSON, report)


def report_markdown_path(comparison_run_dir: str | Path) -> Path:
    return Path(comparison_run_dir) / "reports" / GAP_REPORT_MD


def final_report_json_path(comparison_run_dir: str | Path) -> Path:
    return Path(comparison_run_dir) / FINAL_REPORT_JSON


def final_report_markdown_path(comparison_run_dir: str | Path) -> Path:
    return Path(comparison_run_dir) / FINAL_REPORT_MD


def final_report_csv_path(comparison_run_dir: str | Path) -> Path:
    return Path(comparison_run_dir) / FINAL_REPORT_CSV


def executive_summary_path(comparison_run_dir: str | Path) -> Path:
    return Path(comparison_run_dir) / "reports" / EXECUTIVE_SUMMARY_MD

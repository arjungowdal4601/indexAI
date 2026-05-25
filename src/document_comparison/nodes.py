"""LangGraph node functions for document comparison."""

from __future__ import annotations

import json
from pathlib import Path
import re
from typing import Literal

from backend.services.retry_utils import run_with_retries

from .config import estimate_tokens
from .report import build_gap_report, write_reports
from .schemas import (
    ComparisonRunConfig,
    ComparisonStateFile,
    GapFinding,
    PageComparisonResult,
)
from .state import DocumentComparisonState
from .storage import (
    ensure_run_directories,
    item_result_path,
    load_comparison_state,
    load_document_manifest,
    load_topic_index,
    page_result_path,
    read_comparison_plan,
    read_compressed_evidence,
    read_item_result,
    read_page_results,
    read_regulatory_pages,
    read_regulatory_pages_evidence,
    read_sop_page_window,
    write_comparison_plan,
    write_comparison_state,
    write_compressed_evidence,
    write_item_result,
    write_page_result,
    write_page_trace,
    write_regulatory_pages_evidence,
    write_run_config,
)


_TOPIC_MATCH_STOPWORDS = {
    "and",
    "for",
    "the",
    "with",
    "from",
    "into",
    "that",
    "this",
    "during",
    "before",
    "after",
    "page",
    "pages",
}


def _topic_match_tokens(text: str) -> set[str]:
    return {
        token
        for token in re.findall(r"[a-z0-9]+", text.lower())
        if len(token) > 2 and token not in _TOPIC_MATCH_STOPWORDS
    }


def _find_canonical_topic_for_mapping(mapping, topic_index):
    requested_pages = {int(page) for page in mapping.regulatory_pages}
    if not requested_pages:
        return None

    page_candidates = [
        topic
        for topic in topic_index
        if requested_pages.issubset({int(page) for page in topic.pages})
    ]
    if not page_candidates:
        return None

    exact_page_candidates = [
        topic
        for topic in page_candidates
        if requested_pages == {int(page) for page in topic.pages}
    ]
    if len(exact_page_candidates) == 1:
        return exact_page_candidates[0]

    candidates = exact_page_candidates or page_candidates
    if len(candidates) == 1:
        return candidates[0]

    requested_tokens = _topic_match_tokens(mapping.regulatory_topic)
    scored = []
    for topic in candidates:
        candidate_tokens = _topic_match_tokens(f"{topic.topic} {topic.description}")
        scored.append((len(requested_tokens & candidate_tokens), topic))
    scored.sort(key=lambda item: item[0], reverse=True)
    if scored and scored[0][0] > 0 and (len(scored) == 1 or scored[0][0] > scored[1][0]):
        return scored[0][1]
    return None


def _regulatory_pages_for_item(state: DocumentComparisonState) -> list[int]:
    item = state["current_plan_item"]
    pages = []
    seen = set()
    if item is None:
        return []
    for mapping in item.regulatory_mappings:
        for page in mapping.regulatory_pages:
            page_no = int(page)
            if page_no in seen:
                continue
            seen.add(page_no)
            pages.append(page_no)
    return pages


def _emit_event(
    state: DocumentComparisonState,
    stage: str,
    step: str,
    message: str,
    progress_current: int | None = None,
    progress_total: int | None = None,
) -> None:
    callback = state.get("event_callback")
    if callback is not None:
        callback(stage, step, message, progress_current, progress_total)


def _sop_page_progress(state: DocumentComparisonState) -> tuple[int, int]:
    start_page = int(state.get("start_page") or 1)
    current_page = int(state["current_sop_page"])
    end_page = int(state.get("end_page") or current_page)
    total = max(1, end_page - start_page + 1)
    current = max(1, min(total, current_page - start_page + 1))
    return current, total


def _run_comparison_llm_call(
    state: DocumentComparisonState,
    step: str,
    waiting_message: str,
    retry_message,
    func,
):
    progress_current, progress_total = _sop_page_progress(state)
    _emit_event(
        state,
        "comparison",
        "waiting_for_llm",
        waiting_message,
        progress_current,
        progress_total,
    )
    return run_with_retries(
        func,
        on_retry=lambda attempt, exc: _emit_event(
            state,
            "comparison",
            "retry",
            retry_message(attempt, exc),
            progress_current,
            progress_total,
        ),
    )


def _format_page_contexts(page_contexts) -> str:
    return "\n\n".join(
        f"--- REGULATORY PAGE {context.page} ---\n{context.markdown}"
        for context in page_contexts
    )


def _format_compressed_evidence(evidence) -> str:
    return "\n\n".join(
        (
            f"--- REGULATORY PAGE {item.regulatory_page} / {item.regulatory_topic} ---\n"
            f"Useful: {item.useful}\n"
            f"Evidence: {item.evidence}\n"
            f"Obligations: {', '.join(item.obligations)}\n"
            f"Source excerpt: {item.source_excerpt}"
        )
        for item in evidence
    )


def _previous_page_summary(state: DocumentComparisonState) -> str:
    page_no = int(state["current_sop_page"]) - 1
    if page_no < 1:
        return ""
    path = page_result_path(state["comparison_run_dir"], page_no)
    if not path.exists():
        path = Path(state["comparison_run_dir"]) / "page_results" / f"sop_page_{page_no:04d}.json"
    if not path.exists():
        return ""
    result = PageComparisonResult.model_validate_json(path.read_text(encoding="utf-8"))
    return result.sop_page_summary


def _aggregate_page_status(findings: list[GapFinding]) -> str:
    if not findings:
        return "not_applicable"
    statuses = {finding.status for finding in findings}
    if "needs_human_review" in statuses:
        return "needs_human_review"
    if "missing" in statuses or "conflicting" in statuses:
        return "major_gaps"
    if "partially_compliant" in statuses:
        return "partial"
    if statuses == {"not_applicable"}:
        return "not_applicable"
    return "compliant"


def initialize_comparison_run_node(
    state: DocumentComparisonState,
) -> DocumentComparisonState:
    ensure_run_directories(state["comparison_run_dir"])
    return {}


def load_comparison_state_node(
    state: DocumentComparisonState,
) -> DocumentComparisonState:
    state_file = load_comparison_state(
        comparison_run_dir=state["comparison_run_dir"],
        comparison_run_id=state["comparison_run_id"],
        start_page=state["start_page"],
        resume=state.get("resume", True),
    )
    completed_page_paths = [Path(path) for path in state_file.completed_page_result_paths]
    current_page = int(state_file.current_sop_page)
    while page_result_path(state["comparison_run_dir"], current_page).exists():
        path = page_result_path(state["comparison_run_dir"], current_page)
        if path not in completed_page_paths:
            completed_page_paths.append(path)
        _emit_event(
            state,
            "comparison",
            "write_page_report",
            f"Completed SOP page {current_page} from existing checkpoint.",
        )
        state_file.last_completed_sop_page = current_page
        current_page += 1
        state_file.current_sop_page = current_page
        state_file.status = "in_progress"
    if completed_page_paths != [Path(path) for path in state_file.completed_page_result_paths]:
        state_file.completed_page_result_paths = [str(path) for path in completed_page_paths]
        write_comparison_state(state["comparison_run_dir"], state_file)
    return {
        "state_file": state_file,
        "current_sop_page": state_file.current_sop_page,
        "run_status": state_file.status,
        "completed_item_result_paths": [
            Path(path) for path in state_file.completed_item_result_paths
        ],
        "completed_page_result_paths": completed_page_paths,
    }


def load_document_manifests_node(
    state: DocumentComparisonState,
) -> DocumentComparisonState:
    _emit_event(state, "comparison", "load_manifests", "Loading regulatory and SOP manifests.")
    regulatory_manifest = load_document_manifest(state["regulatory_root"])
    sop_manifest = load_document_manifest(state["sop_root"])
    if regulatory_manifest.role != "regulatory":
        raise ValueError("Regulatory root manifest role must be 'regulatory'.")
    if sop_manifest.role != "sop":
        raise ValueError("SOP root manifest role must be 'sop'.")
    if regulatory_manifest.topic_index_path is None:
        raise FileNotFoundError("Regulatory document manifest must include topic_index_path.")

    end_page = state.get("end_page") or sop_manifest.total_pages
    run_config = ComparisonRunConfig(
        comparison_run_id=state["comparison_run_id"],
        regulatory_doc_id=regulatory_manifest.document_id,
        sop_doc_id=sop_manifest.document_id,
        regulatory_root=state["regulatory_root"],
        sop_root=state["sop_root"],
        start_page=state["start_page"],
        end_page=end_page,
        max_direct_regulatory_pages=state["max_direct_regulatory_pages"],
        max_direct_estimated_tokens=state["max_direct_estimated_tokens"],
    )
    write_run_config(state["comparison_run_dir"], run_config)
    updates = {
        "regulatory_manifest": regulatory_manifest,
        "sop_manifest": sop_manifest,
        "end_page": end_page,
        "run_config": run_config,
    }
    state_file = state.get("state_file")
    if state_file is not None and int(state.get("current_sop_page") or 1) > int(end_page):
        state_file.status = "completed"
        write_comparison_state(state["comparison_run_dir"], state_file)
        updates["state_file"] = state_file
        updates["run_status"] = "completed"
    return updates


def load_regulatory_topic_index_node(
    state: DocumentComparisonState,
) -> DocumentComparisonState:
    _emit_event(
        state,
        "comparison",
        "load_regulatory_index",
        "Loading regulatory topic index for comparison routing.",
    )
    return {
        "regulatory_topic_index": load_topic_index(
            state["regulatory_manifest"].topic_index_path
        )
    }


def read_sop_page_window_node(
    state: DocumentComparisonState,
) -> DocumentComparisonState:
    progress_current, progress_total = _sop_page_progress(state)
    _emit_event(
        state,
        "comparison",
        "read_sop_page_window",
        f"Reading SOP page {state['current_sop_page']} of {state['end_page']} and continuity context.",
        progress_current,
        progress_total,
    )
    target, next_page = read_sop_page_window(
        state["sop_manifest"],
        int(state["current_sop_page"]),
    )
    return {
        "sop_target_page": target,
        "sop_next_page": next_page,
        "previous_sop_page_summary": _previous_page_summary(state),
        "pending_plan_items": None,
        "current_plan_item": None,
        "current_page_findings": [],
        "current_page_item_result_paths": [],
        "compressed_regulatory_evidence": [],
    }


def plan_sop_page_comparison_node(
    state: DocumentComparisonState,
) -> DocumentComparisonState:
    progress_current, progress_total = _sop_page_progress(state)
    _emit_event(
        state,
        "comparison",
        "plan_sop_page",
        f"Planning comparison for SOP page {state['current_sop_page']} of {state['end_page']}.",
        progress_current,
        progress_total,
    )
    existing_plan = read_comparison_plan(
        state["comparison_run_dir"],
        int(state["current_sop_page"]),
    )
    if existing_plan is not None:
        return {"comparison_plan": existing_plan}
    topic_index_json = json.dumps(
        [topic.model_dump(mode="json") for topic in state["regulatory_topic_index"]],
        indent=2,
        ensure_ascii=False,
    )
    plan = _run_comparison_llm_call(
        state,
        "plan_sop_page",
        f"Waiting for LLM response for SOP page {state['current_sop_page']} plan",
        lambda attempt, exc: (
            f"Retrying SOP page {state['current_sop_page']} plan, attempt {attempt}: "
            f"{type(exc).__name__}: {exc}"
        ),
        lambda: state["client"].plan_sop_page_comparison(
            state["sop_target_page"],
            state.get("sop_next_page"),
            state.get("previous_sop_page_summary", ""),
            topic_index_json,
        ),
    )
    write_comparison_plan(state["comparison_run_dir"], plan)
    return {"comparison_plan": plan}


def validate_comparison_plan_node(
    state: DocumentComparisonState,
) -> DocumentComparisonState:
    plan = state["comparison_plan"]
    if plan.sop_page != state["current_sop_page"]:
        raise ValueError(
            f"Comparison plan SOP page mismatch: {plan.sop_page} != {state['current_sop_page']}"
        )
    topics_by_name = {topic.topic: topic for topic in state["regulatory_topic_index"]}
    repaired_mappings = False
    for item in plan.plan_items:
        if item.sop_page != plan.sop_page:
            raise ValueError(
                f"Plan item SOP page mismatch: {item.sop_page} != {plan.sop_page}"
            )
        for mapping in item.regulatory_mappings:
            topic = topics_by_name.get(mapping.regulatory_topic)
            if topic is None:
                topic = _find_canonical_topic_for_mapping(
                    mapping, state["regulatory_topic_index"]
                )
                if topic is None:
                    raise ValueError(
                        f"Regulatory topic not in topic index: {mapping.regulatory_topic}"
                    )
                mapping.regulatory_topic = topic.topic
                repaired_mappings = True
            topic_pages = set(topic.pages)
            for page in mapping.regulatory_pages:
                if page not in topic_pages:
                    raise ValueError(
                        f"Regulatory page {page} for topic {mapping.regulatory_topic} "
                        "is not in topic index."
                    )
                page_path = (
                    state["regulatory_manifest"].enriched_pages_folder
                    / f"page_{page:04d}.md"
                )
                if not page_path.exists():
                    raise FileNotFoundError(f"Regulatory page Markdown not found: {page_path}")
    if repaired_mappings and "comparison_run_dir" in state:
        write_comparison_plan(state["comparison_run_dir"], plan)
    return {}


def initialize_plan_item_queue_node(
    state: DocumentComparisonState,
) -> DocumentComparisonState:
    queue = state.get("pending_plan_items")
    findings = state.get("current_page_findings", [])
    item_paths = state.get("current_page_item_result_paths", [])
    if queue is None:
        queue = list(state["comparison_plan"].plan_items)
        findings = []
        item_paths = []
    else:
        queue = list(queue)

    while queue:
        current = queue.pop(0)
        item_number = len(state["comparison_plan"].plan_items) - len(queue)
        existing_finding = read_item_result(
            state["comparison_run_dir"],
            int(state["current_sop_page"]),
            item_number,
        )
        if existing_finding is None:
            return {
                "pending_plan_items": queue,
                "current_plan_item": current,
                "current_item_number": item_number,
                "current_page_findings": findings,
                "current_page_item_result_paths": item_paths,
            }
        path = item_result_path(
            state["comparison_run_dir"],
            int(state["current_sop_page"]),
            item_number,
        )
        findings = findings + [existing_finding]
        item_paths = item_paths + [path]

    return {
        "pending_plan_items": [],
        "current_plan_item": None,
        "current_page_findings": findings,
        "current_page_item_result_paths": item_paths,
        "completed_item_result_paths": state.get("completed_item_result_paths", [])
        + [
            path
            for path in item_paths
            if path not in state.get("completed_item_result_paths", [])
        ],
    }


def read_regulatory_evidence_node(
    state: DocumentComparisonState,
) -> DocumentComparisonState:
    pages = _regulatory_pages_for_item(state)
    _emit_event(
        state,
        "comparison",
        "read_regulatory_evidence",
        f"Reading regulatory evidence pages: {', '.join(str(page) for page in pages)}.",
    )
    existing_contexts = read_regulatory_pages_evidence(
        state["comparison_run_dir"],
        state["current_sop_page"],
        state["current_item_number"],
    )
    if existing_contexts is not None:
        return {"regulatory_page_contexts": existing_contexts}
    contexts = read_regulatory_pages(state["regulatory_manifest"], pages)
    write_regulatory_pages_evidence(
        state["comparison_run_dir"],
        state["current_sop_page"],
        state["current_item_number"],
        contexts,
    )
    return {"regulatory_page_contexts": contexts}


def estimate_comparison_context_node(
    state: DocumentComparisonState,
) -> DocumentComparisonState:
    item = state["current_plan_item"]
    sop_text = ""
    if item is not None:
        sop_text = (
            f"{item.sop_topic}\n{item.sop_claim_or_requirement}\n"
            f"{item.sop_evidence_excerpt}\n{item.comparison_focus}"
        )
    regulatory_text = _format_page_contexts(state["regulatory_page_contexts"])
    estimated = estimate_tokens(sop_text + "\n\n" + regulatory_text)
    mode: Literal["direct", "compressed"] = (
        "direct"
        if len(state["regulatory_page_contexts"]) <= state["max_direct_regulatory_pages"]
        and estimated <= state["max_direct_estimated_tokens"]
        else "compressed"
    )
    return {
        "estimated_context_tokens": estimated,
        "comparison_memory_mode": mode,
    }


def compress_regulatory_evidence_node(
    state: DocumentComparisonState,
) -> DocumentComparisonState:
    item = state["current_plan_item"]
    if item is None:
        return {"compressed_regulatory_evidence": []}
    existing_evidence = read_compressed_evidence(
        state["comparison_run_dir"],
        state["current_sop_page"],
        state["current_item_number"],
    )
    if existing_evidence is not None:
        return {"compressed_regulatory_evidence": existing_evidence}
    _emit_event(
        state,
        "comparison",
        "compress_regulatory_evidence",
        f"Compressing regulatory evidence for SOP page {state['current_sop_page']} item {state['current_item_number']}.",
    )
    evidence = [
        _run_comparison_llm_call(
            state,
            "compress_regulatory_evidence",
            (
                f"Waiting for LLM response for regulatory page {context.page} "
                f"compression on SOP page {state['current_sop_page']}"
            ),
            lambda attempt, exc, context=context: (
                f"Retrying SOP page {state['current_sop_page']} evidence compression, "
                f"attempt {attempt}: {type(exc).__name__}: {exc}"
            ),
            lambda context=context: state["client"].compress_regulatory_evidence(item, context),
        )
        for context in state["regulatory_page_contexts"]
    ]
    write_compressed_evidence(
        state["comparison_run_dir"],
        state["current_sop_page"],
        state["current_item_number"],
        evidence,
    )
    return {"compressed_regulatory_evidence": evidence}


def execute_gap_analysis_node(
    state: DocumentComparisonState,
) -> DocumentComparisonState:
    item = state["current_plan_item"]
    if item is None:
        raise RuntimeError("No current comparison plan item is available.")
    progress_current, progress_total = _sop_page_progress(state)
    _emit_event(
        state,
        "comparison",
        "analyze_gap_item",
        f"Analyzing SOP page {state['current_sop_page']} item {state['current_item_number']}.",
        progress_current,
        progress_total,
    )
    if state["comparison_memory_mode"] == "compressed":
        regulatory_evidence = _format_compressed_evidence(
            state.get("compressed_regulatory_evidence", [])
        )
    else:
        regulatory_evidence = _format_page_contexts(state["regulatory_page_contexts"])
    finding = _run_comparison_llm_call(
        state,
        "analyze_gap_item",
        (
            f"Waiting for LLM response for gap item {state['current_item_number']} "
            f"on SOP page {state['current_sop_page']}"
        ),
        lambda attempt, exc: (
            f"Retrying gap item {state['current_item_number']} on SOP page "
            f"{state['current_sop_page']}, attempt {attempt}: {type(exc).__name__}: {exc}"
        ),
        lambda: state["client"].execute_gap_analysis(
            item,
            regulatory_evidence,
            state["comparison_memory_mode"],
        ),
    )
    return {"current_gap_finding": finding}


def write_item_result_node(
    state: DocumentComparisonState,
) -> DocumentComparisonState:
    finding = state["current_gap_finding"]
    path = write_item_result(
        state["comparison_run_dir"],
        finding,
        state["current_item_number"],
    )
    return {
        "current_page_findings": state.get("current_page_findings", []) + [finding],
        "current_page_item_result_paths": state.get("current_page_item_result_paths", [])
        + [path],
        "completed_item_result_paths": state.get("completed_item_result_paths", [])
        + [path],
    }


def aggregate_sop_page_result_node(
    state: DocumentComparisonState,
) -> DocumentComparisonState:
    findings = state.get("current_page_findings", [])
    page_result = PageComparisonResult(
        sop_page=state["current_sop_page"],
        sop_page_summary=state["comparison_plan"].page_summary,
        findings=findings,
        page_status=_aggregate_page_status(findings),  # type: ignore[arg-type]
        high_priority_count=sum(
            1 for finding in findings if finding.severity in {"critical", "major"}
        ),
        human_review_count=sum(
            1 for finding in findings if finding.status == "needs_human_review"
        ),
    )
    return {"page_result": page_result}


def write_page_result_node(
    state: DocumentComparisonState,
) -> DocumentComparisonState:
    progress_current, progress_total = _sop_page_progress(state)
    _emit_event(
        state,
        "comparison",
        "write_page_report",
        f"Completed SOP page {state['current_sop_page']} of {state['end_page']}.",
        progress_current,
        progress_total,
    )
    path = write_page_result(state["comparison_run_dir"], state["page_result"])
    completed_page_paths = state.get("completed_page_result_paths", []) + [path]
    next_page = state["current_sop_page"] + 1
    end_page = int(state["end_page"])
    status: Literal["in_progress", "completed"] = (
        "completed" if next_page > end_page else "in_progress"
    )
    state_file = ComparisonStateFile(
        comparison_run_id=state["comparison_run_id"],
        last_completed_sop_page=state["current_sop_page"],
        current_sop_page=next_page,
        completed_item_result_paths=[
            str(path) for path in state.get("completed_item_result_paths", [])
        ],
        completed_page_result_paths=[str(path) for path in completed_page_paths],
        status=status,
    )
    write_comparison_state(state["comparison_run_dir"], state_file)
    write_page_trace(
        state["comparison_run_dir"],
        state["current_sop_page"],
        {
            "sop_page": state["current_sop_page"],
            "plan": state["comparison_plan"].model_dump(mode="json"),
            "item_result_paths": [str(path) for path in state.get("current_page_item_result_paths", [])],
            "memory_mode_last_item": state.get("comparison_memory_mode"),
            "estimated_context_tokens_last_item": state.get("estimated_context_tokens"),
        },
    )
    return {
        "state_file": state_file,
        "run_status": status,
        "current_sop_page": next_page,
        "completed_page_result_paths": completed_page_paths,
        "pending_plan_items": None,
        "current_plan_item": None,
        "current_page_findings": [],
        "current_page_item_result_paths": [],
    }


def aggregate_final_gap_report_node(
    state: DocumentComparisonState,
) -> DocumentComparisonState:
    _emit_event(
        state,
        "comparison",
        "aggregate_final_report",
        "Aggregating final gap report.",
    )
    page_results = read_page_results(state["comparison_run_dir"])
    report = build_gap_report(
        comparison_run_id=state["comparison_run_id"],
        regulatory_doc_id=state["regulatory_manifest"].document_id,
        sop_doc_id=state["sop_manifest"].document_id,
        page_results=page_results,
    )
    json_path, markdown_path, summary_path = write_reports(
        state["comparison_run_dir"],
        report,
    )
    return {
        "final_report": report,
        "gap_report_path": json_path,
        "markdown_report_path": markdown_path,
        "executive_summary_path": summary_path,
    }

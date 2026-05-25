"""LangGraph wiring and public runner for document comparison."""

from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path
from typing import Callable

from langgraph.graph import END, START, StateGraph

from .config import (
    DEFAULT_COMPARISON_RUNS_DIR,
    DEFAULT_MAX_DIRECT_ESTIMATED_TOKENS,
    DEFAULT_MAX_DIRECT_REGULATORY_PAGES,
)
from .llm import ComparisonClient, LangChainComparisonClient
from .nodes import (
    aggregate_final_gap_report_node,
    aggregate_sop_page_result_node,
    compress_regulatory_evidence_node,
    estimate_comparison_context_node,
    execute_gap_analysis_node,
    initialize_comparison_run_node,
    initialize_plan_item_queue_node,
    load_comparison_state_node,
    load_document_manifests_node,
    load_regulatory_topic_index_node,
    plan_sop_page_comparison_node,
    read_regulatory_evidence_node,
    read_sop_page_window_node,
    validate_comparison_plan_node,
    write_item_result_node,
    write_page_result_node,
)
from .routers import (
    route_after_context_estimate,
    route_after_page_result,
    route_after_plan_item_queue,
    route_after_regulatory_index,
)
from .schemas import ComparisonRunOutput
from .state import DocumentComparisonState
from .storage import (
    executive_summary_path,
    final_report_json_path,
    final_report_markdown_path,
    page_result_path,
)


def build_document_comparison_graph():
    builder = StateGraph(DocumentComparisonState)

    builder.add_node("initialize_comparison_run", initialize_comparison_run_node)
    builder.add_node("load_comparison_state", load_comparison_state_node)
    builder.add_node("load_document_manifests", load_document_manifests_node)
    builder.add_node("load_regulatory_topic_index", load_regulatory_topic_index_node)
    builder.add_node("read_sop_page_window", read_sop_page_window_node)
    builder.add_node("plan_sop_page_comparison", plan_sop_page_comparison_node)
    builder.add_node("validate_comparison_plan", validate_comparison_plan_node)
    builder.add_node("initialize_plan_item_queue", initialize_plan_item_queue_node)
    builder.add_node("read_regulatory_evidence", read_regulatory_evidence_node)
    builder.add_node("estimate_comparison_context", estimate_comparison_context_node)
    builder.add_node("compress_regulatory_evidence", compress_regulatory_evidence_node)
    builder.add_node("execute_gap_analysis", execute_gap_analysis_node)
    builder.add_node("write_item_result", write_item_result_node)
    builder.add_node("aggregate_sop_page_result", aggregate_sop_page_result_node)
    builder.add_node("write_page_result", write_page_result_node)
    builder.add_node("aggregate_final_gap_report", aggregate_final_gap_report_node)

    builder.add_edge(START, "initialize_comparison_run")
    builder.add_edge("initialize_comparison_run", "load_comparison_state")
    builder.add_edge("load_comparison_state", "load_document_manifests")
    builder.add_edge("load_document_manifests", "load_regulatory_topic_index")
    builder.add_conditional_edges(
        "load_regulatory_topic_index",
        route_after_regulatory_index,
        {
            "read_page": "read_sop_page_window",
            "finished": "aggregate_final_gap_report",
        },
    )
    builder.add_edge("read_sop_page_window", "plan_sop_page_comparison")
    builder.add_edge("plan_sop_page_comparison", "validate_comparison_plan")
    builder.add_edge("validate_comparison_plan", "initialize_plan_item_queue")

    builder.add_conditional_edges(
        "initialize_plan_item_queue",
        route_after_plan_item_queue,
        {
            "next_item": "read_regulatory_evidence",
            "page_complete": "aggregate_sop_page_result",
        },
    )
    builder.add_edge("read_regulatory_evidence", "estimate_comparison_context")
    builder.add_conditional_edges(
        "estimate_comparison_context",
        route_after_context_estimate,
        {
            "direct": "execute_gap_analysis",
            "compressed": "compress_regulatory_evidence",
        },
    )
    builder.add_edge("compress_regulatory_evidence", "execute_gap_analysis")
    builder.add_edge("execute_gap_analysis", "write_item_result")
    builder.add_edge("write_item_result", "initialize_plan_item_queue")
    builder.add_edge("aggregate_sop_page_result", "write_page_result")
    builder.add_conditional_edges(
        "write_page_result",
        route_after_page_result,
        {
            "next_page": "read_sop_page_window",
            "finished": "aggregate_final_gap_report",
        },
    )
    builder.add_edge("aggregate_final_gap_report", END)

    return builder.compile()


def export_graph_mermaid(output_path: str | Path = "document_comparison_graph.mmd") -> None:
    graph = build_document_comparison_graph()
    mermaid = graph.get_graph().draw_mermaid()
    Path(output_path).write_text(mermaid, encoding="utf-8")


def _default_comparison_run_id(regulatory_root: Path, sop_root: Path) -> str:
    timestamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    return f"{regulatory_root.name}__{sop_root.name}__{timestamp}"


def run_document_comparison(
    regulatory_root: str | Path,
    sop_root: str | Path,
    comparison_run_dir: str | Path | None = None,
    comparison_run_id: str | None = None,
    client: ComparisonClient | None = None,
    model: str | None = None,
    start_page: int = 1,
    end_page: int | None = None,
    resume: bool = True,
    max_direct_regulatory_pages: int = DEFAULT_MAX_DIRECT_REGULATORY_PAGES,
    max_direct_estimated_tokens: int = DEFAULT_MAX_DIRECT_ESTIMATED_TOKENS,
    event_callback: Callable[[str, str, str, int | None, int | None], None] | None = None,
) -> ComparisonRunOutput:
    regulatory_root = Path(regulatory_root)
    sop_root = Path(sop_root)
    run_id = comparison_run_id or _default_comparison_run_id(regulatory_root, sop_root)
    run_dir = (
        Path(comparison_run_dir)
        if comparison_run_dir is not None
        else DEFAULT_COMPARISON_RUNS_DIR / run_id
    )
    comparison_client = client or LangChainComparisonClient(model=model)
    graph = build_document_comparison_graph()
    result = graph.invoke(
        {
            "comparison_run_id": run_id,
            "comparison_run_dir": run_dir,
            "regulatory_root": regulatory_root,
            "sop_root": sop_root,
            "start_page": int(start_page),
            "end_page": int(end_page) if end_page is not None else None,
            "resume": bool(resume),
            "max_direct_regulatory_pages": int(max_direct_regulatory_pages),
            "max_direct_estimated_tokens": int(max_direct_estimated_tokens),
            "event_callback": event_callback,
            "client": comparison_client,
        }
    )
    final_report = result["final_report"]
    page_paths = [
        page_result_path(run_dir, page_result.sop_page)
        for page_result in final_report.page_results
    ]
    return ComparisonRunOutput(
        comparison_run_id=run_id,
        comparison_run_dir=run_dir,
        gap_report_path=final_report_json_path(run_dir),
        markdown_report_path=final_report_markdown_path(run_dir),
        executive_summary_path=executive_summary_path(run_dir),
        page_result_paths=page_paths,
    )
